# SEPA Signals — US v1 (mini-PC, alert-first)

Always-on personal scanner. Nightly: ingest US data → Minervini multistage
filters → tiered watch list → Telegram alert with chart + reasoning when a
stock becomes **buyable**. No web UI in v1 — Telegram is the interface.

## Data sources (US, ToS-clean)
- Universe + CIK → SEC `company_tickers.json`
- Fundamentals → SEC EDGAR companyfacts API (official XBRL)
- Prices (OHLCV) → yfinance (free)

---

## Install on the mini PC (headless Linux)

```bash
# 1. Clone / copy the repo to /opt/sepa
sudo mkdir -p /opt/sepa
sudo chown $USER:$USER /opt/sepa
cp -r . /opt/sepa

# 2. Create a dedicated user (optional but recommended)
sudo useradd -r -s /usr/sbin/nologin -d /opt/sepa sepa
sudo chown -R sepa:sepa /opt/sepa

# 3. Build the virtualenv
cd /opt/sepa
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 4. Set credentials
cp deploy/.env.example .env
chmod 600 .env
nano .env    # fill in ANTHROPIC_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
```

## Configure (sepa/config.py)
```python
ACCOUNT_SIZE   = 100_000     # your account size ($)
RISK_PER_TRADE = 0.0125      # 1.25% per trade — adjust to your comfort
MARKET_TONE    = "Confirmed uptrend"   # flip to "Under pressure" or "Correction"
UNIVERSE_LIMIT = None        # None = all SEC tickers; set 500 for testing
```

The `SEC_USER_AGENT` is already set with your email. Do not change it —
SEC requires a real contact in the User-Agent.

## First live ingest (NEEDS-LIVE-VERIFY)
```bash
# Takes ~2-4 hours for the full universe (thousands of EDGAR calls, rate-limited)
# Start with a limit to verify data quality first:
cd /opt/sepa
.venv/bin/python -c "from sepa import db, ingest; con=db.connect(); ingest.ingest_us(con, limit=300)"

# Then run the scan on that initial universe:
.venv/bin/python -m sepa.run_daily
```

Verify 20 hand-picked names: compare prices and EPS/sales to TradingView / your
broker. They should match within rounding. If not, check EDGAR concept mapping
in `ingest.py` (`_EPS_CONCEPTS`, `_REV_CONCEPTS`).

## Install systemd timer (runs nightly)
```bash
# Copy unit files
sudo cp deploy/sepa-ingest.service  /etc/systemd/system/
sudo cp deploy/sepa-ingest.timer    /etc/systemd/system/
sudo cp deploy/sepa-daily.service   /etc/systemd/system/
sudo cp deploy/sepa-daily.timer     /etc/systemd/system/

# Edit the User= and WorkingDirectory= lines if you're not using /opt/sepa + sepa user
sudo nano /etc/systemd/system/sepa-daily.service

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now sepa-ingest.timer sepa-daily.timer

# Watch the next run
sudo journalctl -fu sepa-daily.service
```

Timer schedule (UTC — adjust OnCalendar in the timer files for your timezone):
- `sepa-ingest.timer` fires at 21:00 local (prices + fundamentals download)
- `sepa-daily.timer` fires at 22:00 local (scan + alerts)

## Log rotation
```bash
sudo cp deploy/logrotate.conf /etc/logrotate.d/sepa
```

Logs rotate daily, 14 days retained, compressed.

## Resumable runs
If a scan dies mid-way (power cut, OOM), the next run resumes from where it
stopped: tickers already classified are checkpointed in SQLite. Re-run the
same `sepa.run_daily` command; it will skip the done tickers and continue.

## Offline demo (no network — what is tested here)
```bash
make run   # seeds synthetic universe + runs the full pipeline
make test  # all 47+ unit tests (offline, no API calls)
```

Live integration tests (require ANTHROPIC_API_KEY, run on mini PC):
```bash
.venv/bin/python -m pytest -m live -v
```

## Setup summary (what each module does)
| Module | Role |
|---|---|
| `config.py` | All thresholds — edit here only |
| `db.py` | SQLite schema + all reads/writes + WAL |
| `ingest.py` | SEC + EDGAR + yfinance, with hygiene filters + retry |
| `providers.py` | DataProvider seam (Synthetic / DB) |
| `indicators.py` | MAs, 52w hi/lo, swing points, contractions |
| `screens.py` | Trend Template, stage, RS rank, fundamentals |
| `patterns.py` | VCP, Power Play, Cup-Handle, Cheat, Livermore PP |
| `classify.py` | 3-axis → tier; power-play bypass |
| `state.py` | Move-in/out diff (NEW/PROMOTED/DEMOTED/DROPPED) |
| `alerter.py` | Chart render + Telegram card + dedupe |
| `validator.py` | Phase 7 AI validator (Claude API — last step) |
| `run_daily.py` | Orchestrator — runs after market close |
| `log_config.py` | Rotating file log + heartbeat |

## v2 (later)
Broker API auto-execution — only after v1 paper period proves alerts are sane.
