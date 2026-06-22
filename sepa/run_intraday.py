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
import pandas as pd
from . import config as C
from . import db
from . import alerter

log = logging.getLogger("sepa.intraday")

_MARKET_OPEN = dtime(9, 30)
_MARKET_CLOSE = dtime(16, 0)
_SCAN_TIERS = {"Watch", "Buy Alert", "Potential Buy", "Momentum"}
_SESSION_MINUTES = 390   # 9:30–16:00 ET = 390 minutes

# Common corporate-suffix tokens stripped before name comparison
_CORP_SUFFIXES = {"inc", "corp", "ltd", "llc", "plc", "co", "group",
                  "holdings", "technologies", "technology", "international"}


def _names_match(db_name: str, yf_name: str) -> bool:
    """Return True if the significant tokens in both names overlap enough.

    Protects against ticker reassignment: when a company goes bankrupt and the
    ticker is later assigned to an unrelated company, yfinance will return
    price data but the company name will differ entirely from what is in our DB.
    """
    def tokens(s: str) -> set[str]:
        return {w.lower().rstrip(".,") for w in s.split()
                if w.lower().rstrip(".,") not in _CORP_SUFFIXES and len(w) > 1}

    db_tok = tokens(db_name)
    yf_tok = tokens(yf_name)
    if not db_tok or not yf_tok:
        return True  # can't compare, allow through
    return bool(db_tok & yf_tok)


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


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse yfinance's (Price, Ticker) MultiIndex columns to single-level.

    Some yfinance versions return MultiIndex columns even for a single-ticker
    download. Left unflattened, df["close"] is itself a one-column DataFrame
    rather than a Series, so df["close"].iloc[-1] yields a Series and any
    float() cast on it raises "not a real number, not 'Series'".
    """
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _last_close_and_volume(df5: pd.DataFrame) -> tuple[float, float]:
    """Extract (last close, total session volume) as scalars from a 5m bars df.

    Always returns plain floats, never a pandas Series — guards against
    yfinance returning MultiIndex columns for a single-ticker download.
    """
    df5 = _flatten_columns(df5).rename(columns=str.lower)
    last_close = float(df5["close"].iloc[-1])
    today_vol = float(df5["volume"].sum())
    return last_close, today_vol


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
    error_count = 0
    total_count = 0
    error_messages: list[str] = []

    for t in tickers:
        if t not in pivots:
            continue
        pivot = pivots[t]
        total_count += 1
        try:
            df5 = yf.download(t, period="1d", interval="5m", progress=False,
                              auto_adjust=True)
            if df5.empty:
                log.debug("no intraday data for %s", t)
                continue
            last_close, today_vol = _last_close_and_volume(df5)

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
                # Guard against ticker reassignment: verify yfinance still
                # returns the same company we ingested.  A mismatch means the
                # ticker was re-used after a delisting/bankruptcy.
                db_name_row = con.execute(
                    "SELECT name FROM securities WHERE ticker=?", (t,)
                ).fetchone()
                if db_name_row:
                    yf_info = yf.Ticker(t).info
                    yf_name = yf_info.get("longName") or yf_info.get("shortName") or ""
                    if yf_name and not _names_match(db_name_row[0], yf_name):
                        log.warning(
                            "intraday %s: name mismatch (DB=%r yfinance=%r) "
                            "— possible ticker reassignment, alert skipped",
                            t, db_name_row[0], yf_name)
                        continue

                msg = (f"📶 *{t}* crossing pivot intraday\n"
                       f"close `{last_close:.2f}` ≥ pivot `{pivot:.2f}` "
                       f"(+{pct_above:.1%}) — vol pace `{vol_ratio:.1f}×` avg")
                alerter.send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, msg)
                log.info("intraday alert %s: close=%.2f pivot=%.2f vol_ratio=%.2f",
                         t, last_close, pivot, vol_ratio)
                alerts_sent.append(t)
        except Exception as e:
            error_count += 1
            error_messages.append(str(e))
            log.error("intraday %s: unhandled error", t, exc_info=True)

    log.info("intraday complete: %d alerts sent", len(alerts_sent))

    error_rate = error_count / max(total_count, 1)
    if error_rate > C.INTRADAY_ERROR_RATE_THRESHOLD:
        from collections import Counter
        top_err = Counter(error_messages).most_common(1)[0][0] if error_messages else "unknown"
        msg = (f"⚠️ Intraday scan degraded: {error_count}/{total_count} tickers failed "
               f"({error_rate*100:.0f}%). Top error: {top_err[:120]}")
        log.critical(msg)
        alerter.send_text(msg)

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
