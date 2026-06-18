# PROGRESS.md — SEPA Signals v1 (living checklist)

> Update at the END of EVERY task. Check items only when their acceptance gate
> passed FOR REAL with pasted output. Add discovered work as you find it.
> Legend: [ ] todo · [~] in progress · [x] done & verified · [!] blocked ·
> `NEEDS-LIVE-VERIFY` = code done, user must confirm on mini PC.

_Last updated: 2026-06-18 (Claude). Resume point: **Phase 2 (mini PC) — tier split + intraday scan implemented**._

---

## Status snapshot
- Current phase: **Feature-complete offline. Phases 2/4/6/8 require mini PC.**
- Pipeline proven offline on synthetic US universe: **yes**
- Anything proven on live data: **no**
- v1 "working" (passed paper period): **no**

---

## Phase 0 — Repo hygiene & harness  ✅ DONE
- [x] `requirements.txt` with all deps (including `anthropic>=0.40`)
- [x] `pytest.ini` with `live` mark registered
- [x] `pytest` wired; `tests/conftest.py` sets Agg backend
- [x] `Makefile`: `make venv`, `make test`, `make run`, `make ingest`, `make scan`
- [x] `sepa/log_config.py`: rotating file log (7 days, TimedRotatingFileHandler)
- [x] matplotlib forced to `Agg` (alerter.py + conftest.py)
- [x] `.gitignore` covers venv, DB, charts, logs
- [x] **GATE PASSED 2026-06-11:**
```
47 passed in 8.94s

=== SEPA 2026-06-11 | tone Confirmed uptrend | universe 20 ===
  Watch      3  |  Buy Alert  1  |  Buy Ready  3
  alerts sent: 3 -> ['AAVCP', 'DDPOW', 'EEPOW']
```

## Phase 1 — Live data spine  [x] code done  `NEEDS-LIVE-VERIFY`
- [x] yfinance loader: batching (200/batch), timeout, retry/backoff (_retry helper), per-ticker soft-fail
- [x] EDGAR loader: XBRL concept-name fallback chain (_EPS_CONCEPTS, _REV_CONCEPTS, etc.), rate-limit 0.12s, real User-Agent
- [x] Universe loader: SEC company_tickers → securities table, ETF/shell filter by SIC + name
- [x] L0 hygiene filters: price>$10, avg daily dollar-volume >= $1M
- [x] Unit tests: EDGAR JSON fixture parsing (12 tests, offline) — all pass
- [x] Unit tests: hygiene filter + ETF detection — all pass
- [ ] **GATE (user, mini PC):** 20-name price + fundamentals spot-check sane `NEEDS-LIVE-VERIFY`

## Phase 2 — Funnel calibration  ← make-or-break  `NEEDS-LIVE-VERIFY`
- [ ] L0–L5 run nightly on live ~300
- [ ] Compare stage/TT/RS/footprint vs user chart read on ~20 known names
- [ ] Tune thresholds in config.py to reach agreement
- [ ] Document each threshold change + rationale here
- [ ] **GATE (user):** ~90% agreement engine vs chart `NEEDS-LIVE-VERIFY`

### Phase 2 tier-split + intraday scan (2026-06-18)  ✅ DONE (offline)
- [x] **Buy Ready** split from **Potential Buy**: Buy Ready requires last close ≥ pivot AND
      volume ≥ 1.3× 50-day avg (confirmed breakout). Potential Buy = old Buy Ready criteria
      (good setup, near pivot, no breakout confirmation required).
- [x] `sepa/classify.py`: `_breakout_confirmed(df, setup)` helper, `decide_tier` updated with
      `df=None` parameter; both Power Play and normal paths split correctly.
- [x] `sepa/config.py`: `BREAKOUT_VOL_MULT=1.3` added; `TIER_ORDER` updated to include
      `"Potential Buy"` between `"Buy Alert"` and `"Buy Ready"`.
- [x] `sepa/alerter.py`: `build_card` is tier-aware: "🔥 BUY READY" vs "📈 POTENTIAL BUY" header.
- [x] `sepa/run_daily.py`: passes `df=hist.get(t)` to `decide_tier`; alerts fire on NEW/PROMOTED
      into either Buy Ready OR Potential Buy; resume guard SQL updated; heartbeat shows both counts.
- [x] `sepa/db.py`: pre-existing bug fixed — `write_signal` now uses explicit column names so it
      doesn't fail when the AI migration columns exist (was failing silently, 4 tests broken).
- [x] `sepa/providers.py`: `stage2_breakout` archetype added (260-bar strong advance + VCP base +
      confirmed breakout bar), `ZZBRK` ticker added to synthetic universe.
- [x] Tests: 60 passed (was 52 before the db.py fix). New tests cover `_breakout_confirmed`
      positive/negative fixtures and `decide_tier` Buy Ready vs Potential Buy split.
- [x] `sepa/run_intraday.py`: intraday scanner — pulls 5m yfinance bars for Watch/Buy Alert/
      Potential Buy tickers; checks `close ≥ pivot` AND `vol_pace ≥ 1.3× 50d avg` (annualised
      as `today_vol × 390/minutes_elapsed`); fires Telegram alert; skips if market closed.
- [x] `deploy/windows/intraday_0945.xml` and `intraday_1230.xml`: Windows Task Scheduler XML
      files for 9:45 AM ET (14:45 London) and 12:30 PM ET (17:30 London) runs.
- [x] **Dry-run check (2026-06-18, data date 2026-06-17)**:
      19 current Buy Ready tickers checked against the 1.3× vol + above-pivot filter.
      **Result: 0 stay Buy Ready, 19 move to Potential Buy.**
      None had both close ≥ pivot AND vol ≥ 1.3× avg on the most recent data date. This is
      expected — confirmed breakouts are rare; the engine will re-promote to Buy Ready the next
      day a name breaks out with volume. The existing 19 alerts remain in the dedupe table so
      they will not re-fire when they return to Potential Buy.
- [x] **GATE PASSED (offline): `python -m pytest -q` → 60 passed in 367s**
- [ ] **GATE (user, mini PC):** run nightly scan on live data; verify Potential Buy alerts
      reach Telegram; confirm a real Buy Ready fires when a name breaks out with volume.
      `NEEDS-LIVE-VERIFY`

## Phase 3 — Watch-list state & lifecycle  ✅ DONE
- [x] Persist 5 lists; move-in/out diff verified
- [x] Positions: manual fill entry (open_position, update_position_status, close_position)
- [x] Follow-through / squat / closed status on positions
- [x] Reset Watch: add_reset_watch, remove_reset_watch, get_reset_watch
- [x] Stage-transition alerts: 2→3, 2→4, 3→4 logged + Telegram send for owned/watched names
- [x] **GATE PASSED:** 4 lifecycle golden tests pass
  - full Walk through all 5 states (Watch→Buy Alert→Buy Ready→Position→Reset Watch)
  - Stage transition logged for owned names
  - Positions persist across scanner runs
  - Reset Watch is independent of scanner

## Phase 4 — Alerts hardened  [x] code done  `NEEDS-LIVE-VERIFY`
- [x] Card: chart + why + plan + TV link + AI note
- [x] Dedupe holds across reruns (confirmed in golden test + Phase 0 gate)
- [x] Telegram failure can't break the scan (wrapped, logs to warning)
- [x] Stage-transition alerts (2→3/4 on positions + watchlist)
- [ ] **GATE (user, mini PC):** real card hits phone; no re-alert on rerun `NEEDS-LIVE-VERIFY`

## Phase 5 — Remaining detectors  ✅ DONE
- [x] Cup-with-Handle (7 tests: positive + depth/handle/vol/bars/buyable fixtures)
- [x] Cheat 4-phase (A-B-C-D) + 5 fixtures (recoup too low/high, plateau too deep, insufficient bars)
- [x] Livermore PP (two reaction highs, R2>=R1 guard) + 4 fixtures
- [x] Ranked entry types (low-cheat / cheat / pivot) on Setup.entry_type field
- [x] detect_setups() dispatcher: PP > VCP > Cup-Handle > Cheat > Livermore PP
- [x] Negative: declining name (JJDEC) returns None from detect_setups()
- [x] **GATE:** 20/20 detector tests pass

## Phase 6 — Ops & resilience  [x] code done  `NEEDS-LIVE-VERIFY`
- [x] `deploy/sepa-daily.service` + `deploy/sepa-daily.timer` (22:00 local)
- [x] `deploy/sepa-ingest.service` + `deploy/sepa-ingest.timer` (21:00 local)
- [x] `deploy/logrotate.conf` (daily, 14-day retention, compressed)
- [x] `deploy/.env.example` (ANTHROPIC_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
- [x] DB WAL mode enabled (PRAGMA journal_mode=WAL in schema)
- [x] Nightly vacuum: `db.vacuum()` after scan (WAL checkpoint + VACUUM)
- [x] Resumable mid-run: `run_checkpoint` table, per-ticker checkpoint written
  after each classify; cleared on clean run completion
- [x] `SETUP_US_v1.md` updated with full install instructions
- [ ] **GATE (user):** mid-run kill recovers clean; full scan in budget `NEEDS-LIVE-VERIFY`

## Phase 7 — AI validator  ✅ DONE (offline)  `NEEDS-LIVE-VERIFY`
- [x] `sepa/validator.py`: real Claude claude-opus-4-7 API call (not mocked)
- [x] Inputs: chart PNG (base64) + metrics string + headlines list
- [x] Output: {verdict: CONFIRM|CAUTION|REJECT, reason}
- [x] REJECT suppresses alert; CAUTION annotates card; CONFIRM passes through
- [x] Error fallback: any API error → CAUTION (alert is never silently suppressed)
- [x] Token logging: logs in/out tokens + elapsed time per call
- [x] Wired into run_daily.py (validated before alerter.process)
- [x] AI note shown in Telegram card
- [x] `ANTHROPIC_API_KEY` loaded from env var (via config.py)
- [x] 3 offline tests pass; 2 live tests marked `@pytest.mark.live` for mini PC
- [ ] **GATE (user):** live check on mini PC `NEEDS-LIVE-VERIFY`

## Phase 8 — Paper period (defines "working")
- [ ] Log every alert + subsequent stock behavior, 4–8 weeks
- [ ] Review: follow-through rate, false-positive rate
- [ ] **GATE (user):** alerts judged sane → v1 declared working

---

## Signal quality fixes (2026-06-15) ✅ DONE

Three systemic bugs found via 13-signal audit; all fixed and tested:

**Bug #1 — Extension gate was missing (4 of 13 signals were chase entries)**
- Root cause: VCP `buyable` check was `pivot <= last * 1.05` (trivially true even at +67%
  extension). Cup-with-Handle and Livermore PP had only a lower bound, no upper bound.
- Fix: All three detectors now use `pivot × 0.95 ≤ last ≤ pivot × 1.05`. Any price > pivot ×
  1.05 is `buyable=False` (Buy Alert, not Buy Ready — wait for pullback to new base).
- Safety net added in `detect_setups()`: extension gate re-checks after all detectors, annotates
  footprint with `[EXTENDED +N%]`. Power Play is explicitly exempt (PP is by design "extended").
- New test: `test_extension_gate_marks_not_buyable` confirms extended setups return `buyable=False`.

**Bug #2 — Stop anchored to stale/historical base**
- Root cause: Detectors compute stop from the detected base structure. When price has run far
  past the old pivot (e.g. HPE +67%), the stop referenced a base that no longer exists.
- Fix: Already addressed by the `MAX_STOP_PCT` cap in `detect_setups()` (added in 2026-06-11
  pull): `stop = max(stop, entry × (1 − MAX_STOP_PCT))`. Verified cap raises stale stops
  to current-price-relative level (e.g. HPE: stop raised from $24.23 → $44.32).

**Bug #3 — Volume confirmation threshold wrong in alert card**
- Root cause: `ud_tag` used ⬆/⬇ symbols with 1.0× threshold. Minervini's confirmation bar
  is 1.40× (40% above average accumulation).
- Fix: `VOL_CONFIRM_RATIO = 1.40` added to config. Card now shows ✅ at ≥1.40× and ⚠️ below.

**Tests were hitting live APIs (Telegram + Claude)**
- Root cause: `conftest.py` only set Agg backend; credentials from `.env` were live.
  Engine tests (`test_funnel_golden_tiers`, lifecycle tests) called `run()` which fired
  real Telegram messages and real Claude API calls on every pytest run.
- Fix: `conftest.py` now clears `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`
  before any test runs. Validator error-path returns CAUTION (by design). `alerter.send()`
  now returns `True` on unconfigured-token path so dedupe logging and `sent` list still work.
- Result: 54 non-live tests pass in ~52s with zero external API calls.

**Incremental price fetching**
- `db.get_price_latest_dates(con, tickers)`: single SQL query for the max stored date per ticker.
- `ingest.load_prices()` now splits universe into new tickers (full `PRICE_LOOKBACK` download)
  and incremental tickers (fetch only from `last_date+1` to today, grouped by last date).
  On subsequent nightly runs, established tickers pull 1–2 days instead of 2 years.

**Gate status:** 54 passed in 52s (all non-live). All offline acceptance gates still green.

## Backlog / future upgrades
- [ ] **Universe: switch to S&P 1500** (S&P 500 + MidCap 400 + SmallCap 600) instead of first-N
  from SEC registry. Current approach takes the oldest 3,000 SEC registrants (by CIK), which
  is roughly the right stocks but not sorted by quality/liquidity. S&P 1500 is the true
  institutional universe Minervini targets and would give cleaner signal quality.
  Approach: fetch constituent list from a free source (e.g. Wikipedia S&P 500 table + iShares
  ETF holdings for the other two), replace `fetch_us_universe()` with a constituent loader.

## Discovered work / TODOs found mid-build
- Makefile needed `venv` target (first-time setup on mini PC)
- `tests/conftest.py` needed for Agg backend in test context
- run_daily.py: all per-ticker loops wrapped in try/except for resilience
- Cheat detector: algorithm initially had wrong phase-identification logic (A/B/C
  confusion); fixed by anchoring to C_high as last swing high + working backwards
- Livermore PP: added R2>=R1 guard to prevent false positives on declining stocks
- VACUUM needs an explicit commit first (pending transaction caused "table locked")

## Blockers
- None. All offline work complete.

## Decisions log (what changed and why)
- Data source = yfinance + EDGAR (not screener scraping)
- Phase 7: built real Claude API validator — no mock. Error → CAUTION, never silent suppression.
- Cheat entry types: low-cheat (≤3% above C floor) vs cheat (anywhere in C band)
- Detector priority: PP > VCP > Cup-Handle > Cheat > Livermore PP

## VERIFY-AGAINST-BOOK (setup definitions to reconcile with the text)
- CHEAT: recoup % bounds (33-60%) vs book's 33-50% spec
- CHEAT: plateau depth ceiling (12% used; book says 5-10%)
- LIVERMORE PP: reaction symmetry requirement (R2>=R1 × 0.97 used)
- CUP-HANDLE: handle upper-half rule (handle_low >= mid-cup used)

## Open questions for the user
- Universe size for Phase 1 start (S&P 1500? ~300 liquid names? adjust UNIVERSE_LIMIT)
- Live account size + risk-% for position sizing (config defaults: $100k, 1.25%)
- Market-tone gauge: keep as manual switch in MARKET_TONE config, or compute from breadth?
- Telegram bot setup: need to create bot via @BotFather and get TELEGRAM_CHAT_ID
- Set ANTHROPIC_API_KEY in /opt/sepa/.env on the mini PC before first live run
