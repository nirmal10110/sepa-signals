"""Tests for sepa/plans.py — stop floor and trade plan recalculation."""
import pytest
from sepa.plans import apply_stop_floor


def test_stop_floor_applied_when_pattern_too_tight():
    """Stop 1.6% below entry must be pushed down to the 8% minimum floor."""
    result = apply_stop_floor(entry=13.45, computed_stop=13.23)
    # 13.45 * (1 - 0.08) = 12.374 → rounds to 12.37
    assert result["stop"] == pytest.approx(12.37, abs=0.01)
    assert result["stop"] <= 13.45 * 0.92 + 0.01


def test_stop_wide_pattern_preserved():
    """Stop already 12% below entry must not be moved — it already exceeds the floor."""
    result = apply_stop_floor(entry=100.0, computed_stop=88.0)
    assert result["stop"] == pytest.approx(88.0, abs=0.01)


def test_target_recalculated_after_floor():
    """After the stop floor is applied the 3:1 R:R target must use the corrected stop."""
    result = apply_stop_floor(entry=13.45, computed_stop=13.23)
    # stop = 12.37, risk = 13.45 - 12.37 = 1.08, target = 13.45 + 3*1.08 = 16.69
    assert result["target"] == pytest.approx(16.69, abs=0.01)
    assert result["risk_reward"] == pytest.approx(3.0)
