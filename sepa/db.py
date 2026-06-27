"""SQLite layer. Single file on the mini PC; zero config; the whole system's
memory lives here."""
import sqlite3
import pandas as pd
from . import config as C

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS securities(
  ticker TEXT PRIMARY KEY, name TEXT, exchange TEXT, sector TEXT,
  cik TEXT, active INTEGER DEFAULT 1, added_at TEXT,
  fund_fetched_at TEXT, hygiene_excluded INTEGER DEFAULT 0);

CREATE TABLE IF NOT EXISTS prices(
  ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY(ticker, date));

CREATE TABLE IF NOT EXISTS fundamentals(
  ticker TEXT, period_end TEXT, eps REAL, sales REAL, op_margin REAL, roe REAL,
  PRIMARY KEY(ticker, period_end));

CREATE TABLE IF NOT EXISTS signals(
  ticker TEXT, asof TEXT, stage INTEGER, tt INTEGER, rs INTEGER, funda INTEGER,
  setup TEXT, footprint TEXT, pivot REAL, entry REAL, stop REAL, buyable INTEGER,
  tier TEXT, reason TEXT, ext_200 REAL, climax_risk INTEGER,
  gain_52wk_pct REAL, funda_improving INTEGER, funda_trend_label TEXT,
  PRIMARY KEY(ticker, asof));

CREATE TABLE IF NOT EXISTS watchlist_state(
  ticker TEXT PRIMARY KEY, tier TEXT, added TEXT, updated TEXT);

CREATE TABLE IF NOT EXISTS transitions(
  asof TEXT, ticker TEXT, status TEXT, from_tier TEXT, to_tier TEXT);

CREATE TABLE IF NOT EXISTS alerts(
  dedupe_key TEXT PRIMARY KEY, ticker TEXT, asof TEXT, setup TEXT,
  pivot REAL, sent_at TEXT);

-- Positions: manually entered after a fill. The engine populates
-- follow-through / squat status; the user enters fill_price and shares.
CREATE TABLE IF NOT EXISTS positions(
  ticker TEXT PRIMARY KEY,
  fill_date TEXT,          -- date of entry fill
  fill_price REAL,         -- actual fill price
  shares REAL,
  stop_ref REAL,           -- initial stop from the signal; user can tighten
  pivot REAL,              -- pivot the name broke out of
  setup TEXT,
  status TEXT DEFAULT 'open',   -- open | follow_through | squat | closed
  close_date TEXT,
  close_price REAL,
  notes TEXT,
  added_at TEXT DEFAULT (date('now')));

-- Reset Watch: tickers to re-watch after being stopped out.
-- When a stopped name forms a new base that resets, it re-enters Watch.
CREATE TABLE IF NOT EXISTS reset_watch(
  ticker TEXT PRIMARY KEY,
  stopped_date TEXT,
  stopped_price REAL,
  original_pivot REAL,
  reset_type TEXT,   -- 'base_reset' | 'pivot_reset'
  notes TEXT,
  added_at TEXT DEFAULT (date('now')));

-- Stage-transition events (e.g. owned name moves 2→3 = danger alert)
CREATE TABLE IF NOT EXISTS stage_transitions(
  asof TEXT, ticker TEXT, from_stage INTEGER, to_stage INTEGER,
  source_list TEXT,   -- 'positions' | 'watchlist_state'
  alerted INTEGER DEFAULT 0);

-- Resumable run checkpoint: tracks which tickers have been classified this run.
-- If a run is killed mid-way, the next run skips already-done tickers.
CREATE TABLE IF NOT EXISTS run_checkpoint(
  asof TEXT, ticker TEXT, PRIMARY KEY(asof, ticker));
"""


def _migrate(con):
    """Add columns introduced after initial release without dropping existing data."""
    try:
        con.execute("ALTER TABLE securities ADD COLUMN fund_fetched_at TEXT")
    except Exception:
        pass  # column already exists
    try:
        con.execute("ALTER TABLE securities ADD COLUMN hygiene_excluded INTEGER DEFAULT 0")
    except Exception:
        pass
    for col in ("ai_verdict", "ai_note", "ai_summary", "ai_thesis", "ai_catalysts"):
        try:
            con.execute(f"ALTER TABLE signals ADD COLUMN {col} TEXT")
        except Exception:
            pass
    try:
        con.execute("ALTER TABLE signals ADD COLUMN ext_200 REAL")
    except Exception:
        pass
    try:
        con.execute("ALTER TABLE signals ADD COLUMN climax_risk INTEGER")
    except Exception:
        pass
    for col, decl in (("gain_52wk_pct", "REAL"), ("funda_improving", "INTEGER"),
                      ("funda_trend_label", "TEXT")):
        try:
            con.execute(f"ALTER TABLE signals ADD COLUMN {col} {decl}")
        except Exception:
            pass
    try:
        con.execute("ALTER TABLE securities ADD COLUMN yfinance_fail_streak INTEGER DEFAULT 0")
    except Exception:
        pass


def connect(path=None):
    path = path or C.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def vacuum(con):
    """Periodic maintenance — call after a full scan."""
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("VACUUM")


# ---- writes ----
def upsert_security(con, ticker, name, exchange, sector, cik=None):
    con.execute("""INSERT INTO securities(ticker,name,exchange,sector,cik,added_at)
        VALUES(?,?,?,?,?,date('now'))
        ON CONFLICT(ticker) DO UPDATE SET name=excluded.name,
        exchange=excluded.exchange, sector=excluded.sector, cik=excluded.cik""",
        (ticker, name, exchange, sector, cik))


def set_hygiene_excluded(con, ticker, excluded: bool):
    """Mark whether a ticker's real price data fails the hygiene filter
    (penny stock / illiquid). Excluded tickers are intentionally never
    given a price row, so they must not be reported as stale; this flag
    is what lets get_stale_tickers() tell that apart from a genuine gap.
    Self-heals: cleared whenever the ticker next loads real prices, in
    case its price/volume later qualifies."""
    con.execute("UPDATE securities SET hygiene_excluded=? WHERE ticker=?",
                (1 if excluded else 0, ticker))


def reset_fail_streaks(con, tickers: list):
    """Zero out yfinance_fail_streak for tickers that loaded successfully."""
    if not tickers:
        return
    con.executemany("UPDATE securities SET yfinance_fail_streak=0 WHERE ticker=?",
                    [(t,) for t in tickers])


def increment_fail_streaks(con, tickers: list):
    """Bump yfinance_fail_streak by 1 for tickers that failed to load."""
    if not tickers:
        return
    con.executemany(
        "UPDATE securities SET yfinance_fail_streak=yfinance_fail_streak+1 WHERE ticker=?",
        [(t,) for t in tickers])


def deactivate_stale_streaks(con, threshold: int) -> list:
    """Set active=0 for securities whose fail streak has reached threshold.
    Returns the tickers newly deactivated (active was 1 before this call)."""
    rows = con.execute(
        "SELECT ticker FROM securities WHERE yfinance_fail_streak>=? AND active=1",
        (threshold,)).fetchall()
    deactivated = [r[0] for r in rows]
    if deactivated:
        con.execute(
            "UPDATE securities SET active=0 WHERE yfinance_fail_streak>=? AND active=1",
            (threshold,))
    return deactivated


def upsert_prices(con, ticker, df):
    rows = [(ticker, d.strftime("%Y-%m-%d"), float(r.open), float(r.high),
             float(r.low), float(r.close), float(r.volume))
            for d, r in df.iterrows()]
    con.executemany("""INSERT INTO prices(ticker,date,open,high,low,close,volume)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(ticker,date) DO UPDATE SET
        close=excluded.close, volume=excluded.volume""", rows)


def upsert_fundamental(con, ticker, period_end, eps, sales, op_margin, roe):
    con.execute("""INSERT INTO fundamentals(ticker,period_end,eps,sales,op_margin,roe)
        VALUES(?,?,?,?,?,?) ON CONFLICT(ticker,period_end) DO UPDATE SET
        eps=excluded.eps, sales=excluded.sales, op_margin=excluded.op_margin,
        roe=excluded.roe""", (ticker, period_end, eps, sales, op_margin, roe))


def write_signal(con, asof, s):
    con.execute("""INSERT INTO signals(ticker,asof,stage,tt,rs,funda,setup,footprint,
        pivot,entry,stop,buyable,tier,reason,ext_200,climax_risk,
        gain_52wk_pct,funda_improving,funda_trend_label)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker,asof) DO UPDATE SET stage=excluded.stage,
        tt=excluded.tt, rs=excluded.rs, funda=excluded.funda, setup=excluded.setup,
        footprint=excluded.footprint, pivot=excluded.pivot, entry=excluded.entry,
        stop=excluded.stop, buyable=excluded.buyable, tier=excluded.tier,
        reason=excluded.reason, ext_200=excluded.ext_200,
        climax_risk=excluded.climax_risk, gain_52wk_pct=excluded.gain_52wk_pct,
        funda_improving=excluded.funda_improving,
        funda_trend_label=excluded.funda_trend_label""",
        (s["ticker"], asof, int(s["stage"]), int(s["tt"]), int(s["rs"]), int(s["funda"]),
         s["setup"], s["footprint"], float(s["pivot"]), float(s["entry"]),
         float(s["stop"]), int(s["buyable"]), s["tier"], s["reason"],
         float(s.get("ext_200") or 0), int(bool(s.get("climax_risk"))),
         s.get("gain_52wk_pct"), int(bool(s.get("funda_improving"))),
         s.get("funda_trend_label") or ""))


def set_state(con, ticker, tier, added, asof):
    con.execute("""INSERT INTO watchlist_state(ticker,tier,added,updated)
        VALUES(?,?,?,?) ON CONFLICT(ticker) DO UPDATE SET tier=excluded.tier,
        updated=excluded.updated""", (ticker, tier, added, asof))


def clear_state(con, tickers):
    con.executemany("DELETE FROM watchlist_state WHERE ticker=?",
                    [(t,) for t in tickers])


def log_transition(con, asof, ticker, status, frm, to):
    con.execute("INSERT INTO transitions VALUES(?,?,?,?,?)",
                (asof, ticker, status, frm, to))


def alert_seen(con, key):
    return con.execute("SELECT 1 FROM alerts WHERE dedupe_key=?", (key,)).fetchone() is not None


def log_alert(con, key, ticker, asof, setup, pivot):
    con.execute("INSERT OR IGNORE INTO alerts VALUES(?,?,?,?,?,datetime('now'))",
                (key, ticker, asof, setup, pivot))


def update_signal_ai(con, ticker, asof, verdict, note, summary, thesis, catalysts):
    """Persist AI validator output back to the signals row for the daily report."""
    con.execute(
        """UPDATE signals SET ai_verdict=?, ai_note=?, ai_summary=?,
           ai_thesis=?, ai_catalysts=? WHERE ticker=? AND asof=?""",
        (verdict, note, summary, thesis, catalysts, ticker, asof)
    )


# ---- positions ----
def open_position(con, ticker, fill_date, fill_price, shares, stop_ref, pivot, setup):
    con.execute("""INSERT INTO positions
        (ticker,fill_date,fill_price,shares,stop_ref,pivot,setup,status,added_at)
        VALUES(?,?,?,?,?,?,?,'open',date('now'))
        ON CONFLICT(ticker) DO UPDATE SET
        fill_date=excluded.fill_date, fill_price=excluded.fill_price,
        shares=excluded.shares, stop_ref=excluded.stop_ref,
        pivot=excluded.pivot, setup=excluded.setup, status='open',
        close_date=NULL, close_price=NULL""",
        (ticker, fill_date, fill_price, shares, stop_ref, pivot, setup))


def update_position_status(con, ticker, status, notes=None):
    con.execute("UPDATE positions SET status=?, notes=? WHERE ticker=?",
                (status, notes, ticker))


def close_position(con, ticker, close_date, close_price):
    con.execute("""UPDATE positions SET status='closed',
        close_date=?, close_price=? WHERE ticker=?""",
        (close_date, close_price, ticker))


def get_positions(con):
    """Return list of open positions as dicts."""
    rows = con.execute("""SELECT ticker,fill_date,fill_price,shares,stop_ref,
        pivot,setup,status,notes FROM positions WHERE status != 'closed'""").fetchall()
    keys = ["ticker", "fill_date", "fill_price", "shares", "stop_ref",
            "pivot", "setup", "status", "notes"]
    return [dict(zip(keys, r)) for r in rows]


# ---- reset watch ----
def add_reset_watch(con, ticker, stopped_date, stopped_price, original_pivot,
                    reset_type="base_reset", notes=None):
    con.execute("""INSERT INTO reset_watch
        (ticker,stopped_date,stopped_price,original_pivot,reset_type,notes,added_at)
        VALUES(?,?,?,?,?,?,date('now'))
        ON CONFLICT(ticker) DO UPDATE SET stopped_date=excluded.stopped_date,
        stopped_price=excluded.stopped_price, original_pivot=excluded.original_pivot,
        reset_type=excluded.reset_type, notes=excluded.notes""",
        (ticker, stopped_date, stopped_price, original_pivot, reset_type, notes))


def remove_reset_watch(con, ticker):
    con.execute("DELETE FROM reset_watch WHERE ticker=?", (ticker,))


def get_reset_watch(con):
    rows = con.execute("""SELECT ticker,stopped_date,stopped_price,
        original_pivot,reset_type FROM reset_watch""").fetchall()
    keys = ["ticker", "stopped_date", "stopped_price", "original_pivot", "reset_type"]
    return [dict(zip(keys, r)) for r in rows]


# ---- stage transitions ----
def log_stage_transition(con, asof, ticker, from_stage, to_stage, source_list):
    con.execute("""INSERT INTO stage_transitions VALUES(?,?,?,?,?,0)""",
                (asof, ticker, from_stage, to_stage, source_list))


def mark_stage_transition_alerted(con, asof, ticker):
    con.execute("""UPDATE stage_transitions SET alerted=1
        WHERE asof=? AND ticker=?""", (asof, ticker))


# ---- run checkpoint (resumability) ----
def checkpoint_done(con, asof, ticker):
    """Mark a ticker as fully processed for today's run."""
    con.execute("INSERT OR IGNORE INTO run_checkpoint VALUES(?,?)", (asof, ticker))


def checkpoint_get(con, asof) -> set:
    """Return the set of tickers already processed in today's run."""
    rows = con.execute("SELECT ticker FROM run_checkpoint WHERE asof=?", (asof,)).fetchall()
    return {r[0] for r in rows}


def checkpoint_clear(con, asof):
    """Remove checkpoint after a successful run so tomorrow starts clean."""
    con.execute("DELETE FROM run_checkpoint WHERE asof=?", (asof,))


# ---- reads (the engine consumes these) ----
def universe(con):
    return [r[0] for r in con.execute(
        "SELECT ticker FROM securities WHERE active=1").fetchall()]


def get_history(con, ticker):
    df = pd.read_sql_query(
        "SELECT date,open,high,low,close,volume FROM prices WHERE ticker=? ORDER BY date",
        con, params=(ticker,), parse_dates=["date"]).set_index("date")
    return df


def get_fundamentals(con, ticker):
    df = pd.read_sql_query(
        "SELECT * FROM fundamentals WHERE ticker=? ORDER BY period_end", con,
        params=(ticker,))
    if df.empty:
        return {"eps": [], "sales": [], "op_margin": 0, "op_margins": [], "roe": 0}
    tail8 = df.tail(8)
    return {
        "eps":        tail8["eps"].tolist(),          # up to 8 quarters, oldest first
        "sales":      tail8["sales"].tolist(),
        "op_margin":  float(tail8["op_margin"].iloc[-1]),   # most recent (backward compat)
        "op_margins": tail8["op_margin"].tolist(),    # list for trend detection
        "roe":        float(tail8["roe"].iloc[-1]),
    }


def mark_fundamentals_fetched(con, ticker):
    """Record the UTC timestamp when EDGAR was last successfully fetched."""
    con.execute("UPDATE securities SET fund_fetched_at=datetime('now') WHERE ticker=?",
                (ticker,))


def get_price_latest_dates(con, tickers: list) -> dict:
    """Return {ticker: "YYYY-MM-DD"} for the most recent stored price date.
    Tickers with no stored data are omitted from the result."""
    if not tickers:
        return {}
    placeholders = ",".join("?" * len(tickers))
    rows = con.execute(
        f"SELECT ticker, MAX(date) FROM prices WHERE ticker IN ({placeholders}) GROUP BY ticker",
        tickers,
    ).fetchall()
    return {t: d for t, d in rows if d}


def get_stale_tickers(con, max_age_days: int) -> list:
    """Return [(ticker, last_date)] for active securities whose newest stored
    price is older than max_age_days, or that have no price data at all
    (last_date is None in that case).

    Securities flagged hygiene_excluded are skipped: their price data is
    intentionally never stored (penny stock / illiquid per hygiene_filter),
    so they would otherwise show up as permanently "stale" every run and
    drown out real feed problems."""
    rows = con.execute(
        """SELECT s.ticker, p.last_date
           FROM securities s
           LEFT JOIN (
               SELECT ticker, MAX(date) AS last_date FROM prices GROUP BY ticker
           ) p ON s.ticker = p.ticker
           WHERE s.active = 1
             AND COALESCE(s.hygiene_excluded, 0) = 0
             AND (p.last_date IS NULL OR p.last_date < date('now', ?))
           ORDER BY s.ticker""",
        (f"-{max_age_days} days",),
    ).fetchall()
    return rows


def get_fundamentals_fetched_at(con, ticker) -> str | None:
    """Return the ISO datetime string when fundamentals were last fetched, or None."""
    row = con.execute("SELECT fund_fetched_at FROM securities WHERE ticker=?",
                      (ticker,)).fetchone()
    return row[0] if row else None


def get_meta(con, ticker):
    r = con.execute("SELECT name,exchange,sector FROM securities WHERE ticker=?",
                    (ticker,)).fetchone()
    if not r:
        return {"name": ticker, "exchange": "US", "sector": "—", "summary": ""}
    sector = r[2] if r[2] and r[2] != "—" else ""
    summary = f"{sector} — {r[0]}" if sector else r[0]
    return {"name": r[0], "exchange": r[1], "sector": r[2], "summary": summary}


def prev_state(con):
    return {t: {"tier": tier, "added": added} for t, tier, added in
            con.execute("SELECT ticker,tier,added FROM watchlist_state").fetchall()}


def prev_stages(con):
    """Return {ticker: stage} from the most recent signal for each ticker."""
    rows = con.execute("""SELECT ticker, stage FROM signals
        WHERE (ticker, asof) IN
        (SELECT ticker, MAX(asof) FROM signals GROUP BY ticker)""").fetchall()
    return {t: s for t, s in rows}
