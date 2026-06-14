"""Offline tests for ingest layer. No network — uses fixture JSON shapes
that match real EDGAR/yfinance responses."""
import numpy as np
import pandas as pd
import pytest

from sepa.ingest import hygiene_filter, _quarterly, _is_etf_or_shell
from sepa.ingest import _EPS_CONCEPTS, _REV_CONCEPTS, _OP_CONCEPTS, _NI_CONCEPTS, _EQ_CONCEPTS
from sepa import config as C


# ---------------------------------------------------------------- hygiene filter
def _price_df(close, volume):
    idx = pd.bdate_range(start="2024-01-01", periods=len(close))
    return pd.DataFrame({"open": close, "high": close, "low": close,
                         "close": close, "volume": volume}, index=idx)


def test_hygiene_filter_passes_liquid_stock():
    closes = np.full(60, 50.0)
    vols = np.full(60, 100_000.0)     # avg dv = $5M
    df = hygiene_filter(_price_df(closes, vols))
    assert not df.empty


def test_hygiene_filter_rejects_penny_stock():
    closes = np.full(60, 5.0)         # below $10
    vols = np.full(60, 1_000_000.0)
    df = hygiene_filter(_price_df(closes, vols))
    assert df.empty


def test_hygiene_filter_rejects_illiquid_stock():
    closes = np.full(60, 50.0)
    vols = np.full(60, 100.0)         # avg dv = $5,000 — far below $1M
    df = hygiene_filter(_price_df(closes, vols))
    assert df.empty


def test_hygiene_filter_rejects_empty_df():
    assert hygiene_filter(pd.DataFrame()).empty


# ---------------------------------------------------------------- ETF / shell detection
def test_etf_detection_by_name():
    assert _is_etf_or_shell("SPY", "SPDR S&P 500 ETF Trust", None)
    assert _is_etf_or_shell("QQQ", "Invesco QQQ Trust", None)


def test_etf_detection_by_sic():
    assert _is_etf_or_shell("XYZ", "Some Company", 6726)


def test_real_company_not_flagged():
    assert not _is_etf_or_shell("AAPL", "Apple Inc.", 3674)
    assert not _is_etf_or_shell("MSFT", "Microsoft Corporation", 7372)


# ---------------------------------------------------------------- EDGAR concept parsing
def _edgar_fixture(concept_name, vals, units_key="USD", form="10-Q"):
    """Build a minimal EDGAR companyfacts JSON shape."""
    series = [{"end": f"2024-0{i+1}-30", "val": v, "form": form,
               "fp": f"Q{i+1}", "filed": "2024-05-01"}
              for i, v in enumerate(vals)]
    return {"facts": {"us-gaap": {concept_name: {"units": {units_key: series}}}}}


def test_quarterly_parses_primary_eps_concept():
    facts = _edgar_fixture("EarningsPerShareDiluted", [0.10, 0.18, 0.31, 0.52])
    result = _quarterly(facts, _EPS_CONCEPTS)
    assert len(result) == 4
    assert result[-1][1] == pytest.approx(0.52)


def test_quarterly_falls_back_to_secondary_eps_concept():
    """Filer uses EarningsPerShareBasic instead of EarningsPerShareDiluted."""
    facts = _edgar_fixture("EarningsPerShareBasic", [0.20, 0.25, 0.30])
    result = _quarterly(facts, _EPS_CONCEPTS)
    assert len(result) == 3


def test_quarterly_returns_empty_for_missing_concept():
    facts = {"facts": {"us-gaap": {}}}
    result = _quarterly(facts, _EPS_CONCEPTS)
    assert result == []


def test_quarterly_deduplicates_periods():
    """Same period end appearing twice (amended filing) should appear once."""
    series = [
        {"end": "2024-03-31", "val": 0.10, "form": "10-Q", "fp": "Q1", "filed": "2024-05-01"},
        {"end": "2024-03-31", "val": 0.12, "form": "10-Q", "fp": "Q1", "filed": "2024-05-15"},
        {"end": "2024-06-30", "val": 0.20, "form": "10-Q", "fp": "Q2", "filed": "2024-08-01"},
    ]
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": series}}}}}
    result = _quarterly(facts, _EPS_CONCEPTS)
    ends = [r[0] for r in result]
    assert len(set(ends)) == len(ends)   # no duplicates


def test_quarterly_revenue_fallback_chain():
    """Uses RevenueFromContractWithCustomer... when Revenues is absent."""
    concept = "RevenueFromContractWithCustomerExcludingAssessedTax"
    facts = _edgar_fixture(concept, [100, 120, 140], units_key="USD")
    result = _quarterly(facts, _REV_CONCEPTS)
    assert len(result) == 3
    assert result[0][1] == 100
