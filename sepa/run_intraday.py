"""Intraday breakout scanner.

Re-evaluates every Stage-2/TT>=5 watchlist ticker from scratch: 252 days of
DB price history plus a single live yfinance quote, recomputing SMAs, Stage
2, and trend-template score rather than trusting yesterday's stored
classification. Fires only on a genuine breakout — price crossing the pivot
from below, with volume pace confirming, and the pivot not already stale
(price ran more than INTRADAY_STALE_PIVOT_RUN past it before today).

Does NOT update tier state in the DB — the nightly run is authoritative.
Run at 9:45 AM and 12:30 PM ET via the Task Scheduler XMLs in deploy/windows/.

Usage:
    python -m sepa.run_intraday
"""
import logging
from datetime import datetime, time as dtime
import pandas as pd
from . import config as C
from . import db
from . import alerter
from .indicators import add_mas, hi_lo_52w
from .screens import trend_template, classify_stage

log = logging.getLogger("sepa.intraday")

_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)
_SESSION_MINUTES = 390   # 9:30-16:00 ET = 390 minutes


def _now_et() -> datetime:
    """Current datetime in US/Eastern."""
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except (ImportError, KeyError):
        from datetime import timezone
        return datetime.now(timezone.utc).astimezone().replace(tzinfo=None)


def _market_open() -> bool:
    return _MARKET_OPEN <= _now_et().time() <= _MARKET_CLOSE


def _minutes_elapsed() -> int:
    """Minutes since 9:30 AM ET today (minimum 1)."""
    now = _now_et()
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return max(1, int((now - open_dt).total_seconds() / 60))


def load_watchlist(con) -> list[dict]:
    """Tickers from the most recent nightly run classified Stage 2, TT>=5,
    with a valid pivot — the universe eligible for an intraday breakout."""
    rows = con.execute(
        """SELECT ticker, pivot, stage, tt, rs FROM signals
           WHERE (ticker, asof) IN
                 (SELECT ticker, MAX(asof) FROM signals GROUP BY ticker)
             AND stage = 2 AND tt >= 5 AND pivot > 0
           ORDER BY ticker"""
    ).fetchall()
    return [{"ticker": t, "pivot": float(p), "stage": int(s), "tt": int(tt),
             "rs": int(rs) if rs is not None else 0}
            for t, p, s, tt, rs in rows]


def load_daily_history(con, ticker: str) -> pd.DataFrame:
    """Most recent 252 trading days of close/volume, oldest first — enough
    for a 200SMA without pulling full price history into memory."""
    return pd.read_sql_query(
        """SELECT date, close, volume FROM (
               SELECT date, close, volume FROM prices
               WHERE ticker=? ORDER BY date DESC LIMIT 252
           ) ORDER BY date ASC""",
        con, params=(ticker,), parse_dates=["date"]).set_index("date")


def get_live_quote(ticker: str) -> tuple[float, float]:
    """Today's live price and cumulative intraday volume so far — the one
    yfinance call the scanner needs."""
    import yfinance as yf
    bars = yf.Ticker(ticker).history(period="1d", interval="1m").dropna()
    if bars.empty:
        raise ValueError(f"no intraday bars for {ticker}")
    bars = bars.rename(columns=str.lower)
    live_price = float(bars["close"].iloc[-1])
    intraday_volume = float(bars["volume"].sum())
    return live_price, intraday_volume


def evaluate_breakout(history_df: pd.DataFrame, live_price: float,
                      live_volume: float, pivot: float, rs: int,
                      elapsed_pct: float) -> dict:
    """Decide, from scratch, whether this is a genuine breakout right now.

    Joins today's live price onto the 252-day history to recompute Stage 2
    and the trend-template score, then gates on direction (crossing the
    pivot from below, not having already run past it from above), pivot
    staleness, and volume pace before allowing an alert.
    """
    if len(history_df) < 200 or history_df["close"].isna().any():
        return {"alert": False, "reason": "insufficient history"}

    prev_close = float(history_df["close"].iloc[-1])
    avg_daily_vol = float(history_df["volume"].tail(50).mean())

    live_row = pd.DataFrame(
        {"close": [live_price], "volume": [live_volume]},
        index=[history_df.index[-1] + pd.Timedelta(days=1)])
    live_df = add_mas(pd.concat([history_df, live_row]))

    if live_df[["sma50", "sma150", "sma200"]].iloc[-1].isna().any():
        return {"alert": False, "reason": "insufficient history for 200sma"}

    tt_score, _checks = trend_template(live_df, rs)
    stage, _confidence = classify_stage(live_df, tt_score)
    hi_52w, _lo_52w = hi_lo_52w(live_df)

    stage2_ok = stage == 2
    tt_ok = tt_score >= 5
    direction_ok = prev_close < pivot <= live_price
    run_mult = 1 + C.INTRADAY_STALE_PIVOT_RUN
    stale_pivot = hi_52w > pivot * run_mult and prev_close > pivot * run_mult

    vol_pace = ((live_volume / max(elapsed_pct, 1e-6)) / avg_daily_vol
                if avg_daily_vol > 0 else 0.0)
    volume_ok = vol_pace >= C.BREAKOUT_VOL_MULT

    alert = stage2_ok and tt_ok and direction_ok and not stale_pivot and volume_ok
    reason = (f"stage{stage} TT{tt_score}/8 dir={'ok' if direction_ok else 'fail'} "
              f"stale={'yes' if stale_pivot else 'no'} vol={vol_pace:.2f}x")
    return {
        "alert": alert, "stage": stage, "tt_score": tt_score,
        "direction_ok": direction_ok, "stale_pivot": stale_pivot,
        "vol_pace": vol_pace, "volume_ok": volume_ok, "reason": reason,
    }


def run_scan(con=None) -> list[str]:
    """Scan the Stage-2/TT>=5 watchlist for genuine intraday breakouts."""
    if not _market_open():
        log.info("market closed — intraday scan skipped")
        print("market closed — intraday scan skipped")
        return []

    con = con or db.connect()
    watchlist = load_watchlist(con)
    if not watchlist:
        log.info("no Stage 2 / TT>=5 tickers — intraday skipped")
        return []

    log.info("intraday scan: %d watchlist tickers", len(watchlist))
    elapsed_pct = _minutes_elapsed() / _SESSION_MINUTES

    alerts_sent: list[str] = []
    error_count = 0
    error_messages: list[str] = []

    for row in watchlist:
        t, pivot, rs = row["ticker"], row["pivot"], row["rs"]
        try:
            history = load_daily_history(con, t)
            if history.empty:
                continue
            live_price, live_volume = get_live_quote(t)
            result = evaluate_breakout(history, live_price, live_volume,
                                       pivot, rs, elapsed_pct)
            if result["alert"]:
                msg = (f"📶 *{t}* breaking out intraday\n"
                       f"live `{live_price:.2f}` crossing pivot `{pivot:.2f}` — "
                       f"Stage {result['stage']} · TT {result['tt_score']}/8 · "
                       f"vol pace `{result['vol_pace']:.1f}×` avg")
                alerter.send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, msg)
                log.info("intraday alert %s: %s", t, result["reason"])
                alerts_sent.append(t)
        except Exception as e:
            error_count += 1
            error_messages.append(str(e))
            log.error("intraday %s: unhandled error", t, exc_info=True)

    log.info("intraday complete: %d alerts sent", len(alerts_sent))

    total = len(watchlist)
    error_rate = error_count / max(total, 1)
    if error_rate > C.INTRADAY_ERROR_RATE_THRESHOLD:
        from collections import Counter
        top_err = Counter(error_messages).most_common(1)[0][0] if error_messages else "unknown"
        msg = (f"⚠️ Intraday scan degraded: {error_count}/{total} tickers failed "
               f"({error_rate*100:.0f}%). Top error: {top_err[:120]}")
        log.critical(msg)
        alerter.send_text(msg)

    return alerts_sent


if __name__ == "__main__":
    from .log_config import setup_logging
    setup_logging(run_name="intraday")
    run_scan()
