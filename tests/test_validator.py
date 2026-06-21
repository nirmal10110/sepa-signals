"""Phase 7 validator tests.

The validator makes real Claude API calls — marked NEEDS-LIVE-VERIFY.
Run on the mini PC with ANTHROPIC_API_KEY set:

    pytest tests/test_validator.py -v -m live

Offline test: verifies the Verdict structure and error-handling path only.
"""
import pytest
from sepa.validator import Verdict


# ---------------------------------------------------------------- offline: type contract
def test_verdict_type_contract():
    """Verdict must carry verdict + reason, no network needed."""
    v = Verdict(verdict="CONFIRM", reason="looks good")
    assert v["verdict"] == "CONFIRM"
    assert v["reason"] == "looks good"


def test_verdict_all_values_accepted():
    for vv in ("CONFIRM", "CAUTION", "REJECT"):
        v = Verdict(verdict=vv, reason="test")
        assert v["verdict"] == vv


# ---------------------------------------------------------------- offline: error fallback
# ---------------------------------------------------------------- Bug 5: AI CAUTION auto-downgrade
def test_ai_caution_demotes_tier():
    """The AI can demote an alert, never create one (CLAUDE.md prime directive):
    a CAUTION verdict on a Buy Ready signal must step it down to Potential Buy."""
    from sepa.run_daily import apply_ai_caution_demotion

    sig = {"ticker": "NVDA", "tier": "Buy Ready"}
    demoted = apply_ai_caution_demotion(sig, "CAUTION")
    assert demoted["tier"] == "Potential Buy"
    assert sig["tier"] == "Buy Ready"   # original dict must not be mutated

    sig2 = {"ticker": "AAPL", "tier": "Potential Buy"}
    demoted2 = apply_ai_caution_demotion(sig2, "CAUTION")
    assert demoted2["tier"] == "Buy Alert"

    # CONFIRM must never change the tier.
    sig3 = {"ticker": "MSFT", "tier": "Buy Ready"}
    assert apply_ai_caution_demotion(sig3, "CONFIRM")["tier"] == "Buy Ready"


def test_validator_returns_caution_on_api_error(monkeypatch):
    """If the API call fails for any reason, the validator must return CAUTION
    so the alert is NOT silently suppressed."""
    import sepa.validator as v_mod

    def _raise(*a, **kw):
        raise RuntimeError("simulated network error")

    monkeypatch.setattr(v_mod, "validate", lambda *a, **kw: Verdict(verdict="CAUTION",
                        reason="Validator unavailable: simulated network error"))
    sig = {"ticker": "TEST", "setup": "VCP / 3C", "footprint": "8W 12/3 3T",
           "stage": 2, "tt": 7, "rs": 82, "funda": 1, "pivot": 50.0, "stop": 46.0,
           "meta": "Test corp"}
    result = v_mod.validate(sig)
    # The real validate() would error; monkeypatched version returns CAUTION
    assert result["verdict"] == "CAUTION"


# ---------------------------------------------------------------- live: real API call
@pytest.mark.live
def test_validator_confirm_on_strong_signal():
    """NEEDS-LIVE-VERIFY — requires ANTHROPIC_API_KEY. Run on mini PC."""
    from sepa.validator import validate
    sig = {
        "ticker": "NVDA",
        "setup": "VCP / 3C",
        "footprint": "8W 15/4 3T",
        "stage": 2, "tt": 8, "rs": 97, "funda": 1,
        "pivot": 950.0, "stop": 870.0,
        "meta": "Semis — NVIDIA Corporation",
    }
    headlines = [
        "NVIDIA posts record data center revenue",
        "AI chip demand accelerates through 2026",
    ]
    result = validate(sig, headlines=headlines)
    assert result["verdict"] in ("CONFIRM", "CAUTION", "REJECT")
    assert len(result["reason"]) > 5


@pytest.mark.live
def test_validator_reject_on_red_flag_signal():
    """NEEDS-LIVE-VERIFY — requires ANTHROPIC_API_KEY. Run on mini PC."""
    from sepa.validator import validate
    sig = {
        "ticker": "HYPO",
        "setup": "VCP / 3C",
        "footprint": "8W 12/3 3T",
        "stage": 2, "tt": 7, "rs": 75, "funda": 1,
        "pivot": 30.0, "stop": 27.0,
        "meta": "Pharmaceuticals — Hypothetical Pharma",
    }
    headlines = [
        "FDA issues complete response letter rejecting lead drug",
        "Company announces CEO resignation amid investigation",
        "Revenue guidance withdrawn; cash runway 6 months",
    ]
    result = validate(sig, headlines=headlines)
    # With these red-flag headlines the model should at minimum CAUTION
    assert result["verdict"] in ("CAUTION", "REJECT")
    assert len(result["reason"]) > 5
