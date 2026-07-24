"""Configuration & secrets.

Two sources merged into one immutable ``Settings`` object:

* ``.env`` (chmod 600, gitignored) -> secrets, via pydantic-settings.
* ``config/meridian.yaml`` (the file Mason edits most) -> non-secret config.

Everything downstream imports :func:`get_settings`. Paths are anchored to
``MERIDIAN_HOME`` (defaults to the repo root) so the code is path-agnostic and can
develop on any machine yet deploy on the Mac Mini unchanged.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --------------------------------------------------------------------------------------
# Path anchoring
# --------------------------------------------------------------------------------------

# src/meridian/config.py -> repo root is three parents up.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _home() -> Path:
    import os

    env = os.environ.get("MERIDIAN_HOME")
    return Path(env).expanduser().resolve() if env else _REPO_ROOT


# --------------------------------------------------------------------------------------
# Secrets (.env)
# --------------------------------------------------------------------------------------


class Secrets(BaseSettings):
    """Secret values, read from environment / ``.env``. Never logged, never sent to LLMs."""

    model_config = SettingsConfigDict(
        env_file=str(_home() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    anthropic_api_key: str = ""
    fred_api_key: str = ""
    alpaca_key_id: str = ""
    alpaca_secret_key: str = ""
    finnhub_key: str = ""
    coingecko_key: str = ""
    sec_user_agent: str = "Your Name your-email@example.com"

    ntfy_base_url: str = "https://ntfy.sh"
    ntfy_topic_briefs: str = "meridian-briefs"
    ntfy_topic_alerts: str = "meridian-alerts"
    ntfy_token: str = ""
    pushover_token: str = ""
    pushover_user: str = ""
    imessage_to: str = ""

    kalshi_api_base: str = "https://api.elections.kalshi.com/trade-api/v2"
    tailnet_base_url: str = ""

    def has(self, name: str) -> bool:
        """True if a non-empty secret is present (used to enable/disable connectors)."""
        return bool(getattr(self, name, "") or "")


# --------------------------------------------------------------------------------------
# Non-secret config (meridian.yaml) — typed models
# --------------------------------------------------------------------------------------


class Watchlist(BaseModel):
    holdings: list[str] = Field(default_factory=list)
    active: list[str] = Field(default_factory=list)
    monitor: list[str] = Field(default_factory=list)

    def all(self) -> list[str]:
        seen: dict[str, None] = {}
        for t in [*self.holdings, *self.active, *self.monitor]:
            seen.setdefault(t, None)
        return list(seen)


class Budgets(BaseModel):
    llm_daily_usd: float = 3.00
    llm_monthly_usd: float = 60.00
    sunday_multiplier: float = 2.0


class QuietHours(BaseModel):
    start: str = "23:00"
    end: str = "07:00"
    override_priority: str = "P0"


class Notifications(BaseModel):
    quiet_hours: QuietHours = Field(default_factory=QuietHours)


class BriefSlot(BaseModel):
    at: str = "07:45"
    audio: bool = False
    conditional: bool = False
    min_materiality: int = 0
    model: str | None = None


class Briefs(BaseModel):
    morning: BriefSlot = Field(default_factory=lambda: BriefSlot(at="07:45", audio=True))
    midday: BriefSlot = Field(
        default_factory=lambda: BriefSlot(at="12:30", conditional=True, min_materiality=3)
    )
    closing: BriefSlot = Field(default_factory=lambda: BriefSlot(at="16:20"))
    sunday: BriefSlot = Field(default_factory=lambda: BriefSlot(at="17:00", model="opus"))
    crypto_weekend: BriefSlot = Field(default_factory=lambda: BriefSlot(at="Sat 10:00"))


class ModelTiers(BaseModel):
    """Anthropic model ids, cost-tiered by task difficulty."""

    triage: str = "claude-haiku-4-5-20251001"
    analyst: str = "claude-sonnet-5"
    composer: str = "claude-sonnet-5"
    deep: str = "claude-opus-4-8"  # Sunday Setup, Red Team, Calibration


class MeridianConfig(BaseModel):
    timezone: str = "America/New_York"
    watchlist: Watchlist = Field(default_factory=Watchlist)
    benchmarks: list[str] = Field(default_factory=list)
    sector_etfs: list[str] = Field(default_factory=list)
    budgets: Budgets = Field(default_factory=Budgets)
    notifications: Notifications = Field(default_factory=Notifications)
    briefs: Briefs = Field(default_factory=Briefs)
    models: ModelTiers = Field(default_factory=ModelTiers)
    redact_portfolio: bool = False


# --------------------------------------------------------------------------------------
# Top-level Settings — the object everything imports
# --------------------------------------------------------------------------------------


class Settings(BaseModel):
    model_config = {"arbitrary_types_allowed": True, "frozen": True}

    home: Path
    secrets: Secrets
    config: MeridianConfig

    # ---- computed paths ----
    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "meridian.db"

    @property
    def parquet_dir(self) -> Path:
        return self.data_dir / "parquet"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def migrations_dir(self) -> Path:
        return self.home / "migrations"

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def web_dist(self) -> Path:
        return self.home / "web" / "dist"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.config.timezone)

    def base_url(self) -> str:
        """Public (tailnet) base URL for deep links; falls back to the local daemon port."""
        import os

        port = os.environ.get("MERIDIAN_PORT", "8788")
        return self.secrets.tailnet_base_url or f"http://localhost:{port}"

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.parquet_dir / "daily",
            self.parquet_dir / "intraday",
            self.audio_dir,
            self.backups_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_portfolio(settings: Settings | None = None) -> dict[str, Any]:
    """Load config/portfolio.yaml (gitignored). Returns {} if absent."""
    s = settings or get_settings()
    return _load_yaml(s.config_dir / "portfolio.yaml")


def load_alert_rules(settings: Settings | None = None) -> list[dict[str, Any]]:
    """Load config/alerts.yaml -> list of rule dicts."""
    s = settings or get_settings()
    data = _load_yaml(s.config_dir / "alerts.yaml")
    if isinstance(data, dict):
        return data.get("rules", [])
    return data or []


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    home = _home()
    raw = _load_yaml(home / "config" / "meridian.yaml")
    cfg = MeridianConfig(**raw) if raw else MeridianConfig()
    # holdings tier mirrors portfolio.yaml tickers automatically.
    port = _load_yaml(home / "config" / "portfolio.yaml")
    holdings: list[str] = []
    for acct in port.get("accounts", []):
        for pos in acct.get("positions", []):
            t = pos.get("ticker")
            if t and t not in holdings:
                holdings.append(t)
    if holdings:
        cfg.watchlist.holdings = holdings
    return Settings(home=home, secrets=Secrets(), config=cfg)


def reload_settings() -> Settings:
    """Clear the cache and reload (used after config edits)."""
    get_settings.cache_clear()
    return get_settings()


TierName = Literal["holding", "active", "monitor", "benchmark"]
