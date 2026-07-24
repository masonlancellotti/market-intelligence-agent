"""Bulk OHLCV history — Parquet files queried via DuckDB.

5y of daily bars for hundreds of tickers would bloat SQLite, so history lives in
``data/parquet/daily/{TICKER}.parquet``. SQLite keeps only ``quotes_latest``. This
module owns backfill (yfinance primary — Stooq is bot-gated, see docs/DECISIONS.md D-007)
and read access used by the signal engine.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from loguru import logger

from ..config import Settings, get_settings
from ..util import norm_ticker

DAILY_COLS = ["date", "open", "high", "low", "close", "adj_close", "volume"]


def daily_path(ticker: str, settings: Settings | None = None) -> Path:
    s = settings or get_settings()
    return s.parquet_dir / "daily" / f"{norm_ticker(ticker).replace('/', '_')}.parquet"


# -- read -----------------------------------------------------------------------
def read_daily(
    ticker: str, lookback: int | None = None, settings: Settings | None = None
) -> pl.DataFrame:
    p = daily_path(ticker, settings)
    if not p.exists():
        return pl.DataFrame(schema=dict.fromkeys(DAILY_COLS, pl.Float64) | {"date": pl.Utf8})
    df = pl.read_parquet(p).sort("date")
    if lookback:
        df = df.tail(lookback)
    return df


def has_history(ticker: str, settings: Settings | None = None) -> bool:
    return daily_path(ticker, settings).exists()


# -- fetch (yfinance) -----------------------------------------------------------
def fetch_daily_yf(ticker: str, years: int = 5) -> pl.DataFrame:
    import yfinance as yf

    t = norm_ticker(ticker)
    period = f"{years}y" if years <= 10 else "max"
    hist = yf.Ticker(t).history(period=period, interval="1d", auto_adjust=False, actions=False)
    if hist is None or hist.empty:
        raise RuntimeError(f"yfinance returned no rows for {t}")
    hist = hist.reset_index()
    # normalise column names across yfinance versions
    ren = {c: c.lower().replace(" ", "_") for c in hist.columns}
    hist = hist.rename(columns=ren)
    date_col = (
        "date"
        if "date" in hist.columns
        else ("datetime" if "datetime" in hist.columns else hist.columns[0])
    )
    out = pl.DataFrame(
        {
            "date": [d.strftime("%Y-%m-%d") for d in hist[date_col]],
            "open": _col(hist, "open"),
            "high": _col(hist, "high"),
            "low": _col(hist, "low"),
            "close": _col(hist, "close"),
            "adj_close": _col(hist, "adj_close", fallback="close"),
            "volume": _col(hist, "volume"),
        }
    )
    return out.unique(subset=["date"], keep="last").sort("date")


def _col(df, name: str, fallback: str | None = None):
    import math

    if name in df.columns:
        return [
            None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v)
            for v in df[name]
        ]
    if fallback and fallback in df.columns:
        return [float(v) for v in df[fallback]]
    return [None] * len(df)


# -- write ----------------------------------------------------------------------
def write_daily(ticker: str, df: pl.DataFrame, settings: Settings | None = None) -> int:
    p = daily_path(ticker, settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort("date")
    df.write_parquet(p)
    return df.height


def _update_latest_from_history(
    ticker: str, df: pl.DataFrame, settings: Settings | None = None
) -> None:
    """Seed quotes_latest from the last two daily bars (marked stale — it's EOD data)."""
    if df.height == 0:
        return
    from .base import BaseConnector

    class _Seed(BaseConnector):
        name = "history_seed"

    seeder = _Seed(settings)
    last = df.row(-1, named=True)
    prev = df.row(-2, named=True) if df.height >= 2 else last
    seeder.upsert_quote(
        ticker,
        price=last["close"],
        prev_close=prev["close"],
        day_open=last["open"],
        day_high=last["high"],
        day_low=last["low"],
        volume=last["volume"],
        source="stooq/yfinance-eod",
        is_stale=1,
    )


# -- backfill -------------------------------------------------------------------
def backfill_one(ticker: str, years: int = 5, settings: Settings | None = None) -> dict:
    t = norm_ticker(ticker)
    try:
        df = fetch_daily_yf(t, years=years)
    except Exception as e:  # noqa: BLE001
        logger.warning("backfill {} failed: {}", t, e)
        return {"ticker": t, "ok": False, "error": str(e)[:200]}
    rows = write_daily(t, df, settings)
    _update_latest_from_history(t, df, settings)
    first = df.row(0, named=True)["date"] if rows else None
    last = df.row(-1, named=True)["date"] if rows else None
    return {"ticker": t, "ok": True, "rows": rows, "from": first, "to": last}


def update_recent(ticker: str, settings: Settings | None = None) -> dict:
    """Pull the last ~2 months of daily bars and merge into existing Parquet (upsert by date).
    Cheap nightly refresh vs a full 5y re-pull."""
    t = norm_ticker(ticker)
    p = daily_path(t, settings)
    try:
        recent = fetch_daily_yf(t, years=1)
    except Exception as e:  # noqa: BLE001
        return {"ticker": t, "ok": False, "error": str(e)[:200]}
    recent = recent.tail(60)
    if p.exists():
        existing = pl.read_parquet(p)
        merged = (
            pl.concat([existing, recent], how="diagonal_relaxed")
            .unique(subset=["date"], keep="last")
            .sort("date")
        )
    else:
        merged = recent
    rows = write_daily(t, merged, settings)
    _update_latest_from_history(t, merged, settings)
    return {"ticker": t, "ok": True, "rows": rows}


def refresh_history_all(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    tickers = s.config.watchlist.all() + s.config.benchmarks + s.config.sector_etfs
    seen, ok, fail = set(), 0, 0
    for t in tickers:
        tt = norm_ticker(t)
        if tt in seen:
            continue
        seen.add(tt)
        r = update_recent(tt, s)
        ok += 1 if r["ok"] else 0
        fail += 0 if r["ok"] else 1
    return {"refreshed": ok, "failed": fail}


def backfill_all(tickers: list[str] | None = None, settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    if not tickers:
        # everything except pure crypto (crypto daily also works via yfinance BTC-USD form)
        tickers = s.config.watchlist.all() + s.config.benchmarks + s.config.sector_etfs
    seen, results = set(), []
    for t in tickers:
        tt = norm_ticker(t)
        if tt in seen:
            continue
        seen.add(tt)
        results.append(backfill_one(tt, settings=s))
    ok = [r for r in results if r["ok"]]
    return {
        "requested": len(seen),
        "ok": len(ok),
        "failed": len(results) - len(ok),
        "total_rows": sum(r.get("rows", 0) for r in ok),
        "results": results,
    }
