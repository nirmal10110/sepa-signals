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


# ---------------------------------------------------------------- yfinance "possibly delisted" retry
def test_process_batch_routes_empty_ticker_to_missing(tmp_path):
    """A ticker with all-empty raw rows (yfinance's false-positive 'delisted')
    must be routed to missing_out, not counted as skipped."""
    from sepa import db as sepa_db
    from sepa.ingest import _process_batch

    con = sepa_db.connect(tmp_path / "test.db")
    good = _price_df(np.full(60, 50.0), np.full(60, 100_000.0))
    empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    data = {"GOOD": good, "FTNT": empty}

    counter = [0, 0, 0]
    missing = []
    _process_batch(con, ["GOOD", "FTNT"], data, counter, missing_out=missing)

    assert missing == ["FTNT"]
    assert counter[0] == 1   # GOOD loaded
    assert counter[1] == 0   # nothing hygiene-skipped
    assert counter[2] == 0


def test_process_batch_hygiene_skip_not_routed_to_missing(tmp_path):
    """A ticker with real (non-empty) data that fails the hygiene filter is a
    genuine skip, not a batch glitch — it must NOT be retried individually."""
    from sepa import db as sepa_db
    from sepa.ingest import _process_batch

    con = sepa_db.connect(tmp_path / "test.db")
    penny = _price_df(np.full(60, 5.0), np.full(60, 1_000_000.0))  # below $10

    counter = [0, 0, 0]
    missing = []
    # single-ticker batch: _process_batch uses `data` directly, not data[t]
    _process_batch(con, ["PENNY"], penny, counter, missing_out=missing)

    assert missing == []
    assert counter[1] == 1   # skipped, not missing


def test_fetch_individual_with_retry_recovers_on_later_attempt(monkeypatch, caplog):
    """Mock yf.Ticker(t).history() to fail (empty) on the first attempt and
    return real data on the second — the ticker must be recovered and logged."""
    from unittest.mock import patch, MagicMock
    from sepa.ingest import _fetch_individual_with_retry

    good = _price_df(np.full(5, 50.0), np.full(5, 100_000.0))
    calls = {"n": 0}

    def fake_history(**kwargs):
        calls["n"] += 1
        return pd.DataFrame() if calls["n"] == 1 else good

    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = fake_history

    monkeypatch.setattr("sepa.ingest.time.sleep", lambda *_: None)
    with patch("yfinance.Ticker", return_value=mock_ticker):
        with caplog.at_level(logging.INFO, logger="sepa.ingest"):
            df = _fetch_individual_with_retry("FTNT", period="2y")

    assert not df.empty
    assert calls["n"] == 2
    assert (f"FTNT: missing from batch result, retrying individually "
            f"(attempt 1/{C.INGEST_RETRY_COUNT})") in caplog.text
    assert "FTNT: recovered via individual fetch" in caplog.text


def test_fetch_individual_with_retry_exhausts_and_logs_error(monkeypatch, caplog):
    """If every individual retry also comes back empty, log the final ERROR
    and return an empty DataFrame — the caller marks the ticker stale."""
    from unittest.mock import patch, MagicMock
    from sepa.ingest import _fetch_individual_with_retry

    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    monkeypatch.setattr("sepa.ingest.time.sleep", lambda *_: None)
    with patch("yfinance.Ticker", return_value=mock_ticker):
        with caplog.at_level(logging.WARNING, logger="sepa.ingest"):
            df = _fetch_individual_with_retry("DEADCO", period="2y")

    assert df.empty
    assert mock_ticker.history.call_count == C.INGEST_RETRY_COUNT
    assert (f"DEADCO: no price data after {C.INGEST_RETRY_COUNT} retries "
            f"— ticker will be stale") in caplog.text


def test_retry_missing_upserts_recovered_ticker(tmp_path, monkeypatch):
    """_retry_missing must upsert a ticker that recovers via individual fetch
    and bump the loaded counter."""
    from unittest.mock import patch
    from sepa import db as sepa_db
    from sepa.ingest import _retry_missing

    con = sepa_db.connect(tmp_path / "test.db")
    sepa_db.upsert_security(con, "FTNT", "Fortinet Inc", "NASDAQ", "Tech")
    recovered = _price_df(np.full(60, 80.0), np.full(60, 200_000.0))

    counter = [0, 0, 0]
    with patch("sepa.ingest._fetch_individual_with_retry", return_value=recovered):
        _retry_missing(con, ["FTNT"], counter, period="2y")

    assert counter[0] == 1
    hist = sepa_db.get_history(con, "FTNT")
    assert not hist.empty


def test_retry_missing_counts_persistent_failure(tmp_path):
    """A ticker that never recovers (still empty after retries) must be
    counted as failed, not silently dropped."""
    from unittest.mock import patch
    from sepa import db as sepa_db
    from sepa.ingest import _retry_missing

    con = sepa_db.connect(tmp_path / "test.db")
    counter = [0, 0, 0]
    with patch("sepa.ingest._fetch_individual_with_retry", return_value=pd.DataFrame()):
        _retry_missing(con, ["DEADCO"], counter)

    assert counter == [0, 0, 1]


# ---------------------------------------------------------------- stale price detection
def test_stale_ticker_logged(tmp_path, caplog):
    """A ticker whose newest stored price is older than INGEST_STALE_DAYS
    must produce a WARNING naming the ticker and last date."""
    import datetime
    from sepa import db as sepa_db
    from sepa.ingest import check_stale_prices

    con = sepa_db.connect(tmp_path / "test.db")
    sepa_db.upsert_security(con, "STALE1", "Stale Corp", "NASDAQ", "Tech")
    old_date = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
    idx = pd.DatetimeIndex([old_date])
    df = pd.DataFrame({"open": [10.0], "high": [10.0], "low": [10.0],
                       "close": [10.0], "volume": [100_000.0]}, index=idx)
    sepa_db.upsert_prices(con, "STALE1", df)
    con.commit()

    with caplog.at_level(logging.WARNING, logger="sepa.ingest"):
        stale = check_stale_prices(con, max_age_days=3)

    assert any(t == "STALE1" for t, _ in stale)
    assert "STALE PRICE DATA: STALE1" in caplog.text
    assert old_date in caplog.text


def test_fresh_ticker_not_flagged_stale(tmp_path, caplog):
    import datetime
    from sepa import db as sepa_db
    from sepa.ingest import check_stale_prices

    con = sepa_db.connect(tmp_path / "test.db")
    sepa_db.upsert_security(con, "FRESH1", "Fresh Corp", "NASDAQ", "Tech")
    today = datetime.date.today().isoformat()
    idx = pd.DatetimeIndex([today])
    df = pd.DataFrame({"open": [10.0], "high": [10.0], "low": [10.0],
                       "close": [10.0], "volume": [100_000.0]}, index=idx)
    sepa_db.upsert_prices(con, "FRESH1", df)
    con.commit()

    stale = check_stale_prices(con, max_age_days=3)
    assert not any(t == "FRESH1" for t, _ in stale)


def test_stale_ticker_alert_above_threshold(tmp_path):
    """More than STALE_TICKER_ALERT_THRESHOLD stale tickers must trigger a
    Telegram ops alert via alerter.send_text."""
    from unittest.mock import patch
    from sepa import db as sepa_db
    from sepa.ingest import check_stale_prices

    con = sepa_db.connect(tmp_path / "test.db")
    for i in range(C.STALE_TICKER_ALERT_THRESHOLD + 1):
        sepa_db.upsert_security(con, f"STALE{i}", f"Stale Corp {i}", "NASDAQ", "Tech")
    con.commit()

    with patch("sepa.alerter.send_text") as mock_send:
        check_stale_prices(con, max_age_days=3)

    mock_send.assert_called_once()
    msg = mock_send.call_args[0][0]
    assert f"{C.STALE_TICKER_ALERT_THRESHOLD + 1}" in msg
