"""Signal engine orchestration.

Nightly after daily-bar finalization: compute per-instrument indicators → market breadth
→ regime model, persisting every value to the ``signals`` table (traceable to a bar).
"""

from __future__ import annotations

import numpy as np
from loguru import logger

from ..config import Settings, get_settings
from ..connectors.history import read_daily
from ..util import utcnow_iso


def _spy_closes(s: Settings) -> np.ndarray | None:
    df = read_daily("SPY", settings=s)
    return df.get_column("close").to_numpy() if df.height else None


def recompute_indicators(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from ..db import get_db
    from .indicators import compute_indicators

    db = get_db(s)
    spy = _spy_closes(s)
    instruments = db.query("SELECT id, ticker FROM instruments ORDER BY ticker")
    n_inst = 0
    n_sig = 0
    for inst in instruments:
        df = read_daily(inst["ticker"], settings=s)
        if df.height < 30:
            continue
        snap = compute_indicators(df, spy_closes=spy)
        if not snap:
            continue
        bar_date = df.row(-1, named=True)["date"]
        now = utcnow_iso()
        rows = [
            (inst["id"], kind, float(val) if isinstance(val, bool) else val, "{}", bar_date, now)
            for kind, val in snap.items()
            if isinstance(val, int | float)
        ]
        db.executemany(
            "INSERT INTO signals(instrument_id,kind,value,params_json,bar_date,created_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(instrument_id,kind,bar_date) DO UPDATE SET "
            "value=excluded.value",
            rows,
        )
        n_inst += 1
        n_sig += len(rows)
    logger.info("indicators: {} instruments, {} signal rows", n_inst, n_sig)
    return {"instruments": n_inst, "signals": n_sig}


def recompute_all(settings: Settings | None = None) -> dict:
    s = settings or get_settings()
    from .breadth import compute_breadth
    from .regime import compute_regime

    ind = recompute_indicators(s)
    breadth = compute_breadth(s)
    regime = compute_regime(s)
    return {
        "indicators": ind,
        "breadth": {
            k: breadth.get(k) for k in ("pct_above_50dma", "net_new_highs", "universe_size")
        },
        "regime": {"score": regime.get("score"), "bucket": regime.get("bucket")},
    }
