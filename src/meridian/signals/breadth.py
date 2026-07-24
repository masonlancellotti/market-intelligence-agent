"""Market internals & breadth.

Computed across active+monitor+sector_etfs: % above 50/200DMA, advancers/decliners,
new 20d highs−lows, sector RS ranking (1M/3M), a rolling 60d correlation matrix with a
correlation-shift detector (pairwise Δcorr > 0.4 over 10 sessions), and the RSP/SPY
equal-vs-cap-weight breadth proxy.
"""

from __future__ import annotations

import numpy as np

from ..config import Settings, get_settings
from ..connectors.history import read_daily
from ..util import norm_ticker

_CORR_WINDOW = 60
_CORR_SHIFT_LOOKBACK = 10
_CORR_SHIFT_THRESHOLD = 0.4


def _universe(s: Settings) -> list[str]:
    cfg = s.config
    tick = cfg.watchlist.active + cfg.watchlist.monitor + cfg.sector_etfs + cfg.benchmarks
    return [norm_ticker(t) for t in dict.fromkeys(tick) if not t.endswith("-USD")]


def _aligned_closes(
    tickers: list[str], settings: Settings, lookback: int = 130
) -> dict[str, np.ndarray]:
    """Return {ticker: close array} for tickers with enough history, aligned by date."""
    frames = {}
    for t in tickers:
        df = read_daily(t, settings=settings)
        if df.height >= 60:
            frames[t] = df.tail(lookback)
    if not frames:
        return {}
    # align on common dates
    common = None
    for df in frames.values():
        dates = set(df.get_column("date").to_list())
        common = dates if common is None else (common & dates)
    common = sorted(common or [])
    if len(common) < 60:
        return {}
    out = {}
    for t, df in frames.items():
        d = df.filter(df.get_column("date").is_in(common)).sort("date")
        out[t] = d.get_column("close").to_numpy()
    return out


def compute_breadth(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from .indicators import sma

    universe = _universe(s)
    above50 = above200 = total = 0
    adv = dec = 0
    new_high = new_low = 0
    for t in universe:
        df = read_daily(t, settings=s)
        if df.height < 50:
            continue
        close = df.get_column("close").to_numpy()
        high = df.get_column("high").to_numpy()
        low = df.get_column("low").to_numpy()
        total += 1
        s50 = sma(close, 50)[-1]
        if not np.isnan(s50) and close[-1] > s50:
            above50 += 1
        if df.height >= 200:
            s200 = sma(close, 200)[-1]
            if not np.isnan(s200) and close[-1] > s200:
                above200 += 1
        if len(close) >= 2:
            (adv, dec) = (adv + 1, dec) if close[-1] >= close[-2] else (adv, dec + 1)
        win = min(20, len(high))
        if close[-1] >= high[-win:].max() - 1e-9:
            new_high += 1
        if close[-1] <= low[-win:].min() + 1e-9:
            new_low += 1

    breadth = {
        "universe_size": total,
        "pct_above_50dma": round(above50 / total * 100, 1) if total else None,
        "pct_above_200dma": round(above200 / total * 100, 1) if total else None,
        "advancers": adv,
        "decliners": dec,
        "new_20d_highs": new_high,
        "new_20d_lows": new_low,
        "net_new_highs": new_high - new_low,
        "sector_rs": _sector_rs(s),
        "rsp_spy_proxy": _rsp_spy(s),
        "correlation_shifts": _correlation_shifts(universe, s),
    }
    s_db = _db(s)
    s_db.set_setting("breadth.latest", breadth)
    return breadth


def _sector_rs(s: Settings) -> list[dict]:
    out = []
    for t in [norm_ticker(x) for x in s.config.sector_etfs]:
        df = read_daily(t, settings=s)
        if df.height < 64:
            continue
        close = df.get_column("close").to_numpy()
        r1m = (close[-1] / close[-22] - 1.0) * 100.0 if len(close) >= 22 else None
        r3m = (close[-1] / close[-64] - 1.0) * 100.0 if len(close) >= 64 else None
        out.append({"ticker": t, "ret_1m": _r(r1m), "ret_3m": _r(r3m)})
    out.sort(key=lambda x: (x["ret_1m"] is None, -(x["ret_1m"] or -999)))
    return out


def _rsp_spy(s: Settings) -> dict | None:
    rsp = read_daily("RSP", settings=s)
    spy = read_daily("SPY", settings=s)
    if rsp.height < 65 or spy.height < 65:
        return None
    rc = rsp.get_column("close").to_numpy()
    sc = spy.get_column("close").to_numpy()
    m = min(len(rc), len(sc))
    ratio = rc[-m:] / sc[-m:]
    return {
        "ratio": round(float(ratio[-1]), 4),
        "trend_20d": _r((ratio[-1] / ratio[-21] - 1.0) * 100.0) if m >= 21 else None,
    }


def _correlation_shifts(universe: list[str], s: Settings) -> list[dict]:
    closes = _aligned_closes(universe, s, lookback=_CORR_WINDOW + _CORR_SHIFT_LOOKBACK + 5)
    tickers = [t for t in universe if t in closes]
    if len(tickers) < 4:
        return []
    # returns matrix
    min_len = min(len(closes[t]) for t in tickers)
    if min_len < _CORR_WINDOW + _CORR_SHIFT_LOOKBACK + 1:
        return []
    rets = {t: np.diff(np.log(closes[t][-min_len:])) for t in tickers}
    now = _corr_matrix(rets, tickers, offset=0)
    past = _corr_matrix(rets, tickers, offset=_CORR_SHIFT_LOOKBACK)
    shifts = []
    for i in range(len(tickers)):
        for j in range(i + 1, len(tickers)):
            d = now[i, j] - past[i, j]
            if abs(d) > _CORR_SHIFT_THRESHOLD:
                shifts.append(
                    {
                        "pair": [tickers[i], tickers[j]],
                        "corr_now": round(float(now[i, j]), 2),
                        "corr_prev": round(float(past[i, j]), 2),
                        "delta": round(float(d), 2),
                    }
                )
    shifts.sort(key=lambda x: -abs(x["delta"]))
    return shifts[:10]


def _corr_matrix(rets: dict, tickers: list[str], offset: int) -> np.ndarray:
    win = _CORR_WINDOW
    mat = np.vstack([rets[t][-(win + offset) : len(rets[t]) - offset] for t in tickers])
    return np.corrcoef(mat)


def _r(x):
    return round(float(x), 2) if x is not None else None


def _db(s):
    from ..db import get_db

    return get_db(s)
