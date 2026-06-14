"""The three-axis primitives: technical (trend template + stage), relative
strength, and fundamentals."""
import numpy as np
import pandas as pd
from . import config as C
from .indicators import hi_lo_52w, sma_rising


def trend_template(df: pd.DataFrame, rs: float | None):
    """Minervini's 8 criteria. Returns (score 0-8, dict of bools)."""
    c = df["close"].iloc[-1]
    s50, s150, s200 = df["sma50"].iloc[-1], df["sma150"].iloc[-1], df["sma200"].iloc[-1]
    hi, lo = hi_lo_52w(df)
    checks = {
        "price>150&200": c > s150 and c > s200,
        "150>200": s150 > s200,
        "200_rising": sma_rising(df, "sma200", C.SMA200_RISING_LOOKBACK),
        "50>150>200": s50 > s150 > s200,
        "price>50": c > s50,
        "30%_above_low": c >= lo * (1 + C.PCT_ABOVE_52W_LOW),
        "within_25%_high": c >= hi * (1 - C.PCT_BELOW_52W_HIGH),
        "RS>=70": (rs is not None and rs >= C.RS_MIN),
    }
    return sum(checks.values()), checks


def classify_stage(df: pd.DataFrame, tt_score: int):
    """Rule-based Stage 1-4 with a confidence 0-1."""
    c = df["close"].iloc[-1]
    s50, s150, s200 = df["sma50"].iloc[-1], df["sma150"].iloc[-1], df["sma200"].iloc[-1]
    rising200 = sma_rising(df, "sma200", C.SMA200_RISING_LOOKBACK)
    falling200 = not rising200 and df["sma200"].iloc[-1] < df["sma200"].iloc[-22]
    slope200 = abs(df["sma200"].iloc[-1] / df["sma200"].iloc[-22] - 1)

    # Stage 2: durable advancing structure (price can dip below the fast 50
    # during a base and still be Stage 2 — gate on the slower MAs).
    if rising200 and c > s150 and c > s200 and s150 > s200:
        return 2, min(1.0, max(tt_score, 6) / 8)
    if tt_score >= 6 and c > s50 and rising200:
        return 2, min(1.0, tt_score / 8)
    if c < s50 and s50 < s200 and falling200:
        return 4, 0.8
    if slope200 < 0.01 and abs(c / s200 - 1) < 0.10:
        return 1, 0.6
    if rising200 and c < s50:               # was advancing, now churning under 50
        return 3, 0.55
    return 4 if c < s200 else 1, 0.4


def weighted_rs_return(df: pd.DataFrame) -> float | None:
    """IBD-style: 40% most recent quarter + 20% each prior three."""
    cl = df["close"]
    if len(cl) < 252:
        return None
    def q(a, b):
        return cl.iloc[-a] / cl.iloc[-b] - 1
    return 0.4 * q(1, 63) + 0.2 * q(63, 126) + 0.2 * q(126, 189) + 0.2 * q(189, 252)


def rank_rs(returns: dict[str, float]) -> dict[str, int]:
    """Percentile-rank raw RS returns across the universe -> 1..99."""
    valid = {t: r for t, r in returns.items() if r is not None}
    if not valid:
        return {}
    s = pd.Series(valid)
    pct = s.rank(pct=True) * 98 + 1
    return {t: int(round(v)) for t, v in pct.items()}


def fundamental_screen(f: dict):
    """Returns (passes, score 0-4, note). Looks for acceleration + quality."""
    eps, sales = f.get("eps", []), f.get("sales", [])
    eps_accel = len(eps) >= 3 and eps[-1] > eps[-2] > eps[-3]
    sales_accel = len(sales) >= 3 and sales[-1] > sales[-2] > sales[-3]
    margin_ok = f.get("op_margin", 0) >= 0.10
    roe_ok = f.get("roe", 0) >= 0.17
    score = sum([eps_accel, sales_accel, margin_ok, roe_ok])
    tags = []
    if eps_accel: tags.append("EPS↑")
    if sales_accel: tags.append("Sales↑")
    if roe_ok: tags.append("ROE>17")
    note = "+".join(tags) if tags else "weak"
    return score >= 3, score, note
