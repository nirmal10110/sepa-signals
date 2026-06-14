"""US data ingestion for the mini PC.

Real sources (ToS-clean, meant to be pulled from):
  • Universe + CIK : SEC company_tickers.json
  • Fundamentals   : SEC EDGAR companyfacts API (official XBRL financials)
  • Prices (OHLCV) : yfinance (free)

Network paths are marked NEEDS-LIVE-VERIFY — run on the mini PC and confirm.
"""
import logging
import time
import random
import pandas as pd
from . import config as C
from . import db
from .providers import SyntheticProvider

log = logging.getLogger("sepa.ingest")

# Months when quarterly 10-Q/10-K filings are actively landing on EDGAR.
# Re-fetch fundamentals more aggressively (every 6h) during these windows.
_EARNINGS_MONTHS = frozenset({1, 2, 4, 5, 7, 8, 10, 11})

SEC_TICKERS = "https://www.sec.gov/files/company_tickers.json"
EDGAR_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# SIC codes that identify ETFs, closed-end funds, and blank-check shells
_ETF_SIC = {6726}  # Investment offices, NEC (covers most ETFs)
# Name fragments that flag ETFs / funds when SIC is unavailable
_ETF_NAME_TOKENS = frozenset([
    "etf", "fund", "trust", "ishares", "spdr", "invesco", "proshares",
    "direxion", "vaneck", "wisdomtree", "portfolio", "index", "ultra",
])

# Minimum average daily dollar-volume (~$1M) for liquidity gate
MIN_DOLLAR_VOLUME = 1_000_000


# ---------------------------------------------------------------- retry helper
def _retry(fn, *, retries=3, backoff=2.0, jitter=0.3):
    """Call fn(); on exception retry with exponential + jitter backoff."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt == retries - 1:
                raise
            sleep = backoff ** attempt + random.uniform(0, jitter)
            log.warning("retry %d/%d after %.1fs: %s", attempt + 1, retries, sleep, e)
            time.sleep(sleep)


# ---------------------------------------------------------------- hygiene filters
def _is_etf_or_shell(ticker: str, name: str, sic: int | None) -> bool:
    """Return True if the security looks like an ETF, fund, or shell."""
    if sic in _ETF_SIC:
        return True
    lower = name.lower()
    return any(tok in lower.split() for tok in _ETF_NAME_TOKENS)


def hygiene_filter(df: pd.DataFrame) -> pd.DataFrame:
    """L0 filter applied to a price DataFrame just fetched.

    Keeps rows only if:
      - last close > $10
      - average daily dollar-volume (close × volume) ≥ MIN_DOLLAR_VOLUME
    Returns an empty DataFrame if the stock fails.
    """
    if df.empty:
        return df
    last_close = float(df["close"].iloc[-1])
    if last_close <= C.HYGIENE_MIN_PRICE:
        return pd.DataFrame()
    avg_dv = float((df["close"] * df["volume"]).mean())
    if avg_dv < C.HYGIENE_MIN_DOLLAR_VOL:
        return pd.DataFrame()
    return df


# ---------------------------------------------------------------- universe
def fetch_us_universe(limit=None):
    """Return [(ticker, name, cik)] from SEC. Covers all US-listed issuers."""
    import requests
    r = _retry(lambda: requests.get(
        SEC_TICKERS, headers={"User-Agent": C.SEC_USER_AGENT}, timeout=30))
    r.raise_for_status()
    rows = []
    for d in r.json().values():
        ticker = d["ticker"].upper()
        name = d["title"]
        cik = int(d["cik_str"])
        if not _is_etf_or_shell(ticker, name, None):
            rows.append((ticker, name, cik))
    return rows[:limit] if limit else rows


def load_universe(con, rows):
    for ticker, name, cik in rows:
        db.upsert_security(con, ticker, name, "US", "—", cik=str(cik))
    con.commit()


# ---------------------------------------------------------------- prices
def load_prices(con, tickers, period=None):
    """Batch-download prices via yfinance; apply hygiene filter; upsert."""
    import yfinance as yf
    period = period or C.PRICE_LOOKBACK
    loaded = skipped = failed = 0
    batches = list(range(0, len(tickers), 100))   # 100-ticker batches (safer for yfinance)
    for batch_num, i in enumerate(batches):
        batch = tickers[i:i + 100]
        try:
            data = _retry(lambda: yf.download(
                batch, period=period, interval="1d",
                auto_adjust=True, group_by="ticker",
                progress=False, threads=False))    # threads=False reduces burst load
        except Exception as e:
            log.error("batch download failed (tickers %d-%d): %s", i, i + len(batch), e)
            failed += len(batch)
            time.sleep(5)   # back off after a batch error
            continue
        for t in batch:
            try:
                df = data[t] if len(batch) > 1 else data
                df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
                df = hygiene_filter(df)
                if df.empty:
                    skipped += 1
                    continue
                db.upsert_prices(con, t, df)
                loaded += 1
            except Exception as e:
                log.warning("price load failed %s: %s", t, e)
                failed += 1
        con.commit()
        log.info("prices batch %d/%d: loaded=%d skipped=%d failed=%d",
                 batch_num + 1, len(batches), loaded, skipped, failed)
        if batch_num < len(batches) - 1:
            time.sleep(3)   # 3s between batches — stays well under Yahoo rate limits
    log.info("prices total: loaded=%d skipped=%d failed=%d", loaded, skipped, failed)


# ---------------------------------------------------------------- fundamentals
# XBRL concept candidates in priority order — filers use different names
_EPS_CONCEPTS = [
    "EarningsPerShareDiluted",
    "EarningsPerShareBasic",
]
_REV_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
]
_OP_CONCEPTS = [
    "OperatingIncomeLoss",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
]
_NI_CONCEPTS = [
    "NetIncomeLoss",
    "ProfitLoss",
]
_EQ_CONCEPTS = [
    "StockholdersEquity",
    "StockholdersEquityAttributableToParent",
]


def _quarterly(facts, concepts):
    """Try each concept in order; return quarterly (end, val) pairs, newest last."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in concepts:
        if concept not in gaap:
            continue
        try:
            units = gaap[concept]["units"]
            series = units.get("USD") or units.get("USD/shares") or next(iter(units.values()))
            q = [(x["end"], x["val"]) for x in series
                 if x.get("form") in ("10-Q", "10-K") and x.get("fp")]
            seen, out = set(), []
            for end, val in sorted(q):
                if end not in seen:
                    seen.add(end)
                    out.append((end, val))
            if out:
                return out
        except (KeyError, StopIteration):
            continue
    return []


def _fundamentals_fresh(con, ticker) -> bool:
    """Return True if cached fundamentals are recent enough to skip EDGAR."""
    import datetime
    fetched_at = db.get_fundamentals_fetched_at(con, ticker)
    if not fetched_at:
        return False
    age_h = (datetime.datetime.utcnow() -
              datetime.datetime.fromisoformat(fetched_at)).total_seconds() / 3600
    month = datetime.datetime.utcnow().month
    max_h = (C.FUND_CACHE_DAYS_EARNINGS * 24 if month in _EARNINGS_MONTHS
             else C.FUND_CACHE_DAYS_NORMAL * 24)
    return age_h < max_h


def load_fundamentals(con, ticker, cik):
    """Map EDGAR companyfacts -> the engine's fundamentals schema."""
    if _fundamentals_fresh(con, ticker):
        log.debug("fundamentals fresh, skipping EDGAR for %s", ticker)
        return
    import requests
    url = EDGAR_FACTS.format(cik=int(cik))
    try:
        r = _retry(lambda: requests.get(
            url, headers={"User-Agent": C.SEC_USER_AGENT}, timeout=30))
    except Exception as e:
        log.warning("EDGAR fetch failed %s (CIK %s): %s", ticker, cik, e)
        return
    if r.status_code == 404:
        log.debug("no EDGAR data for %s", ticker)
        return
    if r.status_code != 200:
        log.warning("EDGAR %s status %d", ticker, r.status_code)
        return
    facts = r.json()
    eps = _quarterly(facts, _EPS_CONCEPTS)
    rev = _quarterly(facts, _REV_CONCEPTS)
    opinc = _quarterly(facts, _OP_CONCEPTS)
    ni = _quarterly(facts, _NI_CONCEPTS)
    eq = _quarterly(facts, _EQ_CONCEPTS)
    rev_d, op_d, ni_d, eq_d = (dict(rev), dict(opinc), dict(ni), dict(eq))
    rows_written = 0
    for end, eps_v in eps[-8:]:
        sales_v = rev_d.get(end, 0)
        op_margin = (op_d.get(end, 0) / sales_v) if sales_v else 0
        roe = (ni_d.get(end, 0) / eq_d.get(end, 1)) if eq_d.get(end) else 0
        db.upsert_fundamental(con, ticker, end, eps_v, sales_v, op_margin, roe)
        rows_written += 1
    if rows_written:
        db.mark_fundamentals_fetched(con, ticker)
        con.commit()


def ingest_us(con, limit=None, with_fundamentals=True):
    """Full nightly ingest. Run on the mini PC. NEEDS-LIVE-VERIFY."""
    rows = fetch_us_universe(limit or C.UNIVERSE_LIMIT)
    load_universe(con, rows)
    tickers = [t for t, *_ in rows]
    log.info("universe: %d US tickers (after ETF/shell filter)", len(tickers))
    load_prices(con, tickers)
    if with_fundamentals:
        for i, (t, _, cik) in enumerate(rows):
            load_fundamentals(con, t, cik)
            time.sleep(0.12)     # SEC courtesy rate-limit ≤10 req/s
            if i % 100 == 0:
                log.info("fundamentals: %d/%d done", i, len(rows))
    log.info("ingest complete")


# ---------------------------------------------------------------- offline demo
def seed_synthetic(con):
    """Populate the DB from the synthetic provider so the pipeline can run
    without network. Mirrors what real ingest would write."""
    p = SyntheticProvider()
    for t in p.universe():
        m = p.meta(t)
        db.upsert_security(con, t, m["name"], m["exchange"], m["sector"])
        db.upsert_prices(con, t, p.history(t))
        f = p.fundamentals(t)
        for i, (eps, sales) in enumerate(zip(f["eps"], f["sales"])):
            db.upsert_fundamental(con, t, f"2025-Q{i+1}", eps, sales,
                                  f["op_margin"], f["roe"])
    con.commit()
    print(f"seeded {len(p.universe())} synthetic US tickers")


if __name__ == "__main__":
    from .log_config import setup_logging
    setup_logging()
    con = db.connect()
    ingest_us(con)
