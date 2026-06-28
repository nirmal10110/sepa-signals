# Commercialisation Roadmap

Things to fix/build before selling SEPA Signals to other people.
Work through these top-to-bottom — each section is roughly ordered by priority.

---

## 🔴 Hard Blockers — must fix before taking any money

### 1. Switch data provider (yfinance → licensed source)
yfinance scrapes Yahoo Finance. Yahoo's ToS explicitly prohibits commercial
redistribution of derived data. The moment you charge money for signals, you're
in violation.

**Options:**
- Polygon.io — ~$29/mo, clean REST API, easy drop-in for OHLCV
- Tiingo — ~$10/mo, good for EOD data
- EOD Historical Data — covers international markets too

**What to do:**
- Replace `sepa/ingest.py` price download with a licensed provider client
- Keep the same `load_prices(con, tickers)` interface so nothing else changes
- [ ] TODO: pick provider, implement, test

---

### 2. Complete paper trading validation (3 months minimum)
You can't sell signals you haven't validated. Buyers will ask "what's your win
rate?" The honest answer right now is "unknown."

**What to do:**
- Log every Buy Ready signal + entry price automatically to a `paper_trades` table
- After 20 trading days, log the outcome (price at day 20, max gain, hit stop?)
- Run for at least 3 months before selling
- [ ] TODO: add `paper_trades` table and auto-logging in `run_daily.py`
- [ ] TODO: run 3-month paper period (target: start YYYY-MM-DD, end YYYY-MM-DD)

---

### 3. Add exit signals
You tell buyers when to buy. You don't tell them when to sell. Minervini has
explicit sell rules — without them, buyers will hold losers too long.

**Exit rules to encode:**
- Hard stop hit (already calculated, just needs alerting when price < stop)
- 8-week hold rule: if no meaningful gain after 8 weeks, exit
- Moving average violation: close below 10-week MA after a confirmed uptrend
- Distribution: 4+ distribution days in 2 weeks on the major indices
- Climax top signals: gap-up exhaustion, heaviest-volume reversal day

**What to do:**
- Add a `run_positions.py` or extend `run_daily.py` to check open positions daily
- Alert via Telegram when an exit condition triggers
- [ ] TODO: implement stop-hit detection against daily close
- [ ] TODO: implement 10-week MA violation alert for positions
- [ ] TODO: implement 8-week hold rule alert

---

### 4. Legal: disclaimer + Terms of Service
Every signal card needs a footer: "Not investment advice. For educational
purposes only. Past performance is not indicative of future results."
You need Terms of Service before taking any payment.

**What to do:**
- Add disclaimer footer to every Telegram card and HTML email
- Draft a one-page Terms of Service (consult a lawyer before launch)
- [ ] TODO: add disclaimer to `build_card()` in `alerter.py`
- [ ] TODO: add disclaimer to HTML email footer in `reporter.py`
- [ ] TODO: draft ToS

---

## 🟡 Important Gaps — will lose customers quickly without these

### 5. Multi-tenancy
Everything is hardcoded to one Telegram chat ID, one SQLite DB, one `.env`.
Selling to a second user means running a completely separate copy. That's not
a product — it's a custom install job.

**Two options — pick one:**

**Option A: Hosted SaaS** (you run it, users subscribe via web)
- One backend, one DB per user (or multi-tenant schema), one Telegram bot per user
- Users sign up on a website, connect their Telegram, choose settings
- You handle the infrastructure, they just receive alerts
- Higher build cost, recurring revenue model, scales well

**Option B: Software licence** (they run it on their own machine)
- Package as a one-click Windows installer (NSIS, Inno Setup, or PyInstaller exe)
- GUI config screen (tkinter or a simple web UI via Flask on localhost)
- User enters their own Telegram token, Anthropic key, account size
- Lower build cost, one-time sale or annual licence, harder to update

- [ ] TODO: decide on Option A vs B before building anything else here

---

### 6. Performance dashboard
Buyers need to see: how many signals fired, which worked, win rate, average
gain/loss, open positions vs outcomes. A Telegram card is the alert — buyers
also need a way to review history.

**Options:**
- HTML email daily summary (already partially built in `reporter.py`) — extend it
  to include a "recent signal outcomes" section
- Simple web dashboard (Flask + Chart.js) showing signal history and P&L
- [ ] TODO: add signal outcome tracking to `reporter.py`

---

### 7. Better universe: switch to S&P 1500
Current approach takes the first 3,000 SEC registrants by CIK (oldest
companies). This is roughly right but not sorted by quality or liquidity.
Institutional traders want S&P 500 + MidCap 400 + SmallCap 600 (the S&P 1500)
— stocks they can actually trade with size. Noted in PROGRESS.md backlog.

**What to do:**
- Fetch S&P 500 from Wikipedia (free, stable URL)
- Fetch MidCap 400 + SmallCap 600 from iShares ETF holdings JSON (free)
- Replace `fetch_us_universe()` with a constituent loader
- [ ] TODO: implement `fetch_sp1500_universe()` in `ingest.py`

---

### 8. Infrastructure hardening (for SaaS option)
Single mini PC with no monitoring is not reliable enough for paying customers.

**What to do:**
- Move to a cloud VM (DigitalOcean, Hetzner, AWS) — ~$10-20/mo
- Add a heartbeat monitor: if the nightly scan doesn't complete, send an alert
  to YOU (not the customer) via a separate channel
- Add automatic restart on crash (systemd on Linux, or Task Scheduler restart policy)
- Uptime target: 99%+ (< 7h downtime/year)
- [ ] TODO: set up heartbeat monitoring (e.g. healthchecks.io free tier)

---

## 🟢 Nice to Have — separates good from great

### 9. Backtesting engine
Show buyers a backtest: "over the last 2 years, Buy Ready signals in a
Confirmed Uptrend returned X% average gain over 20 trading days."
Without this you're selling a black box; with it you have a marketing story.

- [ ] TODO: build `sepa/backtest.py` — replay signals on historical DB data
- [ ] TODO: generate a backtest report (HTML or PDF)

---

### 10. Onboarding UX (critical for Option B / software licence)
Right now setup requires Python, venv, Task Scheduler, `.env` files. No regular
trader will do this. For a software product:
- One-click Windows installer (PyInstaller .exe + Inno Setup wrapper)
- First-run wizard: enter Telegram token, account size, risk %, Anthropic key
- No command line required

- [ ] TODO: add a `setup_wizard.py` (simple tkinter or web form)
- [ ] TODO: package with PyInstaller

---

### 11. Subscription / billing (for Option A / SaaS)
How do you collect payment? How do you cancel access? Options:
- Stripe for payments + webhook to enable/disable user access
- Gumroad for simple one-time or subscription licence keys
- [ ] TODO: decide pricing model before building this

---

### 12. Alerts customisation
Let buyers set their own filters: minimum RS, minimum TT score, exclude certain
sectors, max number of alerts per night, etc.

- [ ] TODO: add per-user config options (once multi-tenancy is solved)

---

## Priority order (work through top to bottom)

1. [ ] Finish 3-month paper trading period
2. [ ] Add exit signals (stop-hit + MA violation alerts on positions)
3. [ ] Switch data provider (yfinance → Polygon.io or Tiingo)
4. [ ] Add disclaimer to all alerts and emails
5. [ ] Decide SaaS vs software licence
6. [ ] Add paper_trades table + auto outcome logging
7. [ ] Switch universe to S&P 1500
8. [ ] Build performance dashboard / extend reporter
9. [ ] Backtest engine
10. [ ] Onboarding UX / installer (if software licence route)
11. [ ] Multi-tenancy + billing (if SaaS route)
12. [ ] Alerts customisation per user
