# PROGRESS.md — SEPA Signals v1 (living checklist)

> Update at the END of EVERY task. Check items only when their acceptance gate
> passed FOR REAL with pasted output. Add discovered work as you find it.
> Legend: [ ] todo · [~] in progress · [x] done & verified · [!] blocked ·
> `NEEDS-LIVE-VERIFY` = code done, user must confirm on mini PC.

_Last updated: 2026-06-11 (Claude). Resume point: **Phase 2 (mini PC)**._

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
