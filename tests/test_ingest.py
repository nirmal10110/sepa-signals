"""Offline tests for ingest layer. No network — uses fixture JSON shapes
that match real EDGAR/yfinance responses."""
import logging
import numpy as np
import pandas as pd
import pytest

from sepa.ingest import hygiene_filter, _quarterly, _is_etf_or_shell, _fuzzy_get
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


def test_quarterly_prefers_most_recent_concept():
    """When Revenues has only old data and the fallback concept has newer data,
    _quarterly must pick the fallback (MU-style concept switch).

    Revenues:   2019-03-31 and 2019-06-30 (stale)
    RevenueFromContract...: 2024-03-31 and 2024-06-30 (current)
    Expected: the 2024 series wins.
    """
    old_series = [
        {"end": "2019-03-31", "val": 1_000, "form": "10-Q", "fp": "Q1", "filed": "2019-05-01"},
        {"end": "2019-06-30", "val": 1_100, "form": "10-Q", "fp": "Q2", "filed": "2019-08-01"},
    ]
    new_series = [
        {"end": "2024-03-31", "val": 5_000, "form": "10-Q", "fp": "Q1", "filed": "2024-05-01"},
        {"end": "2024-06-30", "val": 6_000, "form": "10-Q", "fp": "Q2", "filed": "2024-08-01"},
    ]
    facts = {
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": old_series}},
                "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": new_series}},
            }
        }
    }
    result = _quarterly(facts, _REV_CONCEPTS)
    assert len(result) == 2
    assert result[-1][0] == "2024-06-30"
    assert result[-1][1] == 6_000


# ---------------------------------------------------------------- _fuzzy_get
def test_fuzzy_get_exact_match_no_warning(caplog):
    """Exact date match returns value without any warning."""
    d = {"2024-03-31": 5_000_000}
    with caplog.at_level(logging.WARNING, logger="sepa.ingest"):
        result = _fuzzy_get(d, "2024-03-31", "TEST", "revenue")
    assert result == 5_000_000
    assert "fuzzy matched" not in caplog.text


def test_fuzzy_get_resolves_3_day_offset(caplog):
    """Revenue date 3 days before EPS date should still be found."""
    d = {"2024-03-28": 9_000_000}
    with caplog.at_level(logging.WARNING, logger="sepa.ingest"):
        result = _fuzzy_get(d, "2024-03-31", "MU", "revenue")
    assert result == 9_000_000
    assert "fuzzy matched" in caplog.text
    assert "MU revenue" in caplog.text
    assert "3 day delta" in caplog.text


def test_fuzzy_get_resolves_positive_offset(caplog):
    """Revenue date 3 days *after* EPS date should also be found."""
    d = {"2024-04-03": 7_500_000}
    with caplog.at_level(logging.WARNING, logger="sepa.ingest"):
        result = _fuzzy_get(d, "2024-03-31", "NVDA", "revenue")
    assert result == 7_500_000
    assert "fuzzy matched" in caplog.text


def test_fuzzy_get_returns_zero_beyond_7_days():
    """Dates more than 7 days apart must not fuzzy-match (genuine missing data)."""
    d = {"2024-03-23": 1_000_000}   # 8 days before 2024-03-31
    result = _fuzzy_get(d, "2024-03-31", "TEST", "revenue")
    assert result == 0


def test_fuzzy_get_returns_zero_on_empty_dict():
    assert _fuzzy_get({}, "2024-03-31", "TEST", "revenue") == 0


def test_fuzzy_get_picks_nearest_when_multiple_candidates():
    """When two keys are within 7 days, the closer one wins."""
    d = {"2024-03-26": 111, "2024-03-30": 999}  # 5 days and 1 day from 2024-03-31
    result = _fuzzy_get(d, "2024-03-31", "TEST", "revenue")
    assert result == 999


# ---------------------------------------------------------------- all-zero sales quality check
def test_all_zero_sales_warning_when_eps_present(caplog, tmp_path):
    """load_fundamentals must warn when sales are all 0 but EPS is non-zero."""
    from unittest.mock import patch, MagicMock
    from sepa import db as sepa_db
    from sepa.ingest import load_fundamentals

    # Minimal real-shaped EDGAR response: EPS present, revenue dates off by 10 days
    # (beyond fuzzy window) so all lookups return 0.
    facts_json = {
        "facts": {
            "us-gaap": {
                "EarningsPerShareDiluted": {
                    "units": {
                        "USD/shares": [
                            {"end": "2024-03-31", "val": 1.20, "form": "10-Q", "fp": "Q1", "filed": "2024-05-01"},
                            {"end": "2024-06-30", "val": 1.50, "form": "10-Q", "fp": "Q2", "filed": "2024-08-01"},
                        ]
                    }
                },
                "Revenues": {
                    "units": {
                        "USD": [
                            # dates are 10 days off — beyond the 7-day fuzzy window
                            {"end": "2024-03-21", "val": 5_000_000, "form": "10-Q", "fp": "Q1", "filed": "2024-05-01"},
                            {"end": "2024-06-20", "val": 6_000_000, "form": "10-Q", "fp": "Q2", "filed": "2024-08-01"},
                        ]
                    }
                },
            }
        }
    }

    con = sepa_db.connect(tmp_path / "test.db")
    sepa_db.upsert_security(con, "FAKE", "Fake Corp", "NASDAQ", "Tech")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = facts_json

    with patch("sepa.ingest._fundamentals_fresh", return_value=False), \
         patch("sepa.ingest._retry", return_value=mock_resp):
        with caplog.at_level(logging.WARNING, logger="sepa.ingest"):
            load_fundamentals(con, "FAKE", 12345)

    assert "sales all-zero despite eps data present" in caplog.text
    assert "FAKE" in caplog.text
