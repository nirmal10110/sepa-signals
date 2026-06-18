"""Intraday breakout scanner.

Pulls 5-minute bars for tickers currently in Watch, Buy Alert, or Potential Buy.
Fires a lightweight Telegram alert when a ticker crosses above its pivot with
volume pace ≥ BREAKOUT_VOL_MULT × the 50-day daily average.

Volume pace = today's cumulative 5m volume × (390 / minutes_elapsed_since_930).
This extrapolates the partial-session volume to a full-day run rate.

Does NOT update tier state in the DB — the nightly run is authoritative.
Run at 9:45 AM and 12:30 PM ET via the Task Scheduler XMLs in deploy/windows/.

Usage:
    python -m sepa.run_intraday
    python -m sepa.run_intraday --mode intraday
"""
import argparse
import logging
from datetime import datetime, time as dtime
from . import config as C
from . import db
from . import alerter

log = logging.getLogger("sepa.intraday")

_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)
_SCAN_TIERS = {"Watch", "Buy Alert", "Potential Buy"}
_SESSION_MINUTES = 390   # 9:30–16:00 ET = 390 minutes


def _now_et() -> datetime:
    """Current datetime in US/Eastern."""
    try:
        import zoneinfo
        return datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except (ImportError, KeyError):
        from datetime import timezone, timedelta
        return datetime.now(timezone.utc).astimezone().replace(tzinfo=None)


def _market_open() -> bool:
    return _MARKET_OPEN <= _now_et().time() <= _MARKET_CLOSE


def _minutes_elapsed() -> int:
    """Minutes since 9:30 AM ET today (minimum 1)."""
    now = _now_et()
    open_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
    return max(1, int((now - open_dt).total_seconds() / 60))


def run_intraday(con=None) -> list[str]:
    """Scan for intraday breakouts; return list of alerted tickers."""
    if not _market_open():
        log.info("market closed — intraday scan skipped")
        print("market closed — intraday scan skipped")
        return []

    con = con or db.connect()
    state = db.prev_state(con)
    tickers = [t for t, info in state.items() if info["tier"] in _SCAN_TIERS]

    if not tickers:
        log.info("no tickers in scan tiers — intraday skipped")
        return []

    log.info("intraday scan: %d tickers in %s", len(tickers), sorted(_SCAN_TIERS))

    # Latest pivot price per ticker (from most recent signals row)
    pivots: dict[str, float] = {}
    for t in tickers:
        row = con.execute(
            "SELECT pivot FROM signals WHERE ticker=? ORDER BY asof DESC LIMIT 1",
            (t,)).fetchone()
        if row and row[0] and float(row[0]) > 0:
            pivots[t] = float(row[0])

    try:
        import yfinance as yf
    except ImportError:
        log.error("yfinance not installed — intraday scan aborted")
        return []

    minutes = _minutes_elapsed()
    alerts_sent: list[str] = []

    for t in tickers:
        if t not in pivots:
            continue
        pivot = pivots[t]
        try:
            df5 = yf.download(t, period="1d", interval="5m", progress=False,
                              auto_adjust=True)
            if df5.empty:
                log.debug("no intraday data for %s", t)
                continue
            df5 = df5.rename(columns=str.lower)
            last_close = float(df5["close"].iloc[-1])
            today_vol = float(df5["volume"].sum())

            # Annualise partial-session volume to full-day pace
            vol_pace = today_vol * (_SESSION_MINUTES / minutes)

            # 50-day avg daily volume from the DB price history
            hist = db.get_history(con, t)
            if len(hist) < 10:
                continue
            n = min(50, len(hist))
            avg_vol_50 = float(hist["volume"].iloc[-n:].mean())
            if avg_vol_50 <= 0:
                continue

            vol_ratio = vol_pace / avg_vol_50

            # Only alert when price is at or just above the pivot (within BUY_ZONE_WIDTH).
            # Without the upper bound every stock that broke out months ago would
            # re-fire every intraday scan — the pivot stored in DB is not updated
            # unless a new nightly scan re-evaluates the base.
            pct_above = (last_close - pivot) / pivot
            near_pivot = 0 <= pct_above <= C.BUY_ZONE_WIDTH

            if near_pivot and vol_ratio >= C.BREAKOUT_VOL_MULT:
                msg = (f"📶 *{t}* crossing pivot intraday\n"
                       f"close `{last_close:.2f}` ≥ pivot `{pivot:.2f}` "
                       f"(+{pct_above:.1%}) — vol pace `{vol_ratio:.1f}×` avg")
                alerter.send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, msg)
                log.info("intraday alert %s: close=%.2f pivot=%.2f vol_ratio=%.2f",
                         t, last_close, pivot, vol_ratio)
                alerts_sent.append(t)
        except Exception as e:
            log.warning("intraday %s: %s", t, e)

    log.info("intraday complete: %d alerts sent", len(alerts_sent))
    return alerts_sent


if __name__ == "__main__":
    from .log_config import setup_logging
    setup_logging(run_name="intraday")
    parser = argparse.ArgumentParser(description="SEPA intraday breakout scanner")
    parser.add_argument("--mode", default="intraday",
                        help="scan mode (only 'intraday' currently supported)")
    args = parser.parse_args()
    if args.mode == "intraday":
        run_intraday()
