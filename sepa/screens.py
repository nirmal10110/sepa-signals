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


def is_merger_arb(df: pd.DataFrame) -> tuple[bool, float]:
    """Detect acquisition price-pinning. While a deal is pending, the target's
    price barely moves day to day (it's anchored to the deal price, not making
    a genuine breakout) — e.g. OGN pinned near $14 by the Sun Pharma deal.

    Uses the coefficient of variation (stdev/mean) of the last 20 closes.
    Returns (flagged, cv).
    """
    closes = df["close"].tail(20)
    if len(closes) < 20:
        return False, 0.0
    mean = float(closes.mean())
    if mean <= 0:
        return False, 0.0
    cv = float(closes.std()) / mean
    return cv < C.MERGER_ARB_CV_THRESHOLD, cv


def fundamental_screen(f: dict):
    """Full SEPA fundamental check. Returns (passes, score, note).

    Hard gates (pre-conditions, not scored — fail immediately):
    0a. Trailing-twelve-month net income positive (sum of last 4 quarters' EPS)
    0b. Latest-quarter EPS positive
    0c. ROE non-negative

    Scored checks (in order of Minervini's priority), all trailing GAAP only —
    no forward estimates or non-GAAP adjustments:
    1. EPS sequential acceleration (direction)
    2. EPS YoY growth >= FUND_EPS_GROWTH_MIN (last Q vs same Q last year, when 5+ quarters available)
    3. Sales sequential acceleration
    4. Sales growth >= FUND_SALES_GROWTH_MIN (TTM vs prior TTM, when 8+ quarters available)
    5. Operating margin >= floor (FUND_OP_MARGIN_MIN)
    6. Expanding margins (current > 4 quarters ago, when available)
    7. ROE >= FUND_ROE_MIN

    Pass = score >= FUND_MIN_SCORE. YoY/TTM checks are skipped (not penalised) when
    fewer than 5 quarters of data are available — common early in a live run.
    """
    eps     = f.get("eps", [])
    sales   = f.get("sales", [])
    margins = f.get("op_margins", [])
    op_margin = f.get("op_margin", 0)
    roe     = f.get("roe", 0)

    # Hard gate: trailing-twelve-month net income must be positive. A single
    # profitable quarter can mask an otherwise loss-making trailing year —
    # this is a pre-condition, not a scored check, and runs before the
    # latest-quarter check below.
    if C.FUND_REQUIRE_POSITIVE_TTM_EPS and len(eps) >= 4 and sum(eps[-4:]) < 0:
        return False, 0, "negative TTM net income"

    # Hard gate: company must be profitable in the latest reported quarter.
    if not eps or eps[-1] <= 0:
        return False, 0, "unprofitable"

    # Hard gate: ROE must be non-negative. A negative return on equity
    # disqualifies regardless of how the other checks score.
    if roe < 0:
        return False, 0, "negative ROE"

    score = 0
    tags  = []

    # 1. Sequential EPS acceleration (last 3 quarters trending up)
    if len(eps) >= 3 and eps[-1] > eps[-2] > eps[-3]:
        score += 1; tags.append("EPS↑")

    # 2. EPS YoY growth >= threshold — trailing GAAP only: last reported
    #    quarter vs the same quarter one year ago, no forward estimates.
    if len(eps) >= 5 and eps[-5] > 0:
        eps_yoy = eps[-1] / eps[-5] - 1
        if eps_yoy >= C.FUND_EPS_GROWTH_MIN:
            score += 1; tags.append(f"EPS+{eps_yoy*100:.0f}%yr")

    # 3. Sales sequential acceleration
    if len(sales) >= 3 and sales[-1] > sales[-2] > sales[-3]:
        score += 1; tags.append("Sales↑")

    # 4. Sales growth >= threshold — trailing GAAP only: trailing-twelve-month
    #    (last 4 quarters) vs the prior trailing-twelve-month (quarters -8..-4).
    #    A single noisy quarter-over-quarter comp can pass on a soft compare;
    #    the full TTM window is what catches seasonal/lumpy revenue.
    if len(sales) >= 8:
        ttm, prior_ttm = sum(sales[-4:]), sum(sales[-8:-4])
        if prior_ttm > 0:
            sales_yoy = ttm / prior_ttm - 1
            if sales_yoy >= C.FUND_SALES_GROWTH_MIN:
                score += 1; tags.append(f"Sales+{sales_yoy*100:.0f}%ttm")

    # 5. Operating margin floor
    if op_margin >= C.FUND_OP_MARGIN_MIN:
        score += 1; tags.append(f"Mrgn>{C.FUND_OP_MARGIN_MIN*100:.0f}%")

    # 6. Expanding margins (current quarter vs 4 quarters ago)
    if len(margins) >= 4 and margins[-1] > margins[-4]:
        score += 1; tags.append("Mrgn↑")

    # 7. Return on Equity >= threshold
    if roe >= C.FUND_ROE_MIN:
        score += 1; tags.append(f"ROE>{C.FUND_ROE_MIN*100:.0f}%")

    # 8. Revenue decline penalty — 2+ consecutive QoQ declines signal deterioration.
    # A company can pass the YoY gate on a soft comp while actively shrinking; this
    # catches it. Deduct one point so borderline names don't squeak through.
    if len(sales) >= 3 and sales[-1] < sales[-2] < sales[-3]:
        score -= 1; tags.append("Rev↓")

    note = "+".join(tags) if tags else "weak"
    return score >= C.FUND_MIN_SCORE, score, note


def _rising_tail(seq: list, min_increases: int = 2) -> bool:
    """True if the last `min_increases` consecutive steps in seq are increases."""
    if len(seq) < min_increases + 1:
        return False
    tail = seq[-(min_increases + 1):]
    return all(b > a for a, b in zip(tail, tail[1:]))


def fundamental_trend(f: dict) -> dict:
    """Quarterly EPS/revenue trajectory for a Momentum-tier stock (failed the
    SEPA fundamental screen but may be a turnaround story worth watching).

    Looks at the trailing quarters already stored in the `fundamentals` table
    (same shape as fundamental_screen's input) and flags whether EPS or
    revenue growth is accelerating into the most recent quarter.
    """
    eps = f.get("eps", [])
    sales = f.get("sales", [])

    empty = {
        "eps_trend": [], "rev_growth_trend": [],
        "eps_accelerating": False, "rev_accelerating": False,
        "improving": False, "trend_label": "",
    }
    if len(eps) < 3:
        return empty

    eps_trend = eps[-4:]
    eps_accelerating = _rising_tail(eps_trend)

    rev_growth_trend = []
    if len(sales) >= 8:
        tail = sales[-8:]
        rev_growth_trend = [
            (tail[i + 4] / tail[i] - 1) if tail[i] else 0.0 for i in range(4)
        ]
    rev_accelerating = _rising_tail(rev_growth_trend)

    if eps_accelerating:
        trend_label = "EPS " + "→".join(f"${v:.2f}" for v in eps_trend[-3:]) + " (↑)"
    elif rev_accelerating:
        trend_label = ("Rev " + "→".join(f"{v*100:.0f}%" for v in rev_growth_trend[-3:])
                       + " YoY (↑)")
    else:
        trend_label = ""

    return {
        "eps_trend": eps_trend,
        "rev_growth_trend": rev_growth_trend,
        "eps_accelerating": eps_accelerating,
        "rev_accelerating": rev_accelerating,
        "improving": eps_accelerating or rev_accelerating,
        "trend_label": trend_label,
    }
