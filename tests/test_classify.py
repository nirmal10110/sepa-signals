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


# ---------------------------------------------------------------------------
# Bug 1 (CRITICAL): pivot sanity check — reject corrupted/stale pivots
# ---------------------------------------------------------------------------

def _flat_df_with_high(hi: float, last_close: float, n: int = 60) -> pd.DataFrame:
    """n-1 bars at `hi`, last bar at `last_close` (< hi), flat volume — so the
    52wk high is unambiguously `hi` and breakout volume never surges."""
    closes = np.full(n, hi)
    closes[-1] = last_close
    vols = np.full(n, 1_000_000.0)
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.005, "low": closes * 0.995,
        "close": closes, "volume": vols,
    }, index=idx)


def _vcp_setup(pivot: float, buyable: bool = True) -> Setup:
    return Setup("VCP / 3C", pivot=pivot, entry=pivot, stop=pivot * 0.9,
                 footprint="8W 13/4 3T", buyable=buyable, base_weeks=8)


def _varied_df_with_high(hi: float, last_close: float, n: int = 60, seed: int = 7) -> pd.DataFrame:
    """Like _flat_df_with_high but with realistic day-to-day variation, so this
    fixture (used only for the 'sanity passes normally' case) never trips the
    unrelated merger-arb pinning check."""
    rng = np.random.RandomState(seed)
    closes = hi * (1 - rng.uniform(0.03, 0.10, n))
    closes[0] = hi                 # guarantee the true 52wk high is exactly `hi`
    closes[-1] = last_close
    vols = np.full(n, 1_000_000.0)
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": vols,
    }, index=idx)


def test_pivot_above_52wk_high_suppresses_signal():
    """Pivot $87 vs a true 52wk high of $72 — fabricated by a bad price join
    (the GRC incident). Must suppress to Watch, not Buy Ready/Potential Buy."""
    setup = _vcp_setup(pivot=87.0)
    df = _flat_df_with_high(hi=72.0, last_close=70.0)
    tier, reason = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                               setup=setup, market_tone="Confirmed uptrend",
                               df=df, ticker="GRC")
    assert tier == "Watch", f"expected Watch, got {tier}"
    assert "corruption" in reason.lower()


def test_pivot_below_price_suppresses_promotion():
    """Pivot $28 vs current price $47 — the base is stale, the stock already
    ran past it. Must suppress promotion (capped at Watch)."""
    setup = _vcp_setup(pivot=28.0)
    df = _flat_df_with_high(hi=50.0, last_close=47.0)
    tier, reason = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                               setup=setup, market_tone="Confirmed uptrend",
                               df=df, ticker="XYZ")
    assert tier == "Watch", f"expected Watch, got {tier}"
    assert "stale" in reason.lower() or "already ran" in reason.lower()


def test_valid_pivot_passes_sanity():
    """Pivot $86 vs 52wk high $90 and current price $87 — both checks pass,
    tier proceeds normally (not capped)."""
    setup = _vcp_setup(pivot=86.0)
    df = _varied_df_with_high(hi=90.0, last_close=87.0)
    tier, _ = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                          setup=setup, market_tone="Confirmed uptrend",
                          df=df, ticker="OK")
    assert tier == "Potential Buy", f"expected Potential Buy, got {tier}"


# ---------------------------------------------------------------------------
# Bug 3 (HIGH): M&A merger-arb price pinning
# ---------------------------------------------------------------------------

def _pinned_df(n: int = 260) -> pd.DataFrame:
    """Last 20 closes pinned within $13.40-$13.49 (deal-price pinning). 260
    bars so decide_tier's >=252-bar merger-arb gate is satisfied."""
    closes = np.full(n, 13.50)
    closes[-20:] = np.linspace(13.40, 13.49, 20)
    vols = np.full(n, 1_000_000.0)
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.002, "low": closes * 0.998,
        "close": closes, "volume": vols,
    }, index=idx)


def _normal_df(n: int = 260) -> pd.DataFrame:
    """Last 20 closes with normal 3-5% daily variation, not pinned."""
    closes = np.full(n, 100.0)
    closes[-20:] = 100 + np.random.RandomState(42).normal(0, 3, 20)
    vols = np.full(n, 1_000_000.0)
    idx = pd.bdate_range("2025-01-01", periods=n)
    return pd.DataFrame({
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": vols,
    }, index=idx)


def test_merger_arb_detected_on_tight_range():
    from sepa.screens import is_merger_arb
    df = _pinned_df()
    flagged, cv = is_merger_arb(df)
    assert flagged is True, f"expected flagged, CV={cv}"

    setup = _vcp_setup(pivot=13.45)
    tier, reason = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                               setup=setup, market_tone="Confirmed uptrend",
                               df=df, ticker="OGN")
    assert tier == "Watch", f"expected Watch (M&A-pinned), got {tier}"
    assert "pinned" in reason.lower()


def test_normal_stock_not_flagged():
    from sepa.screens import is_merger_arb
    df = _normal_df()
    flagged, cv = is_merger_arb(df)
    assert flagged is False, f"expected not flagged, CV={cv}"

    setup = _vcp_setup(pivot=100.0)
    tier, _ = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                          setup=setup, market_tone="Confirmed uptrend",
                          df=df, ticker="NORM")
    assert tier == "Potential Buy", f"expected Potential Buy, got {tier}"


# ---------------------------------------------------------------------------
# Bug 4 (MEDIUM): climax extension cap (>100% above 200SMA)
# ---------------------------------------------------------------------------

def _climax_df(close_last: float, sma200: float, n: int = 300, ramp: int = 40) -> pd.DataFrame:
    """Mostly-flat history that ramps up sharply into `close_last` over the
    last `ramp` bars (plenty of variation -> never merger-arb-pinned), with a
    constant `sma200` column so ext_from_200 is exactly determined."""
    base = close_last * 0.4
    closes = np.full(n, base)
    closes[-ramp:] = np.linspace(base, close_last, ramp)
    vols = np.full(n, 1_000_000.0)
    idx = pd.bdate_range("2024-01-01", periods=n)
    df = pd.DataFrame({
        "open": closes * 0.999, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": vols,
    }, index=idx)
    df["sma200"] = sma200
    return df


def test_climax_extension_demotes_potential_buy():
    """close=200, sma200=90 (+122% extension) -> Potential Buy demoted to Buy Alert."""
    df = _climax_df(close_last=200.0, sma200=90.0)
    setup = _vcp_setup(pivot=190.0)
    tier, reason = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                               setup=setup, market_tone="Confirmed uptrend",
                               df=df, ticker="STX")
    assert tier == "Buy Alert", f"expected Buy Alert (climax-demoted), got {tier}"
    assert "CLIMAX" in reason


def test_within_cap_not_demoted():
    """close=150, sma200=90 (+67% extension, under the 100% cap) -> stays Potential Buy."""
    df = _climax_df(close_last=150.0, sma200=90.0)
    setup = _vcp_setup(pivot=140.0)
    tier, reason = decide_tier(stage=2, tt_score=8, rs=80, funda_pass=True,
                               setup=setup, market_tone="Confirmed uptrend",
                               df=df, ticker="OK2")
    assert tier == "Potential Buy", f"expected Potential Buy, got {tier}"
    assert "CLIMAX" not in reason


def test_climax_tag_propagates_to_card():
    from sepa.alerter import build_card
    sig = {
        "ticker": "STX", "setup": "VCP / 3C", "meta": "Technology — Seagate",
        "stage": 2, "tt": 8, "rs": 95, "funda": 1, "footprint": "8W 13/4 3T",
        "pivot": 190.0, "entry": 195.0, "stop": 175.0, "tier": "Buy Alert",
        "ret_1y": None, "ext_200": 122.0, "climax_flag": False,
        "climax_risk": True, "market_tone": "Confirmed uptrend", "ud_vol": 0,
    }
    card = build_card(sig)
    assert "CLIMAX RISK" in card
    assert "122" in card
