"""Central configuration. Every tunable threshold lives here."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
STATE_PATH = DATA_DIR / "state.json"
WORKBOOK_PATH = DATA_DIR / "SEPA_Watchlist.xlsx"

# --- account / risk (mirrors the Dashboard) ---
ACCOUNT_SIZE = 100_000
RISK_PER_TRADE = 0.0125          # 1.25%
BUY_ZONE_WIDTH = 0.05            # price is "buyable" within 5% of pivot

# --- market tone gate (third axis). Set from your market-health gauge. ---
# one of: "Confirmed uptrend", "Under pressure", "Correction"
MARKET_TONE = "Confirmed uptrend"

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
CUP_MIN_BARS = 35                  # ~7 weeks minimum cup
CUP_MAX_BARS = 260                 # ~52 weeks maximum base
CUP_MIN_DEPTH = 0.12               # cup corrects at least 12%
CUP_MAX_DEPTH = 0.35               # cup corrects no more than 35%
CUP_RIM_TOLERANCE = 0.05           # right rim within 5% of left rim
CUP_HANDLE_MAX_DEPTH = 0.12        # handle corrects <= 12%

# --- Cheat (4-phase A-B-C-D)  VERIFY-AGAINST-BOOK ---
CHEAT_MIN_BARS = 40
CHEAT_LOOKBACK = 120               # look back this many bars for the pattern
CHEAT_B_RECOUP_MIN = 0.33          # B uptrend recoupes >= 33% of A decline
CHEAT_B_RECOUP_MAX = 0.60          # B recoupes no more than 60% (full recoup = not a cheat)
CHEAT_PLATEAU_MIN = 0.03           # C plateau depth at least 3%
CHEAT_PLATEAU_MAX = 0.12           # C plateau depth no more than 12%
CHEAT_LOW_ENTRY_ZONE = 0.03        # "low-cheat" if price within 3% of plateau low

# --- Livermore Pivot Point  VERIFY-AGAINST-BOOK ---
LPP_MIN_BARS = 40
LPP_LOOKBACK = 120
LPP_MIN_PRIOR_DECLINE = 0.15       # prior downtrend must be >= 15%

TIER_ORDER = ["Watch", "Buy Alert", "Buy Ready"]

# --- storage / ops (mini-PC) ---
DB_PATH = DATA_DIR / "sepa.db"
CHART_DIR = DATA_DIR / "charts"

# --- L0 hygiene filters ---
HYGIENE_MIN_PRICE = 10.0         # minimum last close price ($)
HYGIENE_MIN_DOLLAR_VOL = 1_000_000  # minimum avg daily dollar-volume

# --- US ingestion ---
SEC_USER_AGENT = "SEPA personal scanner lather10110@gmail.com"  # SEC requires real UA + contact
UNIVERSE_LIMIT = None        # cap number of tickers (for testing); None = all
PRICE_LOOKBACK = "2y"        # yfinance history window

# --- Telegram alerts ---
TELEGRAM_TOKEN = ""          # from @BotFather
TELEGRAM_CHAT_ID = ""        # your chat id

# --- AI validator (Phase 7) ---
# Set via environment or fill in here. The validator falls back to CAUTION if absent.
import os as _os
ANTHROPIC_API_KEY = _os.environ.get("ANTHROPIC_API_KEY", "")
