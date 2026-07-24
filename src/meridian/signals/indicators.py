"""Technical indicators, implemented in numpy — no TA-lib dependency.

All functions take/return numpy arrays aligned to the input closes (NaN-padded at the
front where a window isn't yet full). Wilder smoothing is used for RSI and ATR to match
the conventions charting packages use. ``compute_indicators`` rolls a daily-bar frame up
into the latest per-instrument snapshot the signal engine stores.
"""

from __future__ import annotations

import numpy as np

_ANNUALIZATION = np.sqrt(252.0)


def _as_array(x) -> np.ndarray:
    return np.asarray(x, dtype=np.float64)


def sma(values, n: int) -> np.ndarray:
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    if len(v) < n:
        return out
    c = np.cumsum(np.insert(v, 0, 0.0))
    out[n - 1 :] = (c[n:] - c[:-n]) / n
    return out


def ema(values, n: int) -> np.ndarray:
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    if len(v) == 0:
        return out
    k = 2.0 / (n + 1.0)
    # seed with SMA of first n for stability
    if len(v) < n:
        seed_idx = 0
        out[0] = v[0]
    else:
        seed_idx = n - 1
        out[seed_idx] = v[:n].mean()
    for i in range(seed_idx + 1, len(v)):
        out[i] = v[i] * k + out[i - 1] * (1 - k)
    return out


def _wilder(values, n: int) -> np.ndarray:
    """Wilder's smoothing (RMA): first point = SMA(n), then rma = (prev*(n-1)+x)/n."""
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    if len(v) < n:
        return out
    out[n - 1] = v[:n].mean()
    for i in range(n, len(v)):
        out[i] = (out[i - 1] * (n - 1) + v[i]) / n
    return out


def rsi(close, n: int = 14) -> np.ndarray:
    c = _as_array(close)
    out = np.full(c.shape, np.nan)
    if len(c) <= n:
        return out
    delta = np.diff(c)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = _wilder(gain, n)
    avg_loss = _wilder(loss, n)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = avg_gain / avg_loss
        rsi_vals = 100.0 - 100.0 / (1.0 + rs)
    rsi_vals = np.where(avg_loss == 0, 100.0, rsi_vals)  # all-gains → 100
    out[1:] = rsi_vals
    return out


def macd(close, fast: int = 12, slow: int = 26, signal: int = 9):
    c = _as_array(close)
    macd_line = ema(c, fast) - ema(c, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def true_range(high, low, close) -> np.ndarray:
    h, low_, c = _as_array(high), _as_array(low), _as_array(close)
    prev_close = np.roll(c, 1)
    prev_close[0] = c[0]
    tr = np.maximum.reduce([h - low_, np.abs(h - prev_close), np.abs(low_ - prev_close)])
    return tr


def atr(high, low, close, n: int = 14) -> np.ndarray:
    return _wilder(true_range(high, low, close), n)


def bollinger(close, n: int = 20, k: float = 2.0):
    c = _as_array(close)
    mid = sma(c, n)
    std = _rolling_std(c, n)
    upper = mid + k * std
    lower = mid - k * std
    with np.errstate(divide="ignore", invalid="ignore"):
        bandwidth = (upper - lower) / mid
    return mid, upper, lower, bandwidth


def _rolling_std(values, n: int) -> np.ndarray:
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    if len(v) < n:
        return out
    for i in range(n - 1, len(v)):
        out[i] = v[i - n + 1 : i + 1].std(ddof=0)
    return out


def donchian(high, low, n: int):
    h, low_ = _as_array(high), _as_array(low)
    upper = np.full(h.shape, np.nan)
    lower = np.full(low_.shape, np.nan)
    for i in range(n - 1, len(h)):
        upper[i] = h[i - n + 1 : i + 1].max()
        lower[i] = low_[i - n + 1 : i + 1].min()
    return upper, lower


def realized_vol(close, n: int) -> np.ndarray:
    c = _as_array(close)
    out = np.full(c.shape, np.nan)
    if len(c) <= n:
        return out
    logret = np.diff(np.log(c))
    for i in range(n, len(c)):
        out[i] = logret[i - n : i].std(ddof=0) * _ANNUALIZATION
    return out


def volume_zscore(volume, n: int = 20) -> np.ndarray:
    v = _as_array(volume)
    out = np.full(v.shape, np.nan)
    for i in range(n, len(v)):
        window = v[i - n : i]
        mu, sd = window.mean(), window.std(ddof=0)
        out[i] = (v[i] - mu) / sd if sd > 0 else 0.0
    return out


def nr7(high, low) -> np.ndarray:
    """Narrow-range-7: today's range is the smallest of the last 7."""
    h, low_ = _as_array(high), _as_array(low)
    rng = h - low_
    out = np.full(h.shape, False)
    for i in range(6, len(rng)):
        out[i] = rng[i] == rng[i - 6 : i + 1].min()
    return out


def rolling_percentile(values, n: int) -> np.ndarray:
    """Percentile rank (0–100) of the latest value within the trailing window."""
    v = _as_array(values)
    out = np.full(v.shape, np.nan)
    for i in range(n - 1, len(v)):
        window = v[i - n + 1 : i + 1]
        out[i] = (window <= v[i]).mean() * 100.0
    return out


def compute_indicators(df, spy_closes: np.ndarray | None = None) -> dict:
    """Compute the latest indicator snapshot for one instrument's daily-bar frame.

    ``df`` must have columns date, open, high, low, close, volume (polars or dict-of-lists).
    ``spy_closes`` (optional) enables relative-strength-vs-SPY.
    """
    close = _as_array(_get(df, "close"))
    high = _as_array(_get(df, "high"))
    low = _as_array(_get(df, "low"))
    volume = _as_array(_get(df, "volume"))
    open_ = _as_array(_get(df, "open"))
    n = len(close)
    if n < 30:
        return {}

    out: dict[str, float] = {}

    def last(a):
        return float(a[-1]) if len(a) and not np.isnan(a[-1]) else None

    for p in (20, 50, 100, 200):
        out[f"sma{p}"] = last(sma(close, p))
        out[f"ema{p}"] = last(ema(close, p))
    out["rsi14"] = last(rsi(close, 14))
    macd_line, signal_line, hist = macd(close)
    out["macd"] = last(macd_line)
    out["macd_signal"] = last(signal_line)
    out["macd_hist"] = last(hist)
    atr14 = atr(high, low, close, 14)
    out["atr14"] = last(atr14)
    out["atr_pct"] = (out["atr14"] / close[-1] * 100.0) if out.get("atr14") and close[-1] else None
    mid, upper, lower, bw = bollinger(close, 20, 2)
    out["bb_upper"] = last(upper)
    out["bb_lower"] = last(lower)
    out["bb_bandwidth"] = last(bw)
    bw_pct = rolling_percentile(bw, min(120, n - 20)) if n > 40 else np.full(n, np.nan)
    out["bb_bandwidth_pct"] = last(bw_pct)
    du, dl = donchian(high, low, 20)
    out["donchian20_upper"], out["donchian20_lower"] = last(du), last(dl)
    du55, dl55 = donchian(high, low, 55)
    out["donchian55_upper"], out["donchian55_lower"] = last(du55), last(dl55)
    out["rvol20"] = last(realized_vol(close, 20))
    out["rvol60"] = last(realized_vol(close, 60))
    out["volume_z"] = last(volume_zscore(volume, 20))
    out["dollar_volume"] = float(close[-1] * volume[-1]) if volume[-1] else None

    # 52-week high/low distance
    win = min(252, n)
    hi52 = float(np.nanmax(high[-win:]))
    lo52 = float(np.nanmin(low[-win:]))
    out["high_52w"] = hi52
    out["low_52w"] = lo52
    out["pct_from_52w_high"] = (close[-1] / hi52 - 1.0) * 100.0 if hi52 else None
    out["pct_from_52w_low"] = (close[-1] / lo52 - 1.0) * 100.0 if lo52 else None

    # gap % vs prior close
    if n >= 2 and close[-2]:
        out["gap_pct"] = (open_[-1] / close[-2] - 1.0) * 100.0
        out["day_change_pct"] = (close[-1] / close[-2] - 1.0) * 100.0

    # drawdown from all-time high (in the loaded window)
    ath = float(np.nanmax(close))
    out["drawdown_pct"] = (close[-1] / ath - 1.0) * 100.0 if ath else None

    # golden/death cross event (today's 50/200 cross)
    s50, s200 = sma(close, 50), sma(close, 200)
    out["cross_50_200"] = _cross_event(s50, s200)

    # range compression flag: NR7 today AND BB bandwidth percentile < 10
    nr = nr7(high, low)
    out["range_compression"] = bool(
        (len(nr) and nr[-1])
        and (out.get("bb_bandwidth_pct") is not None and out["bb_bandwidth_pct"] < 10)
    )

    # relative strength vs SPY (20d/60d ratio slope)
    if spy_closes is not None and len(spy_closes) >= 61 and n >= 61:
        m = min(len(spy_closes), n)
        ratio = close[-m:] / spy_closes[-m:]
        out["rs_spy_20d"] = float(ratio[-1] / ratio[-21] - 1.0) * 100.0 if m >= 21 else None
        out["rs_spy_60d"] = float(ratio[-1] / ratio[-61] - 1.0) * 100.0 if m >= 61 else None

    # cast numpy scalars to native python types for clean JSON/SQLite storage
    clean: dict = {}
    for k, v in out.items():
        if v is None:
            continue
        clean[k] = v if isinstance(v, bool | int) else float(v)
    return clean


def _cross_event(fast: np.ndarray, slow: np.ndarray) -> int:
    """+1 golden cross today, -1 death cross today, 0 otherwise."""
    if (
        len(fast) < 2
        or np.isnan(fast[-1])
        or np.isnan(slow[-1])
        or np.isnan(fast[-2])
        or np.isnan(slow[-2])
    ):
        return 0
    if fast[-2] <= slow[-2] and fast[-1] > slow[-1]:
        return 1
    if fast[-2] >= slow[-2] and fast[-1] < slow[-1]:
        return -1
    return 0


def _get(df, col):
    if hasattr(df, "get_column"):  # polars
        return df.get_column(col).to_numpy()
    if hasattr(df, "__getitem__"):
        return df[col]
    raise TypeError("unsupported frame type")
