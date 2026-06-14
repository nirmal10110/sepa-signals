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
  fund_fetched_at TEXT);

CREATE TABLE IF NOT EXISTS prices(
  ticker TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY(ticker, date));

CREATE TABLE IF NOT EXISTS fundamentals(
  ticker TEXT, period_end TEXT, eps REAL, sales REAL, op_margin REAL, roe REAL,
  PRIMARY KEY(ticker, period_end));

CREATE TABLE IF NOT EXISTS signals(
  ticker TEXT, asof TEXT, stage INTEGER, tt INTEGER, rs INTEGER, funda INTEGER,
  setup TEXT, footprint TEXT, pivot REAL, entry REAL, stop REAL, buyable INTEGER,
  tier TEXT, reason TEXT, PRIMARY KEY(ticker, asof));

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
    con.execute("""INSERT INTO signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker,asof) DO UPDATE SET stage=excluded.stage,
        tt=excluded.tt, rs=excluded.rs, funda=excluded.funda, setup=excluded.setup,
        footprint=excluded.footprint, pivot=excluded.pivot, entry=excluded.entry,
        stop=excluded.stop, buyable=excluded.buyable, tier=excluded.tier,
        reason=excluded.reason""",
        (s["ticker"], asof, s["stage"], s["tt"], s["rs"], s["funda"], s["setup"],
         s["footprint"], s["pivot"], s["entry"], s["stop"], int(s["buyable"]),
         s["tier"], s["reason"]))


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
