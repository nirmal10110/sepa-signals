"""Tests for sepa/run_intraday.py — re-evaluate-from-scratch breakout logic."""
import pandas as pd
from sepa import alerter
from sepa import db
from sepa import run_intraday as ri


def _trending_history(start: float, step: float, n: int = 252,
                      volume: float = 1_000_000.0) -> pd.DataFrame:
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = [start + i * step for i in range(n)]
    return pd.DataFrame({"close": closes, "volume": [volume] * n}, index=idx)


def _uptrend() -> pd.DataFrame:
    """252-day steady uptrend — clears every Stage 2 + trend-template check."""
    return _trending_history(start=50.0, step=0.4)


def _downtrend() -> pd.DataFrame:
    """252-day steady downtrend — price stays under its own 200SMA (Stage != 2)."""
    return _trending_history(start=200.0, step=-0.3)


def test_direction_check_crossing_from_below_fires_alert():
    history = _uptrend()
    prev_close = float(history["close"].iloc[-1])
    pivot = prev_close + 0.1
    live_price = pivot + 0.5
    result = ri.evaluate_breakout(history, live_price, live_volume=700_000,
                                  pivot=pivot, rs=80, elapsed_pct=0.5)
    assert result["direction_ok"] is True
    assert result["stage"] == 2
    assert result["alert"] is True


def test_direction_check_already_above_pivot_no_alert():
    """QMCO case: prev close was already above pivot before today, live price
    is further above — not a fresh cross, must not alert."""
    history = _uptrend()
    prev_close = float(history["close"].iloc[-1])
    pivot = prev_close - 10.0     # already cleared before today
    live_price = prev_close + 0.6
    result = ri.evaluate_breakout(history, live_price, live_volume=700_000,
                                  pivot=pivot, rs=80, elapsed_pct=0.5)
    assert result["direction_ok"] is False
    assert result["alert"] is False


def test_stale_pivot_already_run_past_no_alert():
    """52wk high and prev close both already 10%+ above the pivot — the base
    was broken long ago, this isn't a fresh breakout."""
    history = _uptrend()
    prev_close = float(history["close"].iloc[-1])
    pivot = prev_close / 1.20     # prev_close and 52wk high both > pivot*1.10
    live_price = prev_close + 1.0
    result = ri.evaluate_breakout(history, live_price, live_volume=700_000,
                                  pivot=pivot, rs=80, elapsed_pct=0.5)
    assert result["stale_pivot"] is True
    assert result["alert"] is False


def test_stage2_fail_close_below_200sma_no_alert():
    """Price crosses the pivot, but the underlying trend is a downtrend —
    close sits below its own 200SMA, so this is not a Stage 2 leader."""
    history = _downtrend()
    prev_close = float(history["close"].iloc[-1])
    pivot = prev_close + 0.1
    live_price = pivot + 0.2
    result = ri.evaluate_breakout(history, live_price, live_volume=700_000,
                                  pivot=pivot, rs=80, elapsed_pct=0.5)
    assert result["direction_ok"] is True   # crossed the pivot...
    assert result["stage"] != 2             # ...but not a Stage 2 leader
    assert result["alert"] is False


def _seed_price_history(con, ticker, n=252):
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = [50.0 + i * 0.4 for i in range(n)]
    df = pd.DataFrame({
        "open": closes, "high": closes, "low": closes,
        "close": closes, "volume": [1_000_000.0] * n,
    }, index=idx)
    db.upsert_prices(con, ticker, df)


def test_intraday_error_rate_alert_fires(tmp_path, monkeypatch):
    """10/20 tickers raising in get_live_quote should trip the >5% error-rate
    alert, while the 10 healthy tickers still get scanned (no exception
    propagates, no spurious alert since their live price stays below pivot)."""
    con = db.connect(tmp_path / "intraday_errors.db")
    tickers = [f"TST{i}" for i in range(20)]
    failing = set(tickers[:10])

    for t in tickers:
        _seed_price_history(con, t)
        con.execute(
            "INSERT INTO signals(ticker,asof,stage,tt,rs,pivot) VALUES(?,?,?,?,?,?)",
            (t, "2026-06-22", 2, 7, 80, 100.0))
    con.commit()

    def fake_get_live_quote(ticker):
        if ticker in failing:
            raise RuntimeError("simulated yfinance failure")
        return 101.0, 700_000.0   # below pivot(100)+prev_close(~150.4): no alert

    monkeypatch.setattr(ri, "_market_open", lambda: True)
    monkeypatch.setattr(ri, "get_live_quote", fake_get_live_quote)

    sent_msgs = []
    monkeypatch.setattr(alerter, "send_text", lambda text: sent_msgs.append(text))

    alerts = ri.run_scan(con)

    assert alerts == []
    assert len(sent_msgs) == 1
    assert "degraded" in sent_msgs[0]
    assert "10/20" in sent_msgs[0]
