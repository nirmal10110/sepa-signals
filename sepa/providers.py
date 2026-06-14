"""Data layer. Swap SyntheticProvider for a real one (yfinance/EODHD) — that's
the ONLY seam you must implement for production. Everything downstream is real."""
from abc import ABC, abstractmethod
import numpy as np
import pandas as pd


class DataProvider(ABC):
    @abstractmethod
    def universe(self) -> list[str]: ...
    @abstractmethod
    def history(self, ticker: str) -> pd.DataFrame:
        """Return daily OHLCV indexed by date, oldest first.
        Columns: open, high, low, close, volume."""
    @abstractmethod
    def fundamentals(self, ticker: str) -> dict:
        """Return latest quarterly fundamentals."""
    def meta(self, ticker: str) -> dict:
        return {"name": ticker, "exchange": "US", "sector": "—",
                "summary": ""}


# ----------------------------------------------------------------------------
# SYNTHETIC PROVIDER — generates ~300 sessions with deliberately planted setups
# so the whole pipeline can be demonstrated without a live feed.
# ----------------------------------------------------------------------------
def _series(closes, vols, start="2025-01-01"):
    idx = pd.bdate_range(start=start, periods=len(closes))
    closes = np.asarray(closes, float)
    high = closes * (1 + np.random.uniform(0.002, 0.02, len(closes)))
    low = closes * (1 - np.random.uniform(0.002, 0.02, len(closes)))
    openp = (high + low) / 2
    return pd.DataFrame({"open": openp, "high": high, "low": low,
                         "close": closes, "volume": vols}, index=idx)


def _walk(n, drift, vol, start_price):
    r = np.random.normal(drift, vol, n)
    return start_price * np.exp(np.cumsum(r))


def _gen(archetype, seed):
    np.random.seed(seed)
    base_vol = np.random.randint(800_000, 1_500_000)

    if archetype == "stage2_vcp":
        up = _walk(230, 0.004, 0.018, 10)            # strong stage-2 advance
        peak = up[-1]
        # VCP: 3 shrinking contractions ending tight near highs
        legs, vols, p = [], [], peak
        for depth, length, vmul in [(0.13, 16, 1.3), (0.07, 12, 1.0), (0.035, 10, 0.6)]:
            down = np.linspace(p, p * (1 - depth), length // 2)
            back = np.linspace(p * (1 - depth), p * 0.995, length - length // 2)
            seg = np.concatenate([down, back]); legs.append(seg)
            vols += [base_vol * vmul] * len(seg); p = seg[-1]
        closes = np.concatenate([up] + legs)
        vols = list(base_vol * (1 + np.random.uniform(0, .4, len(up)))) + vols

    elif archetype == "power_play":
        dorm = _walk(210, 0.0005, 0.006, 8)          # dormancy
        thrust = np.linspace(dorm[-1], dorm[-1] * 2.15, 32)   # +115% explosive
        fp = thrust[-1]
        flag = np.concatenate([np.linspace(fp, fp * 0.90, 9),
                               np.linspace(fp * 0.90, fp * 0.985, 9)])  # tight flag
        closes = np.concatenate([dorm, thrust, flag])
        vols = (list(base_vol * (1 + np.random.uniform(0, .2, len(dorm)))) +
                list(base_vol * np.random.uniform(3, 6, len(thrust))) +     # huge vol
                list(base_vol * np.linspace(1.2, 0.4, len(flag))))          # dry-up

    elif archetype == "vcp_forming":
        up = _walk(230, 0.004, 0.018, 10)
        peak = up[-1]
        legs, vols, p = [], [], peak
        for depth, length, vmul in [(0.12, 16, 1.3), (0.07, 12, 0.7)]:
            down = np.linspace(p, p * (1 - depth), length // 2)
            back = np.linspace(p * (1 - depth), p * 0.955, length - length // 2)
            seg = np.concatenate([down, back]); legs.append(seg)
            vols += [base_vol * vmul] * len(seg); p = seg[-1]
        # end mid-base ~9% under the pivot -> setup present but NOT buyable
        tail = np.linspace(p, peak * 0.91, 6); legs.append(tail)
        vols += [base_vol * 0.6] * len(tail)
        closes = np.concatenate([up] + legs)
        vols = list(base_vol * (1 + np.random.uniform(0, .4, len(up)))) + vols

    elif archetype == "stage2_extended":
        closes = _walk(280, 0.005, 0.02, 12)         # strong but no tight base
        vols = base_vol * (1 + np.random.uniform(0, .5, len(closes)))

    elif archetype == "stage1_flat":
        closes = _walk(280, 0.0, 0.008, 20)          # sideways
        vols = base_vol * (1 + np.random.uniform(0, .3, len(closes)))

    else:  # stage4_decline
        closes = _walk(280, -0.004, 0.02, 50)
        vols = base_vol * (1 + np.random.uniform(0, .6, len(closes)))

    return _series(closes, np.asarray(vols, float))


_FUNDA = {
    "good":   dict(eps=[0.10, 0.18, 0.31, 0.52], sales=[100, 118, 140, 171],
                   op_margin=0.19, roe=0.24, surprise=0.12),
    "ok":     dict(eps=[0.20, 0.22, 0.23, 0.25], sales=[100, 104, 107, 110],
                   op_margin=0.12, roe=0.15, surprise=0.01),
    "weak":   dict(eps=[0.40, 0.31, 0.22, 0.10], sales=[100, 96, 91, 88],
                   op_margin=0.04, roe=0.06, surprise=-0.20),
}

# (ticker, archetype, fundamentals, name, sector)
_UNIVERSE = [
    ("AAVCP", "stage2_vcp",      "good", "Apex Velocity Corp",      "Software"),
    ("BBVCP", "stage2_vcp",      "good", "Bluefin Biotech",         "Biotech"),
    ("CCVCP", "stage2_vcp",      "ok",   "Crest Capital Goods",     "Industrials"),
    ("DDPOW", "power_play",      "good", "Delta Dynamics",          "Semis"),
    ("EEPOW", "power_play",      "ok",   "Echo Energy",             "Energy"),
    ("LLFRM", "vcp_forming",     "good", "Lumen Forming",           "Software"),
    ("MMFRM", "vcp_forming",     "good", "Meridian Materials",      "Materials"),
    ("FFEXT", "stage2_extended", "good", "Fortis Extended",         "Retail"),
    ("GGEXT", "stage2_extended", "good", "Granite Growth",          "Consumer"),
    ("NNEXT", "stage2_extended", "ok",   "Nimbus Networks",         "Telecom"),
    ("HHFLAT", "stage1_flat",    "ok",   "Harbor Holdings",         "Utilities"),
    ("IIFLAT", "stage1_flat",    "good", "Ionic Industries",        "Materials"),
    ("JJDEC", "stage4_decline",  "weak", "Junction Decliners",      "Telecom"),
    ("KKDEC", "stage4_decline",  "weak", "Kettle Corp",             "Media"),
    ("P1DEC", "stage4_decline",  "weak", "Palisade Mining",         "Mining"),
    ("P2DEC", "stage4_decline",  "ok",   "Quill Pharma",            "Pharma"),
    ("P3FLAT", "stage1_flat",    "weak", "Rincon Realty",           "REIT"),
    ("P4FLAT", "stage1_flat",    "ok",   "Solace Foods",            "Staples"),
    ("P5DEC", "stage4_decline",  "weak", "Tundra Air",              "Airlines"),
    ("P6DEC", "stage4_decline",  "weak", "Umbra Steel",             "Steel"),
]


class SyntheticProvider(DataProvider):
    def __init__(self):
        self._arch = {t: a for t, a, *_ in _UNIVERSE}
        self._fun = {t: f for t, _, f, *_ in _UNIVERSE}
        self._meta = {t: (n, s) for t, _, _, n, s in _UNIVERSE}

    def universe(self):
        return [t for t, *_ in _UNIVERSE]

    def history(self, ticker):
        import hashlib
        seed = int(hashlib.md5(ticker.encode()).hexdigest(), 16) % (2**31)
        return _gen(self._arch[ticker], seed)

    def fundamentals(self, ticker):
        return _FUNDA[self._fun[ticker]]

    def meta(self, ticker):
        name, sector = self._meta[ticker]
        return {"name": name, "exchange": "US", "sector": sector,
                "summary": f"{sector} name — synthetic demo data"}


# ----------------------------------------------------------------------------
# REAL PROVIDER STUBS — implement these to go live. Schema must match above.
# ----------------------------------------------------------------------------
class YFinanceProvider(DataProvider):
    """pip install yfinance. Free, global-ish, fine for a first live run."""
    def __init__(self, tickers):
        self._tickers = tickers
    def universe(self):
        return self._tickers
    def history(self, ticker):
        import yfinance as yf
        df = yf.download(ticker, period="2y", interval="1d", progress=False, auto_adjust=True)
        df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]]
        return df.dropna()
    def fundamentals(self, ticker):
        # Map yfinance .quarterly_income_stmt / .info into the dict schema above.
        raise NotImplementedError("Wire yfinance fundamentals here")


class EODHDProvider(DataProvider):
    """Recommended for global EOD + fundamentals (~$80/mo All-World)."""
    def __init__(self, api_key, tickers):
        self.api_key, self._tickers = api_key, tickers
    def universe(self):
        return self._tickers
    def history(self, ticker):
        raise NotImplementedError("GET /api/eod/{ticker}?api_token=... -> OHLCV df")
    def fundamentals(self, ticker):
        raise NotImplementedError("GET /api/fundamentals/{ticker} -> map to schema")


class DBProvider(DataProvider):
    """Reads from the SQLite store populated by ingest.py. This is what the
    engine uses in production."""
    def __init__(self, con):
        from . import db
        self._db = db
        self.con = con
    def universe(self):
        return self._db.universe(self.con)
    def history(self, ticker):
        return self._db.get_history(self.con, ticker)
    def fundamentals(self, ticker):
        return self._db.get_fundamentals(self.con, ticker)
    def meta(self, ticker):
        return self._db.get_meta(self.con, ticker)
