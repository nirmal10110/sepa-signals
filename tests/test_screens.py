"""Tests for sepa/screens.py — fundamental hard gates (Bug 2) and the
merger-arb pinning detector (Bug 3)."""
import numpy as np
import pandas as pd

from sepa.screens import fundamental_screen, is_merger_arb, fundamental_trend


# ---------------------------------------------------------------------------
# Bug 2 (HIGH): strict trailing-GAAP fundamental hard gates
# ---------------------------------------------------------------------------

def test_negative_ttm_eps_fails_hard_gate():
    """4 quarters summing to -$1.50 (latest quarter positive, masking the
    trailing-year loss) must fail immediately, before any scoring."""
    f = dict(eps=[-1.0, -1.0, 0.20, 0.30], sales=[100, 105, 110, 115],
            op_margin=0.15, roe=0.20)
    passes, score, note = fundamental_screen(f)
    assert passes is False
    assert score == 0
    assert note == "negative TTM net income"


def test_negative_roe_fails_hard_gate():
    """Positive TTM EPS but ROE=-0.5 must fail immediately."""
    f = dict(eps=[0.10, 0.15, 0.20, 0.25], sales=[100, 104, 107, 110],
            op_margin=0.15, roe=-0.5)
    passes, score, note = fundamental_screen(f)
    assert passes is False
    assert score == 0
    assert note == "negative ROE"


def test_positive_ttm_eps_proceeds_to_scoring():
    """Positive TTM EPS and positive ROE clear both hard gates and proceed
    to normal scoring (matches the SyntheticProvider 'good' fixture)."""
    f = dict(eps=[0.10, 0.18, 0.31, 0.52], sales=[100, 118, 140, 171],
            op_margin=0.19, roe=0.24)
    passes, score, note = fundamental_screen(f)
    assert passes is True
    assert score >= 3
    assert note != "negative TTM net income"
    assert note != "negative ROE"


# ---------------------------------------------------------------------------
# Bug 2: trailing-GAAP TTM revenue growth (8 quarters required)
# ---------------------------------------------------------------------------

def test_sales_ttm_growth_uses_full_year_not_single_quarter():
    """A single soft year-ago quarter must not let a flat TTM pass — the TTM
    comparison (last 4 vs prior 4) is what should drive the score, not the
    single quarter-over-same-quarter-last-year compare."""
    # Prior TTM = 100+100+100+100=400, current TTM = 100+100+100+100=400 -> flat, no growth.
    f = dict(eps=[0.20, 0.20, 0.20, 0.20], sales=[100, 100, 100, 100, 100, 100, 100, 100],
            op_margin=0.15, roe=0.20)
    _, score, note = fundamental_screen(f)
    assert "ttm" not in note   # flat TTM growth must not score the Sales+ tag


# ---------------------------------------------------------------------------
# Bug 3 (HIGH): M&A merger-arb price pinning
# ---------------------------------------------------------------------------

def _pinned_df(n: int = 60) -> pd.DataFrame:
    closes = np.full(n, 13.50)
    closes[-20:] = np.linspace(13.40, 13.49, 20)
    return pd.DataFrame({"close": closes}, index=pd.bdate_range("2025-01-01", periods=n))


def _normal_df(n: int = 60) -> pd.DataFrame:
    closes = np.full(n, 100.0)
    closes[-20:] = 100 + np.random.RandomState(42).normal(0, 3, 20)
    return pd.DataFrame({"close": closes}, index=pd.bdate_range("2025-01-01", periods=n))


def test_merger_arb_detected_on_tight_range():
    """20 closes all within $13.40-$13.49 -> flagged (CV well under 1.5%)."""
    flagged, cv = is_merger_arb(_pinned_df())
    assert flagged is True
    assert cv < 0.015


def test_normal_stock_not_flagged():
    """20 closes with normal 3% stdev variation -> not flagged."""
    flagged, cv = is_merger_arb(_normal_df())
    assert flagged is False
    assert cv >= 0.015


# ---------------------------------------------------------------------------
# fundamental_trend: EPS/revenue trajectory tag for Momentum-tier stocks
# ---------------------------------------------------------------------------

def test_fundamental_trend_accelerating_eps():
    """3 quarters of rising EPS -> improving=True, eps_accelerating=True."""
    f = dict(eps=[-0.12, 0.31, 0.58], sales=[])
    trend = fundamental_trend(f)
    assert trend["improving"] is True
    assert trend["eps_accelerating"] is True
    assert trend["trend_label"] == "EPS $-0.12→$0.31→$0.58 (↑)"


def test_fundamental_trend_flat():
    """EPS flat across 4 quarters -> improving=False."""
    f = dict(eps=[0.20, 0.20, 0.20, 0.20], sales=[])
    trend = fundamental_trend(f)
    assert trend["improving"] is False
    assert trend["eps_accelerating"] is False


def test_fundamental_trend_insufficient_data():
    """Only 1 quarter available -> improving=False."""
    f = dict(eps=[0.10], sales=[])
    trend = fundamental_trend(f)
    assert trend["improving"] is False
