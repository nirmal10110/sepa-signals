"""Price/volume indicators and the swing/contraction primitives the pattern
detectors build on."""
import numpy as np
import pandas as pd


def add_mas(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for w in (10, 21, 50, 150, 200):
        df[f"sma{w}"] = df["close"].rolling(w).mean()
    df["vol50"] = df["volume"].rolling(50).mean()
    return df


def hi_lo_52w(df: pd.DataFrame):
    win = df["close"].iloc[-252:]
    return float(win.max()), float(win.min())


def sma_rising(df: pd.DataFrame, col: str, lookback: int) -> bool:
    s = df[col].dropna()
    if len(s) <= lookback:
        return False
    return bool(s.iloc[-1] > s.iloc[-1 - lookback])


def swing_points(close: np.ndarray, k: int = 3):
    """Return (highs, lows) as lists of (index, price). A swing high is a bar
    higher than k neighbours each side; symmetric for lows."""
    highs, lows = [], []
    n = len(close)
    for i in range(k, n - k):
        window = close[i - k:i + k + 1]
        if close[i] == window.max() and close[i] > close[i - 1]:
            highs.append((i, close[i]))
        if close[i] == window.min() and close[i] < close[i - 1]:
            lows.append((i, close[i]))
    return highs, lows


def ret_1y(df: pd.DataFrame) -> float | None:
    """Total price return over the past 252 trading days (≈ 1 year).
    Returns None when history is shorter than 252 bars."""
    if len(df) < 252:
        return None
    return float(df["close"].iloc[-1] / df["close"].iloc[-252] - 1)


def ext_from_200(df: pd.DataFrame) -> float:
    """How far above (positive) or below (negative) the 200 SMA the current
    price sits, as a fraction. Requires add_mas() to have been called first."""
    c = df["close"].iloc[-1]
    s200 = df["sma200"].iloc[-1]
    if pd.isna(s200) or s200 == 0:
        return 0.0
    return float((c - s200) / s200)


def up_day_vol_ratio(df: pd.DataFrame, lookback: int = 60) -> float:
    """Institutional sponsorship proxy: avg volume on up-days / avg volume on down-days.
    Minervini looks for > 1.0 (more volume on advances than declines = accumulation).
    Uses close vs open to classify each day."""
    recent = df.tail(lookback)
    up_vol = recent.loc[recent["close"] > recent["open"], "volume"].mean()
    dn_vol = recent.loc[recent["close"] <= recent["open"], "volume"].mean()
    if dn_vol == 0 or np.isnan(dn_vol):
        return 1.0
    return float(up_vol / dn_vol)


def contractions(close: np.ndarray, k: int = 3):
    """Sequence of peak->trough drawdown depths (fractions) across the base,
    oldest to newest. This is the raw material for the VCP footprint."""
    highs, lows = swing_points(close, k)
    pivots = sorted(highs + [(i, p, "L") for i, p in lows] +
                    [(i, p, "H") for i, p in highs], key=lambda x: x[0])
    # walk alternating H->L legs
    depths = []
    last_high = None
    for i, p, *_ in [(i, p, "H") for i, p in highs] + [(i, p, "L") for i, p in lows]:
        pass
    # simpler: pair each swing high with the next lower swing low
    hi = sorted(highs); lo = sorted(lows)
    for hidx, hp in hi:
        following = [(lidx, lp) for lidx, lp in lo if lidx > hidx]
        if not following:
            continue
        lidx, lp = min(following, key=lambda x: x[0])
        if hp > 0:
            depths.append((hidx, (hp - lp) / hp))
    # keep chronological, dedupe overlapping
    depths.sort(key=lambda x: x[0])
    return [d for _, d in depths]
