"""Starting test suite. Demonstrates the discipline CLAUDE.md requires:
every detector gets a positive AND a negative fixture; the funnel is
golden-tested. Future agents EXTEND this, never delete coverage."""
import numpy as np
import pandas as pd
import pytest

from sepa import db, ingest
from sepa.indicators import add_mas
from sepa.patterns import detect_vcp, detect_power_play
from sepa.screens import trend_template, classify_stage, weighted_rs_return
from sepa.run_daily import run


# ---------- helpers ----------
def _df(closes, vols, start="2024-01-01"):
    idx = pd.bdate_range(start=start, periods=len(closes))
    closes = np.asarray(closes, float)
    return pd.DataFrame({
        "open": closes * 0.999, "high": closes * 1.015,
        "low": closes * 0.985, "close": closes, "volume": vols}, index=idx)


def _walk(n, drift, vol, p0, seed=0):
    np.random.seed(seed)
    return p0 * np.exp(np.cumsum(np.random.normal(drift, vol, n)))


# ---------- POWER PLAY: positive + negative ----------
def test_power_play_fires_on_textbook_shape():
    dorm = _walk(210, 0.0005, 0.006, 8, seed=1)
    thrust = np.linspace(dorm[-1], dorm[-1] * 2.15, 32)
    flag = np.concatenate([np.linspace(thrust[-1], thrust[-1]*0.9, 9),
                           np.linspace(thrust[-1]*0.9, thrust[-1]*0.985, 9)])
    closes = np.concatenate([dorm, thrust, flag])
    vols = np.concatenate([np.full(210, 1e6), np.full(32, 4e6), np.linspace(1.2e6, 4e5, 18)])
    setup = detect_power_play(add_mas(_df(closes, vols)))
    assert setup is not None and setup.type == "Power Play"


def test_power_play_does_not_fire_on_quiet_uptrend():
    closes = _walk(280, 0.003, 0.012, 10, seed=2)        # steady, no thrust
    vols = np.full(280, 1e6)
    assert detect_power_play(add_mas(_df(closes, vols))) is None


# ---------- VCP: positive + negative ----------
def _vcp_closes():
    up = _walk(230, 0.004, 0.018, 10, seed=3)
    legs, p = [], up[-1]
    for depth, length in [(0.13, 16), (0.07, 12), (0.035, 10)]:
        down = np.linspace(p, p*(1-depth), length//2)
        back = np.linspace(p*(1-depth), p*0.995, length-length//2)
        legs.append(np.concatenate([down, back])); p = legs[-1][-1]
    return np.concatenate([up] + legs), len(up)


def test_vcp_fires_on_contracting_base():
    closes, uplen = _vcp_closes()
    vols = np.concatenate([np.full(uplen, 1.3e6),
                           np.full(len(closes)-uplen, 6e5)])    # dry-up in base
    setup = detect_vcp(add_mas(_df(closes, vols)))
    assert setup is not None and setup.type == "VCP / 3C"
    assert setup.footprint.endswith("T")                       # footprint emitted


def test_vcp_does_not_fire_without_volume_dryup():
    closes, uplen = _vcp_closes()
    vols = np.full(len(closes), 2e6)                            # no dry-up
    assert detect_vcp(add_mas(_df(closes, vols))) is None


# ---------- screens sanity ----------
def test_trend_template_strong_uptrend_scores_high():
    closes = _walk(300, 0.004, 0.012, 10, seed=4)
    tt, checks = trend_template(add_mas(_df(closes, np.full(300, 1e6))), rs=90)
    assert tt >= 6


def test_stage_classifier_labels_decline():
    closes = _walk(300, -0.004, 0.02, 60, seed=5)
    df = add_mas(_df(closes, np.full(300, 1e6)))
    tt, _ = trend_template(df, rs=10)
    stage, _ = classify_stage(df, tt)
    assert stage == 4


# ---------- GOLDEN funnel: fixed synthetic universe → stable tiers ----------
def test_funnel_golden_tiers(tmp_path):
    con = db.connect(tmp_path / "g.db")
    ingest.seed_synthetic(con)
    curr, trans, sent = run(con)
    tiers = {t: sorted(k for k, v in curr.items() if v["tier"] == t)
             for t in ["Watch", "Buy Alert", "Buy Ready"]}
    # Buy Ready must contain the planted VCP + both power plays
    assert "AAVCP" in tiers["Buy Ready"]
    assert "DDPOW" in tiers["Buy Ready"] and "EEPOW" in tiers["Buy Ready"]
    # decliners/flat names must NOT appear anywhere
    flat = {k for grp in tiers.values() for k in grp}
    assert "JJDEC" not in flat and "KKDEC" not in flat


def test_alert_dedupe_holds(tmp_path):
    con = db.connect(tmp_path / "d.db")
    ingest.seed_synthetic(con)
    _, _, first = run(con)
    _, _, second = run(con)                # rerun same day
    assert len(first) > 0 and len(second) == 0
