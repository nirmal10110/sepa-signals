"""Central configuration.

User-facing settings (credentials, account, market tone) are loaded from a
.env file at the project root. All algorithm thresholds stay in this file.

Priority: .env file > environment variable > hardcoded default.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"
WORKBOOK_PATH = DATA_DIR / "SEPA_Watchlist.xlsx"


# ---------------------------------------------------------------------------
# .env loader — no external dependency required
# ---------------------------------------------------------------------------
def _load_env(path: Path) -> None:
    """Parse a .env file and inject into os.environ (does not overwrite)."""
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_env(ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _getfloat(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def _getint(key: str, default) -> int | None:
    val = os.environ.get(key)
    if val is None:
        return default
    val = val.strip()
    if val.lower() in ("none", ""):
        return None
    try:
        return int(val)
    except ValueError:
        return default


# ===========================================================================
# USER-FACING SETTINGS  (set these in .env — see .env.example)
# ===========================================================================

# --- credentials ---
ANTHROPIC_API_KEY  = _get("ANTHROPIC_API_KEY")
TELEGRAM_TOKEN     = _get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID   = _get("TELEGRAM_CHAT_ID")

# --- AI validator ---
VALIDATOR_MODEL    = _get("VALIDATOR_MODEL", "claude-haiku-4-5-20251001")
# Max stocks validated per night. Candidates are sorted by RS first; extras
# still fire as alerts but without the AI Company/Thesis/Catalysts block.
VALIDATOR_MAX_CALLS = _getint("VALIDATOR_MAX_CALLS", 10)

# --- account / risk ---
ACCOUNT_SIZE       = _getfloat("ACCOUNT_SIZE",    100_000)
RISK_PER_TRADE     = _getfloat("RISK_PER_TRADE",  0.0125)   # 1.25% per trade

# --- market tone gate (third axis) ---
# Empty = auto-computed from breadth (recommended).
# Set to override: "Confirmed uptrend" | "Under pressure" | "Correction"
MARKET_TONE_OVERRIDE = _get("MARKET_TONE", "")

# Breadth thresholds: % of universe in Stage 2 that maps to each tone.
BREADTH_BULL_THRESHOLD    = _getfloat("BREADTH_BULL_THRESHOLD",    0.20)  # ≥20% → Confirmed
BREADTH_NEUTRAL_THRESHOLD = _getfloat("BREADTH_NEUTRAL_THRESHOLD", 0.10)  # ≥10% → Under pressure

# --- universe ---
SEC_USER_AGENT     = _get("SEC_USER_AGENT",
                           "SEPA personal scanner lather10110@gmail.com")
UNIVERSE_LIMIT     = _getint("UNIVERSE_LIMIT", None)   # None = all SEC tickers
PRICE_LOOKBACK     = _get("PRICE_LOOKBACK", "2y")

# --- fundamental caching (skip EDGAR re-fetch when data is fresh) ---
# Outside earnings windows: re-fetch after 7 days. During earnings months
# (Jan/Feb, Apr/May, Jul/Aug, Oct/Nov): re-fetch after 6 hours.
FUND_CACHE_DAYS_NORMAL   = _getfloat("FUND_CACHE_DAYS_NORMAL",   7.0)
FUND_CACHE_DAYS_EARNINGS = _getfloat("FUND_CACHE_DAYS_EARNINGS", 0.25)  # 6 h


# ===========================================================================
# ALGORITHM THRESHOLDS  (tune in .env after Phase 2 calibration)
# ===========================================================================

BUY_ZONE_WIDTH = 0.05            # price is "buyable" within 5% of pivot
MAX_STOP_PCT   = _getfloat("MAX_STOP_PCT", 0.08)  # hard cap: stop never > 8% below entry

# --- Climax run detection ---
# A Power Play on top of an already >200% 1-year gain is a potential climax
# (late-stage blow-off, not a first-base breakout). Flagged in the card + AI prompt.
CLIMAX_RET_1Y_MIN = _getfloat("CLIMAX_RET_1Y_MIN", 2.0)   # 200% = 3× from prior year

# --- Fundamentals (SEPA: Accelerating Growth) ---
FUND_EPS_GROWTH_MIN  = _getfloat("FUND_EPS_GROWTH_MIN",  0.20)  # EPS YoY >= 20%
FUND_SALES_GROWTH_MIN= _getfloat("FUND_SALES_GROWTH_MIN",0.20)  # Sales YoY >= 20%
FUND_OP_MARGIN_MIN   = _getfloat("FUND_OP_MARGIN_MIN",   0.10)  # op margin floor 10%
FUND_ROE_MIN         = _getfloat("FUND_ROE_MIN",          0.17)  # ROE >= 17%
FUND_MIN_SCORE       = int(_getfloat("FUND_MIN_SCORE",    3))    # checks to pass (out of 7)

# --- Trend Template / RS ---
RS_MIN = 70                      # min RS percentile to qualify
PCT_ABOVE_52W_LOW = 0.30         # >= 30% above 52w low
PCT_BELOW_52W_HIGH = 0.25        # within 25% of 52w high
SMA200_RISING_LOOKBACK = 21      # ~1 month

# --- VCP ---
VCP_BASE_MAX_DAYS = 65           # look back this far for the base
VCP_MIN_CONTRACTIONS = 2
VCP_FINAL_TIGHTNESS = 0.10       # last contraction depth ceiling
VCP_VOL_DRYUP = 0.85             # last-leg avg vol must be < 85% of base avg

# --- Power Play (high tight flag) ---
PP_THRUST_PCT = 1.00             # +100% ...
PP_THRUST_DAYS = 40              # ... in < ~8 weeks
PP_FLAG_MAX_DEPTH = 0.25         # flag corrects no more than 20-25%
PP_FLAG_MIN_DAYS = 10
PP_FLAG_MAX_DAYS = 30
PP_DORMANCY_VOL = 0.06           # pre-thrust realized vol ceiling (dormant)

# --- Cup-with-Handle ---
CUP_MIN_BARS = 35                # ~7 weeks minimum cup
CUP_MAX_BARS = 260               # ~52 weeks maximum base
CUP_MIN_DEPTH = 0.12             # cup corrects at least 12%
CUP_MAX_DEPTH = 0.35             # cup corrects no more than 35%
CUP_RIM_TOLERANCE = 0.05         # right rim within 5% of left rim
CUP_HANDLE_MAX_DEPTH = 0.12      # handle corrects <= 12%

# --- Cheat (4-phase A-B-C-D)  VERIFY-AGAINST-BOOK ---
CHEAT_MIN_BARS = 40
CHEAT_LOOKBACK = 120
CHEAT_B_RECOUP_MIN = 0.33        # B uptrend recoups >= 33% of A decline
CHEAT_B_RECOUP_MAX = 0.60        # B recoups no more than 60%
CHEAT_PLATEAU_MIN = 0.03         # C plateau depth at least 3%
CHEAT_PLATEAU_MAX = 0.12         # C plateau depth no more than 12%
CHEAT_LOW_ENTRY_ZONE = 0.03      # "low-cheat" if within 3% of plateau low

# --- Livermore Pivot Point  VERIFY-AGAINST-BOOK ---
LPP_MIN_BARS = 40
LPP_LOOKBACK = 120
LPP_MIN_PRIOR_DECLINE = 0.15     # prior downtrend must be >= 15%

TIER_ORDER = ["Watch", "Buy Alert", "Buy Ready"]

# --- storage / ops (mini-PC) ---
DB_PATH = DATA_DIR / "sepa.db"
CHART_DIR = DATA_DIR / "charts"

# --- L0 hygiene filters ---
HYGIENE_MIN_PRICE = 10.0
HYGIENE_MIN_DOLLAR_VOL = 1_000_000
