"""Hedge Ideas module.

Inputs: portfolio positions + betas (2y regression vs SPY), regime score, realized-vol
snapshot, correlation. Output per idea: structure, beta-adjusted notional coverage,
indicative cost (% of portfolio/quarter), trigger, exit/roll, and what it does NOT protect.
Always framed as structured options for Mason's decision — never "do this".
"""

from __future__ import annotations

import numpy as np

from ..config import Settings, get_settings, load_portfolio
from ..connectors.history import read_daily
from ..util import norm_ticker


def _returns(ticker: str, s: Settings, n: int = 504) -> np.ndarray | None:
    df = read_daily(ticker, settings=s)
    if df.height < 60:
        return None
    close = df.get_column("close").to_numpy()[-n:]
    return np.diff(np.log(close))


def beta_vs_spy(ticker: str, s: Settings) -> float | None:
    r = _returns(ticker, s)
    spy = _returns("SPY", s)
    if r is None or spy is None:
        return None
    m = min(len(r), len(spy))
    r, spy = r[-m:], spy[-m:]
    var = np.var(spy)
    if var == 0:
        return None
    return round(float(np.cov(r, spy)[0, 1] / var), 2)


def portfolio_snapshot(s: Settings) -> dict:
    from ..db import get_db

    db = get_db(s)
    port = load_portfolio(s)
    equity_val = 0.0
    crypto_val = 0.0
    beta_dollars = 0.0
    positions = []
    for acct in port.get("accounts", []):
        for pos in acct.get("positions", []):
            ticker = norm_ticker(pos.get("ticker", ""))
            qty = pos.get("qty") or 0
            q = db.query_one(
                "SELECT q.price FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id WHERE i.ticker=?",
                (ticker,),
            )
            price = q["price"] if q else None
            if not price:
                continue
            value = qty * price
            if ticker.endswith("-USD"):
                crypto_val += value
            else:
                beta = beta_vs_spy(ticker, s) or 1.0
                beta_dollars += beta * value
                equity_val += value
            positions.append(
                {
                    "ticker": ticker,
                    "value": round(value, 2),
                    "beta": beta_vs_spy(ticker, s) if not ticker.endswith("-USD") else None,
                }
            )
    cash = port.get("cash", {})
    total = equity_val + crypto_val + sum(v for v in cash.values() if isinstance(v, int | float))
    port_beta = round(beta_dollars / equity_val, 2) if equity_val else 0.0
    return {
        "positions": positions,
        "equity_value": round(equity_val, 2),
        "crypto_value": round(crypto_val, 2),
        "total_value": round(total, 2),
        "portfolio_beta": port_beta,
        "beta_adjusted_exposure": round(beta_dollars, 2),
    }


def hedge_ideas(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db

    db = get_db(s)
    snap = portfolio_snapshot(s)
    regime = db.get_setting("regime.latest", {}) or {}
    regime_score = regime.get("score", 50)

    # SPY level + realized vol for indicative sizing
    spy = db.query_one(
        "SELECT q.price FROM quotes_latest q JOIN instruments i ON i.id=q.instrument_id WHERE i.ticker='SPY'"
    )
    spy_px = spy["price"] if spy else None
    rvol = None
    row = db.query_one(
        "SELECT value FROM signals s JOIN instruments i ON i.id=s.instrument_id "
        "WHERE i.ticker='SPY' AND s.kind='rvol20' ORDER BY bar_date DESC LIMIT 1"
    )
    if row:
        rvol = row["value"]

    beta_exp = snap["beta_adjusted_exposure"]
    ideas = []

    if beta_exp > 0 and spy_px:
        # 1) Index put — indicative quarterly cost ≈ 0.4 * annualized vol / 2 (rough ATM 3m put)
        vol = rvol or 0.18
        put_cost_pct = round(vol / np.sqrt(4) * 0.4 * 100, 1)  # ~ATM 3M put premium %
        strike = round(spy_px * 0.95, 0)
        ideas.append(
            {
                "structure": "SPY 3-month ~5% OTM put (or put spread to cheapen)",
                "coverage": f"beta-adjusted notional ≈ ${beta_exp:,.0f} ({snap['portfolio_beta']}β)",
                "indicative_cost": f"~{put_cost_pct}% of equity / quarter (ATM ref; OTM cheaper)",
                "trigger": f"activate if regime < 35 or SPY closes below {strike:.0f}",
                "exit_roll": "roll at 21 DTE or take profit at 2x; cut if regime recovers > 55",
                "does_not_protect": "idiosyncratic single-name gaps; overnight crypto",
            }
        )
        # 2) Inverse ETF sizing (no options)
        ideas.append(
            {
                "structure": "SH (−1x S&P) sleeve",
                "coverage": f"size ≈ ${beta_exp * 0.5:,.0f} to offset ~50% of beta",
                "indicative_cost": "carry/decay only; no premium outlay",
                "trigger": "activate on regime flip to Risk-Off",
                "exit_roll": "remove when regime ≥ 55",
                "does_not_protect": "convexity in a fast crash (linear, not optioned)",
            }
        )
        # 3) Cash raise
        ideas.append(
            {
                "structure": f"Raise cash by trimming highest-beta names ({_highest_beta(snap)})",
                "coverage": "reduces gross + beta directly",
                "indicative_cost": "opportunity cost if rally continues",
                "trigger": "regime < 40 and breadth deteriorating",
                "exit_roll": "redeploy on regime ≥ 60 or a washed-out breadth reading",
                "does_not_protect": "nothing to hedge once flat — but caps drawdown",
            }
        )

    if snap["crypto_value"] > 0:
        ideas.append(
            {
                "structure": "BTC trim / stablecoin rotation",
                "coverage": f"crypto exposure ≈ ${snap['crypto_value']:,.0f}",
                "indicative_cost": "none (spot)",
                "trigger": "BTC 24h < −8% or weekend liquidity thinning",
                "exit_roll": "re-add on structure reclaim; scale, don't all-or-nothing",
                "does_not_protect": "equity beta",
            }
        )

    return {
        "as_of": regime.get("at"),
        "regime_score": regime_score,
        "snapshot": snap,
        "spy_price": spy_px,
        "realized_vol": rvol,
        "ideas": ideas,
        "note": "Structured options for Mason's decision — never an instruction.",
    }


def _highest_beta(snap: dict) -> str:
    eq = [p for p in snap["positions"] if p.get("beta") is not None]
    eq.sort(key=lambda p: -(p["beta"] or 0))
    return ", ".join(p["ticker"] for p in eq[:2]) or "highest-beta holdings"
