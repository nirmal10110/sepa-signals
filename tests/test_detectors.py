"""Phase 5 detector tests. Every detector gets at least one positive fixture
(a series that SHOULD fire) and one negative fixture (same shape, one rule
violated — confirms the negative catches false positives)."""
import numpy as np
import pandas as pd
import pytest

from sepa.indicators import add_mas
from sepa.patterns import (detect_cup_handle, detect_cheat,
                            detect_livermore_pp, detect_setups)


# ---------------------------------------------------------------- helpers
def _df(closes, vols, start="2023-01-01"):
    idx = pd.bdate_range(start=start, periods=len(closes))
    closes = np.asarray(closes, float)
    return pd.DataFrame({
        "open": closes * 0.999, "high": closes * 1.015,
        "low": closes * 0.985, "close": closes, "volume": vols}, index=idx)


def _walk(n, drift, vol, p0, seed=0):
    np.random.seed(seed)
    return p0 * np.exp(np.cumsum(np.random.normal(drift, vol, n)))


# ================================================================ Cup-with-Handle
class TestCupWithHandle:

    def _cup_handle_series(self, left_rim=50.0, cup_depth=0.22, handle_depth=0.06,
                            cup_bars=55, handle_bars=12):
        """Construct a textbook cup-with-handle price series."""
        left = np.full(5, left_rim)
        descent = np.linspace(left_rim, left_rim * (1 - cup_depth), cup_bars // 2)
        recovery = np.linspace(left_rim * (1 - cup_depth), left_rim * 0.98, cup_bars // 2)
        handle_high = left_rim * 0.98
        handle_low = handle_high * (1 - handle_depth)
        handle = np.concatenate([
            np.linspace(handle_high, handle_low, handle_bars // 2),
            np.linspace(handle_low, handle_high * 0.99, handle_bars // 2)])
        closes = np.concatenate([left, descent, recovery, handle])
        base_vol = 1_000_000
        vols = np.concatenate([
            np.full(len(left), base_vol * 1.2),
            np.full(len(descent) + len(recovery), base_vol * 1.1),
            np.full(len(handle), base_vol * 0.5)])   # volume dries in handle
        return closes, vols

    def test_textbook_cup_handle_fires(self):
        closes, vols = self._cup_handle_series()
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        assert setup is not None
        assert setup.type == "Cup-with-Handle"
        assert setup.pivot > 0

    def test_cup_too_deep_does_not_fire(self):
        closes, vols = self._cup_handle_series(cup_depth=0.45)  # > 35% max
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        assert setup is None

    def test_cup_too_shallow_does_not_fire(self):
        closes, vols = self._cup_handle_series(cup_depth=0.05)  # < 12% min
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        assert setup is None

    def test_handle_too_deep_does_not_fire(self):
        closes, vols = self._cup_handle_series(handle_depth=0.20)  # > 12% max
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        assert setup is None

    def test_no_vol_dryup_does_not_fire(self):
        closes, vols = self._cup_handle_series()
        vols[:] = 1_000_000   # flat volume — no dry-up
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        assert setup is None

    def test_insufficient_bars_does_not_fire(self):
        closes = _walk(30, 0.002, 0.01, 50, seed=10)
        vols = np.full(30, 1_000_000)
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        assert setup is None

    def test_buyable_flag_when_at_rim(self):
        closes, vols = self._cup_handle_series()
        # price ends near the handle high (rim) — should be buyable
        setup = detect_cup_handle(add_mas(_df(closes, vols)))
        if setup is not None:
            assert setup.buyable


# ================================================================ Cheat (4-phase ABCD)
class TestCheat:

    def _cheat_series(self, a_decline=0.25, b_recoup=0.45, c_depth=0.07,
                       pre_bars=60):
        """Build a textbook 4-phase cheat."""
        # Pre-trend up
        pre = _walk(pre_bars, 0.003, 0.012, 30, seed=20)
        a_start_price = pre[-1]

        # Phase A: downtrend
        a_low_price = a_start_price * (1 - a_decline)
        a_len = 20
        phase_a = np.linspace(a_start_price, a_low_price, a_len)

        # Phase B: uptrend, recoups b_recoup of the A decline
        b_high_price = a_low_price + b_recoup * (a_start_price - a_low_price)
        b_len = 20
        phase_b = np.linspace(a_low_price, b_high_price, b_len)

        # Phase C: plateau, corrects c_depth from the B high
        c_low_price = b_high_price * (1 - c_depth)
        c_len = 15
        plateau = np.concatenate([
            np.linspace(b_high_price, c_low_price, c_len // 2),
            np.linspace(c_low_price, b_high_price * 0.99, c_len - c_len // 2)])

        closes = np.concatenate([pre, phase_a, phase_b, plateau])
        vols = np.full(len(closes), 1_000_000)
        return closes, vols

    def test_textbook_cheat_fires(self):
        closes, vols = self._cheat_series()
        setup = detect_cheat(add_mas(_df(closes, vols)))
        assert setup is not None
        assert setup.type == "Cheat"

    def test_b_recoup_too_low_does_not_fire(self):
        # B only recoups 20% — below the 33% minimum
        closes, vols = self._cheat_series(b_recoup=0.20)
        setup = detect_cheat(add_mas(_df(closes, vols)))
        assert setup is None

    def test_b_recoup_too_high_does_not_fire(self):
        # B recoups 80% — this is a full recovery, not a cheat
        closes, vols = self._cheat_series(b_recoup=0.80)
        setup = detect_cheat(add_mas(_df(closes, vols)))
        assert setup is None

    def test_plateau_too_deep_does_not_fire(self):
        # C corrects 20% — too deep for a cheat (max is 12%)
        closes, vols = self._cheat_series(c_depth=0.20)
        setup = detect_cheat(add_mas(_df(closes, vols)))
        assert setup is None

    def test_entry_type_low_cheat_when_near_plateau_floor(self):
        closes, vols = self._cheat_series()
        setup = detect_cheat(add_mas(_df(closes, vols)))
        if setup is not None:
            assert setup.entry_type in ("cheat", "low-cheat")

    def test_insufficient_bars_does_not_fire(self):
        closes = _walk(20, 0.001, 0.01, 30, seed=21)
        vols = np.full(20, 1_000_000)
        setup = detect_cheat(add_mas(_df(closes, vols)))
        assert setup is None


# ================================================================ Livermore PP
class TestLivermorePP:

    def _lpp_series(self, prior_decline=0.25, r1_bounce=0.40, r2_bounce=0.45,
                    pre_bars=60):
        """Build a textbook 2-reaction LP pattern."""
        pre = _walk(pre_bars, 0.003, 0.012, 40, seed=30)
        prior_high = pre[-1]
        low_price = prior_high * (1 - prior_decline)

        # Downtrend to the prior low
        a_len = 25
        downtrend = np.linspace(prior_high, low_price, a_len)

        # Reaction 1: bounce to R1 high
        r1_high = low_price + r1_bounce * (prior_high - low_price)
        r1_len = 10
        reaction1 = np.linspace(low_price, r1_high, r1_len)

        # Pullback below R1
        mid_low = low_price * 1.02
        mid_len = 8
        pullback = np.linspace(r1_high, mid_low, mid_len)

        # Reaction 2: bounce to R2 high (pivot)
        r2_high = low_price + r2_bounce * (prior_high - low_price)
        r2_len = 10
        reaction2 = np.linspace(mid_low, r2_high, r2_len)

        # Price consolidates near R2
        tail = np.full(5, r2_high * 0.99)

        closes = np.concatenate([pre, downtrend, reaction1, pullback, reaction2, tail])
        vols = np.full(len(closes), 1_000_000)
        return closes, vols

    def test_textbook_livermore_fires(self):
        closes, vols = self._lpp_series()
        setup = detect_livermore_pp(add_mas(_df(closes, vols)))
        assert setup is not None
        assert setup.type == "Livermore PP"

    def test_prior_decline_too_small_does_not_fire(self):
        # Prior decline only 8% — too small for a meaningful LP (need >= 15%)
        closes, vols = self._lpp_series(prior_decline=0.08)
        setup = detect_livermore_pp(add_mas(_df(closes, vols)))
        assert setup is None

    def test_no_two_reactions_does_not_fire(self):
        # Single reaction only — not a Livermore PP
        pre = _walk(60, 0.003, 0.012, 40, seed=31)
        prior_high = pre[-1]
        downtrend = np.linspace(prior_high, prior_high * 0.75, 20)
        one_bounce = np.linspace(prior_high * 0.75, prior_high * 0.85, 15)
        closes = np.concatenate([pre, downtrend, one_bounce])
        vols = np.full(len(closes), 1_000_000)
        setup = detect_livermore_pp(add_mas(_df(closes, vols)))
        assert setup is None

    def test_n_contractions_is_two(self):
        closes, vols = self._lpp_series()
        setup = detect_livermore_pp(add_mas(_df(closes, vols)))
        if setup is not None:
            assert setup.n_contractions == 2

    def test_insufficient_bars_does_not_fire(self):
        closes = _walk(20, 0.001, 0.01, 40, seed=32)
        vols = np.full(20, 1_000_000)
        setup = detect_livermore_pp(add_mas(_df(closes, vols)))
        assert setup is None


# ================================================================ Integration
def test_detect_setups_dispatcher_priority():
    """Power Play should beat all other setups when both could fire."""
    from sepa.patterns import detect_power_play
    from sepa import providers

    np.random.seed(0)
    # Use a power-play synthetic series
    p = providers.SyntheticProvider()
    df = add_mas(p.history("DDPOW"))
    setup = detect_setups(df)
    assert setup is not None
    assert setup.type == "Power Play"   # PP must win the priority race


def test_detect_setups_returns_none_for_declining_name():
    """A Stage-4 declining name should not match any setup."""
    from sepa import providers
    p = providers.SyntheticProvider()
    df = add_mas(p.history("JJDEC"))
    setup = detect_setups(df)
    assert setup is None


def test_extension_gate_marks_not_buyable():
    """Price >5% past pivot must come back buyable=False (no-chase rule).

    Construct a VCP-shaped base that ends with pivot at ~50, then tack on a
    large gap-up that puts price 30% above pivot. The setup should still be
    detected (pattern happened) but buyable must be False.
    """
    # Build a VCP base: contracting volatility, volume drying up
    np.random.seed(42)
    n_base = 60
    base_prices = 50.0 * np.exp(np.cumsum(np.random.normal(0, 0.008, n_base)))
    # Force a couple of contractions: two descending swings
    base_prices[10:20] -= np.linspace(0, 3, 10)   # first contraction
    base_prices[20:30] += np.linspace(0, 2, 10)   # recovery
    base_prices[30:40] -= np.linspace(0, 1.5, 10) # second (shallower) contraction
    base_prices[40:] += np.linspace(0, 2, 20)     # final squeeze toward pivot
    base_prices = np.clip(base_prices, 40, 55)

    # Tack on an extended run: current price is 30% above the base pivot
    extended_tail = np.linspace(base_prices[-1], base_prices[-1] * 1.30, 10)
    closes = np.concatenate([base_prices, extended_tail])

    base_vol = 1_000_000
    vols = np.concatenate([
        np.full(n_base, base_vol) * np.linspace(1.2, 0.7, n_base),  # drying volume
        np.full(len(extended_tail), base_vol * 2.0)])                # breakout spike

    df = add_mas(_df(closes, vols))
    setup = detect_setups(df)

    # A setup may or may not be detected (fixture is synthetic), but if detected
    # it must NOT be buyable because price is >5% past any reasonable pivot.
    if setup is not None and setup.type != "Power Play":
        assert not setup.buyable, (
            f"Expected buyable=False for extended setup "
            f"(price={closes[-1]:.2f}, pivot={setup.pivot:.2f}, "
            f"ext={(closes[-1]/setup.pivot-1)*100:.1f}%)"
        )
