# SEPA Signals Engine

A personal stock-signals platform that runs 24/7 on a mini PC and sends Telegram alerts when a stock becomes buyable under Mark Minervini's SEPA methodology.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  DATA INGESTION  (nightly, 9 pm local — sepa-ingest.timer)          │
│                                                                      │
│  SEC EDGAR JSON ──► Universe (~3,800 US stocks, ETF/shell filtered) │
│  yfinance       ──► 2yr OHLCV prices (200-ticker batches)           │
│  SEC EDGAR API  ──► Quarterly fundamentals (smart-cached: 7d normal │
│                     / 6h during earnings windows Jan/Feb Apr/May    │
│                     Jul/Aug Oct/Nov)                                 │
│                         │                                            │
│                         ▼                                            │
│                   SQLite (WAL mode)  ←── nightly VACUUM + checkpoint│
└─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  NIGHTLY SCAN  (10 pm local — sepa-daily.timer)                     │
│                                                                      │
│  L0 Hygiene ──── price > $10 · avg daily dollar-vol ≥ $1M           │
│       │                                                              │
│  L1 Indicators ─ SMA 10/21/50/150/200 · vol50 · up/dn vol ratio     │
│       │          (institutional sponsorship proxy)                   │
│       │                                                              │
│  L2 Stage ────── Weinstein Stage 1–4                                 │
│       │          (SMA slopes + price vs MAs)                         │
│       │                                                              │
│  L3 RS Rank ──── IBD-style: 40% most recent quarter                 │
│       │          + 20% × 3 prior quarters; percentile 1–99          │
│       │                                                              │
│  ◀── Market Breadth ── % universe in Stage 2                        │
│  │       ≥ 20%  →  Confirmed uptrend (full signals)                 │
│  │       ≥ 10%  →  Under pressure   (Buy Ready demoted)             │
│  │       <  10%  →  Correction       (no new buys)                  │
│  │   (manual MARKET_TONE= override available in .env)               │
│       │                                                              │
│  L4 Fundamentals ─ 8 checks (SEPA Accelerating Growth):             │
│       │   ✓ EPS positive (hard gate — loss-makers blocked)          │
│       │   ✓ EPS sequential acceleration (3 qtrs)                    │
│       │   ✓ EPS YoY ≥ 20%                                           │
│       │   ✓ Sales sequential acceleration                           │
│       │   ✓ Sales YoY ≥ 20%                                         │
│       │   ✓ Operating margin ≥ 10%                                  │
│       │   ✓ Expanding margins (vs 4 qtrs ago)                       │
│       │   ✓ ROE ≥ 17%                                               │
│       │   ✗ Revenue decline penalty (2+ consecutive QoQ drops → −1) │
│       │                                                              │
│  L5 Patterns ──── VCP / 3C  ·  Power Play (high tight flag)         │
│       │           Cup-with-Handle  ·  Cheat (A-B-C-D)               │
│       │           Livermore Pivot Point                              │
│       │                                                              │
│  L6 Tier ─────── Watch → Buy Alert → Buy Ready                      │
│       │          (3-axis: technical + fundamental + market tone)     │
│       │                                                              │
│  L7 AI Validator ─ Claude Haiku (bounded sanity check)              │
│       │             CONFIRM → alert fires                            │
│       │             CAUTION → alert fires + ⚠️ note                  │
│       │             REJECT  → alert suppressed                       │
│       │                                                              │
│  Telegram Alert ── annotated chart + position-sized card            │
│       │            entry · stop · 3:1 target · shares · R:R         │
│       │                                                              │
│  Stage Monitor ─── 2→3, 2→4, 3→4 transitions on owned/watched names│
│                    → immediate danger alert                          │
└─────────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│  WATCHLISTS  (stored in SQLite, diffs tracked nightly)              │
│                                                                      │
│  Watch       ── Stage 2 leaders, TT ≥ 5, RS ≥ 70; no setup yet     │
│  Buy Alert   ── Setup detected but not in buy zone / tape weak      │
│  Buy Ready   ── Breakout imminent, all 3 axes pass, AI confirmed    │
│  Positions   ── Manually entered after fill; stage monitor active   │
│  Reset Watch ── Stopped-out names rebuilding a new base             │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Alert card format

```
🟢 AAPL → BUY READY  (VCP / 3C)
_Software — Apple Inc_

Market:  Confirmed uptrend
Signal:  Stage 2 ✓ · TT 7/8 · RS 88 · Fund ✓ · vol ratio 1.42 ⬆
Setup:   footprint `13%→7%→T` · pivot taken out → in buy zone
Plan:    entry 178.50 · stop 168.20 (-5.8%) · target 209.40 (3:1 R:R)
         · size 122 sh @ 1.25% risk
AI:      ✅ AI CONFIRM: tight VCP with institutional accumulation confirmed

chart: tradingview.com/chart/?symbol=AAPL
```

---

## File layout

| file | role |
|---|---|
| `sepa/config.py` | all thresholds + .env loader (edit .env, not this file) |
| `sepa/providers.py` | data layer; `SyntheticProvider` for tests, `DBProvider` for prod |
| `sepa/ingest.py` | SEC + yfinance ingestion with retry, hygiene filter, fund cache |
| `sepa/db.py` | SQLite schema, all reads/writes, WAL mode, migration |
| `sepa/indicators.py` | MAs, 52w hi/lo, swing points, contractions, vol ratio |
| `sepa/screens.py` | Trend Template (8 criteria), stage classifier, RS rank, fundamentals (8 checks) |
| `sepa/patterns.py` | VCP, Power Play, Cup-Handle, Cheat, Livermore PP → `Setup` object |
| `sepa/classify.py` | 3-axis → tier; power-play extension bypass; market-tone gate |
| `sepa/state.py` | transition diff (NEW / PROMOTED / DEMOTED / DROPPED) |
| `sepa/alerter.py` | chart render, card builder, Telegram sender, deduplication |
| `sepa/validator.py` | Claude Haiku bounded validator (CONFIRM / CAUTION / REJECT) |
| `sepa/run_daily.py` | orchestrator; breadth gate; stage-transition monitor |
| `sepa/log_config.py` | rotating file log (7-day) + console handler |
| `deploy/windows/` | Windows Task Scheduler scripts (`install_tasks.ps1`, bat launchers) |
| `deploy/` | Linux systemd service + timer units, logrotate config |

---

## What runs when (London timezone)

| London | US Eastern | task | what it does |
|--------|-----------|------|--------------|
| 14:00 | 09:00 | `SEPA-PreMarket` | scan on yesterday's data — see what's buyable at the open |
| 21:30 | 16:30 | `SEPA-Ingest` | download today's settled prices + fundamentals |
| 22:00 | 17:00 | `SEPA-Daily` | full scan → Telegram alerts |
| nightly | (end of scan) | — | WAL checkpoint + VACUUM + checkpoint clear |

> **Why 21:30 for ingest?** US market closes at 16:00 ET. yfinance data settles
> within ~15 min. Pre-market earnings (released 07–08 ET) are baked into today's
> close. After-hours earnings show up in tomorrow's price action — no need to rush.

---

## Windows mini PC: first-time setup

> The mini PC runs Windows. Run through this once, then Task Scheduler
> handles the three daily runs automatically.

### 1. Prerequisites

- Python 3.11+ from [python.org](https://python.org) — tick **"Add to PATH"** during install
- Git from [git-scm.com](https://git-scm.com)

### 2. Clone and install

Open **Command Prompt** (not PowerShell):

```bat
git clone git@github.com:nirmal10110/sepa-signals.git C:\sepa-signals
cd C:\sepa-signals
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

### 3. Configure credentials

```bat
copy deploy\.env.example .env
notepad .env
```

Fill in these values:

| key | where to get it |
|-----|----------------|
| `ANTHROPIC_API_KEY` | console.anthropic.com → Settings → API Keys |
| `TELEGRAM_TOKEN` | @BotFather on Telegram |
| `TELEGRAM_CHAT_ID` | message your bot, then visit `api.telegram.org/bot<TOKEN>/getUpdates` |
| `ACCOUNT_SIZE` | your trading account size in USD |
| `RISK_PER_TRADE` | e.g. `0.0125` for 1.25% risk per trade |
| `UNIVERSE_LIMIT` | `3000` recommended |
| `MARKET_TONE` | leave blank — auto-computed from market breadth |

### 4. Run first ingest (seeds the database)

```bat
.venv\Scripts\python.exe -m sepa.ingest
```

Takes ~40–60 min for 3,000 stocks. Prices download first (~5 min), then
fundamentals from EDGAR (~35 min). Progress logs to `data\logs\ingest.log`.

### 5. Test Telegram

```bat
.venv\Scripts\python.exe -c "from sepa import alerter, config as C; alerter.send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, 'SEPA test ping')"
```

You should receive "SEPA test ping" on your phone within a few seconds.

### 6. Run first scan

```bat
.venv\Scripts\python.exe -m sepa.run_daily
```

Check the output — verify stage labels, breadth %, and tier counts look sane.
Open a few Buy Ready names in TradingView to spot-check the setups.

### 7. Install Task Scheduler tasks

Right-click **PowerShell** → **Run as Administrator**, then:

```powershell
cd C:\sepa-signals\deploy\windows
.\install_tasks.ps1
```

This registers three tasks:

| Task | Time (London) | What |
|------|--------------|------|
| `SEPA-PreMarket` | 14:00 | Morning signal review |
| `SEPA-Ingest` | 21:30 | Download today's prices |
| `SEPA-Daily` | 22:00 | Scan + Telegram alerts |

### 8. Verify tasks are registered

Open **Task Scheduler** (search in Start menu) → look for `SEPA-PreMarket`,
`SEPA-Ingest`, `SEPA-Daily` in the task list. Right-click any task → **Run**
to test it manually.

Logs appear in `C:\sepa-signals\data\logs\`.

### 9. Paper-trading period (4–8 weeks)

Log every alert you receive — entry price, setup type, RS, stop. Track
the outcome after 4–8 weeks. Only trust the signals after this period
confirms the alerts are sane and stage/footprint labels match the charts.

---

## Linux mini PC: first-time setup

> Everything below runs on the mini PC. Run through this once, then the
> systemd timers handle nightly automation.

### 1. Prerequisites

```bash
sudo apt install python3 python3-venv git sqlite3
```

### 2. Clone and install

```bash
git clone git@github.com:nirmal10110/sepa-signals.git
cd sepa-signals
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Configure credentials

```bash
cp .env.example .env
chmod 600 .env
nano .env          # fill in ANTHROPIC_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
```

Key settings to verify in `.env`:
- `ANTHROPIC_API_KEY` — from console.anthropic.com/settings/keys
- `TELEGRAM_TOKEN` — from @BotFather on Telegram
- `TELEGRAM_CHAT_ID` — send a message to your bot, then check getUpdates
- `ACCOUNT_SIZE` — your trading account size in USD
- `RISK_PER_TRADE` — e.g. `0.0125` for 1.25% per trade
- `MARKET_TONE` — leave blank for auto-computation from breadth

### 4. Run first ingest (live data)

```bash
.venv/bin/python -m sepa.ingest    # takes ~15–30 min for full universe
```

### 5. Validate data quality (Phase 2 gate)

```bash
.venv/bin/python -m sepa.run_daily
```

Check printed output — open ~20 names you know in TradingView and verify:
- Stage labels match the chart visually
- Footprints on VCPs look like real contractions
- RS percentiles feel right for the names you know

### 6. Test Telegram

```bash
.venv/bin/python -c "from sepa import alerter, config as C; alerter.send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, 'SEPA test ping')"
```

### 7. Install systemd services

```bash
sudo cp deploy/sepa-daily.service deploy/sepa-daily.timer \
        deploy/sepa-ingest.service deploy/sepa-ingest.timer \
        /etc/systemd/system/
sudo cp deploy/logrotate.conf /etc/logrotate.d/sepa

# Update WorkingDirectory= in each .service file to point at your clone path
sudo nano /etc/systemd/system/sepa-daily.service

sudo systemctl daemon-reload
sudo systemctl enable sepa-ingest.timer sepa-daily.timer
sudo systemctl start  sepa-ingest.timer sepa-daily.timer
```

### 8. Check it's running

```bash
systemctl status sepa-daily.timer
journalctl -u sepa-daily.service -f     # live log tail
```

### 9. Paper-trading period (4–8 weeks)

Log every alert you receive. Note: entry price, setup type, RS, fundamentals.
Track outcome after 4–8 weeks. Only proceed to trust the signals after this
period shows alerts are sane and stage/footprint labels match reality.

---

## Testing

```bash
# offline (no network — runs in ~10s)
.venv/bin/python -m pytest -q

# live (run on the mini PC — needs real credentials)
.venv/bin/python -m pytest -m live -q
```

All unit tests use the `SyntheticProvider` — a fixed seed universe that always
produces the same tier assignments. Any change that silently moves a name between
tiers will fail the golden test in `tests/test_engine.py`.

---

## What "done" means

- [x] Phase 0 — project structure, SQLite schema, provider seam
- [x] Phase 1 — SEC + yfinance ingest with retry, hygiene, fund caching
- [x] Phase 3 — indicators, screens (TT + stage + RS + fundamentals)
- [x] Phase 4 — pattern detectors (VCP, Power Play, Cup-Handle, Cheat, LPP)
- [x] Phase 5 — 3-axis tier decision + diff engine + watchlist state
- [x] Phase 6 — Telegram alerter + chart render + deduplication
- [x] Phase 7 — Claude Haiku AI validator (CONFIRM / CAUTION / REJECT)
- [x] Breadth gate — auto market tone from % universe in Stage 2
- [x] systemd deploy units + logrotate
- [ ] **NEEDS-LIVE-VERIFY** — Phase 2 mini PC data quality spot-check (20 names)
- [ ] **NEEDS-LIVE-VERIFY** — Phase 4 Telegram gate (receive a real alert)
- [ ] **NEEDS-LIVE-VERIFY** — Phase 6 scale test (full universe, timing OK)
- [ ] **NEEDS-LIVE-VERIFY** — Phase 7 live API validation (real Claude call)
- [ ] **4–8 week paper period** — log all alerts, verify sanity before trusting
