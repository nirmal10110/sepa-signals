"""Tests for sepa/classify.py — TT minimum gates for tier promotion."""
import numpy as np
import pandas as pd
import pytest
from sepa.classify import decide_tier
from sepa.patterns import Setup


def _pp_setup(buyable: bool = True, pivot: float = 100.0, entry: float = 101.0,
              stop: float = 80.0) -> Setup:
    return Setup("Power Play", pivot=pivot, entry=entry, stop=stop,
                 footprint="+115%/32d flag 18d", buyable=buyable, base_weeks=4)


def _df_with_breakout(entry: float = 101.0, pivot: float = 100.0,
                      vol_mult: float = 2.0, n: int = 60) -> pd.DataFrame:
    """DataFrame where the last bar closes above pivot at vol_mult × 50-day avg."""
    closes = np.full(n, pivot * 0.98)
    closes[-1] = entry
    vols = np.full(n, 1_000_000.0)
    vols[-1] = vol_mult * 1_000_000.0   # clearly above BREAKOUT_VOL_MULT (1.3×)
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": vols,
    }, index=idx)


# ---------------------------------------------------------------------------
# Potential Buy gates
# ---------------------------------------------------------------------------

def test_potential_buy_requires_tt_6():
    """Power Play, TT 5/8 — below POTENTIAL_BUY_TT_MIN — must be demoted to Buy Alert."""
    setup = _pp_setup(buyable=True)
    tier, _ = decide_tier(stage=2, tt_score=5, rs=80, funda_pass=True,
                          setup=setup, market_tone="Confirmed uptrend")
    assert tier == "Buy Alert"


def test_potential_buy_passes_with_tt_6():
    """Power Play, TT 6/8 — meets POTENTIAL_BUY_TT_MIN — must reach Potential Buy."""
    setup = _pp_setup(buyable=True)
    tier, _ = decide_tier(stage=2, tt_score=6, rs=80, funda_pass=True,
                          setup=setup, market_tone="Confirmed uptrend")
    assert tier == "Potential Buy"


# ---------------------------------------------------------------------------
# Buy Ready gates
# ---------------------------------------------------------------------------

def test_buy_ready_requires_tt_7():
    """Power Play, TT 6/8, confirmed breakout → Potential Buy (not Buy Ready)."""
    setup = _pp_setup(buyable=True, pivot=100.0, entry=101.0)
    df = _df_with_breakout(entry=101.0, pivot=100.0)
    tier, _ = decide_tier(stage=2, tt_score=6, rs=80, funda_pass=True,
                          setup=setup, market_tone="Confirmed uptrend", df=df)
    assert tier == "Potential Buy"


def test_buy_ready_passes_with_tt_7():
    """Power Play, TT 7/8, confirmed breakout → Buy Ready."""
    setup = _pp_setup(buyable=True, pivot=100.0, entry=101.0)
    df = _df_with_breakout(entry=101.0, pivot=100.0)
    tier, _ = decide_tier(stage=2, tt_score=7, rs=80, funda_pass=True,
                          setup=setup, market_tone="Confirmed uptrend", df=df)
    assert tier == "Buy Ready"
