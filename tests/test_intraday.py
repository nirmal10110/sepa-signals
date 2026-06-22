"""Tests for sepa/run_intraday.py — yfinance 5m bar price/volume extraction."""
import pandas as pd
import pytest
from sepa import alerter
from sepa import db
from sepa import run_intraday as ri_mod
from sepa.run_intraday import _flatten_columns, _last_close_and_volume


def _multiindex_bars(ticker: str = "MU") -> pd.DataFrame:
    """Mimic yf.download()'s (Price, Ticker) MultiIndex columns for one ticker.

    This is the real shape returned by the installed yfinance version even for
    a single-ticker download — the bug this guards against.
    """
    idx = pd.date_range("2026-06-22 09:30", periods=3, freq="5min")
    cols = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Volume"], [ticker]])
    data = [
        [100.0, 101.0, 99.0, 100.5, 10_000],
        [100.5, 102.0, 100.0, 101.5, 12_000],
        [101.5, 103.0, 101.0, 102.5, 15_000],
    ]
    return pd.DataFrame(data, index=idx, columns=cols)


def _flat_bars() -> pd.DataFrame:
    """Single-level columns, as yfinance returns for some versions/configs."""
    idx = pd.date_range("2026-06-22 09:30", periods=3, freq="5min")
    return pd.DataFrame({
        "Open": [100.0, 100.5, 101.5],
        "High": [101.0, 102.0, 103.0],
        "Low": [99.0, 100.0, 101.0],
        "Close": [100.5, 101.5, 102.5],
        "Volume": [10_000, 12_000, 15_000],
    }, index=idx)


def test_flatten_columns_collapses_multiindex():
    df = _flatten_columns(_multiindex_bars())
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_flatten_columns_is_noop_for_flat_columns():
    df = _flatten_columns(_flat_bars())
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_intraday_price_lookup_returns_scalar():
    """MultiIndex columns (the real yfinance bug shape) must yield plain floats."""
    last_close, today_vol = _last_close_and_volume(_multiindex_bars())
    assert isinstance(last_close, float)
    assert isinstance(today_vol, float)
    assert last_close == 102.5
    assert today_vol == 10_000 + 12_000 + 15_000


def test_intraday_price_lookup_returns_scalar_for_flat_columns():
    """Already-flat columns must also extract cleanly (no regression)."""
    last_close, today_vol = _last_close_and_volume(_flat_bars())
    assert isinstance(last_close, float)
    assert isinstance(today_vol, float)
    assert last_close == 102.5
    assert today_vol == 37_000


def test_intraday_error_rate_alert_fires(tmp_path, monkeypatch):
    """10/20 tickers raising should trip the >5% error-rate alert, while the
    10 healthy tickers still get scanned (no exception propagates)."""
    con = db.connect(tmp_path / "intraday_errors.db")
    tickers = [f"TST{i}" for i in range(20)]
    failing = set(tickers[:10])

    for t in tickers:
        db.set_state(con, t, "Watch", "2026-06-22", "2026-06-22")
        con.execute("INSERT INTO signals(ticker,asof,pivot) VALUES(?,?,?)",
                    (t, "2026-06-22", 100.0))
    con.commit()

    def fake_download(ticker, *a, **kw):
        if ticker in failing:
            raise RuntimeError("simulated yfinance failure")
        return _flat_bars()

    monkeypatch.setattr(ri_mod, "_market_open", lambda: True)
    monkeypatch.setattr("yfinance.download", fake_download)

    sent_msgs = []
    monkeypatch.setattr(alerter, "send_text", lambda text: sent_msgs.append(text))

    alerts = ri_mod.run_intraday(con)

    # healthy tickers have no stored price history -> `continue` before any
    # alert logic, so no breakout alerts fire either way; what matters is
    # that they were reached (no unhandled exception bubbled up).
    assert alerts == []
    assert len(sent_msgs) == 1
    assert "degraded" in sent_msgs[0]
    assert "10/20" in sent_msgs[0]
