# PROGRESS.md — SEPA Signals v1 (living checklist)

> Update at the END of EVERY task. Check items only when their acceptance gate
> passed FOR REAL with pasted output. Add discovered work as you find it.
> Legend: [ ] todo · [~] in progress · [x] done & verified · [!] blocked ·
> `NEEDS-LIVE-VERIFY` = code done, user must confirm on mini PC.

_Last updated: 2026-06-27 (Claude). Resume point: **Auto-deactivation of persistently-failing tickers landed (`yfinance_fail_streak` + `INGEST_DEACTIVATE_STREAK`) — offline verified, `NEEDS-LIVE-VERIFY` on the mini PC.**_

---

## Status snapshot
- Current phase: **Feature-complete offline. Phases 2/4/6/8 require mini PC.**
- Pipeline proven offline on synthetic US universe: **yes**
- Anything proven on live data: **no**
- v1 "working" (passed paper period): **no**

---

## Architecture summary

| Layer | Technology |
|---|---|
| Price data | yfinance (batched 200/batch, retry+backoff) |
| Fundamentals | EDGAR XBRL REST API (concept-name fallback chain, 0.12s rate cap) |
| Universe | SEC company_tickers → ~3,000 names, L0-filtered (price > $10, dollar-vol > $1M) |
| Storage | SQLite WAL-mode (single `data/sepa.db`); vacuumed nightly |
| Nightly scan | `python -m sepa.run_daily` → indicators → RS rank → stage/TT/funda → patterns → tiers → diff → alerts |
| Intraday scan | `python -m sepa.run_intraday` at 9:45 AM ET + 12:30 PM ET (Task Scheduler XMLs in `deploy/windows/`) |
| Alerts | Telegram Bot API (chart PNG + Markdown card); AI validator (Claude Haiku) before each Buy Ready/Potential Buy alert |
| Email report | Gmail SMTP, HTML email after every nightly scan |
| Scheduling | Windows Task Scheduler (manual registration) or systemd on Linux |

---

## Tiers

| Tier | Criteria | Alerts |
|---|---|---|
| **Buy Ready** | Stage 2 · TT ≥ 5 · RS ≥ 70 · funda pass · setup buyable · close ≥ pivot · vol ≥ 1.3× avg | Yes — on NEW/PROMOTED |
| **Potential Buy** | Same as Buy Ready but no confirmed breakout | Yes — on NEW/PROMOTED |
| **Buy Alert** | Stage 2 · TT ≥ 5 · RS ≥ 70 · funda pass · setup present but not in buy zone | No |
| **Watch** | Stage 2 · TT ≥ 5 · RS ≥ 70 · no mature setup | No |
| **⚡ Momentum** | Stage 2 · TT ≥ 7 · RS ≥ 85 · funda FAILS (negative EPS or score < FUND_MIN_SCORE) | Yes — only on confirmed breakout (close ≥ pivot + vol ≥ 1.3×); card labelled "⚡ MOMENTUM" with disclaimer |

Market tone gate: "Correction" → no entries of any tier. "Under pressure" → Buy Ready/Potential Buy degrade to Buy Alert.

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
- [x] `sepa/classify.py`: `breakout_confirmed(df, setup)` helper (public; `_breakout_confirmed`
      alias kept for backwards compat), `decide_tier` updated with `df=None` parameter;
      both Power Play and normal paths split correctly.
- [x] `sepa/config.py`: `BREAKOUT_VOL_MULT=1.3` added; `TIER_ORDER` updated to include
      `"Potential Buy"` between `"Buy Alert"` and `"Buy Ready"`, plus `"Momentum"` at end.
- [x] `sepa/alerter.py`: `build_card` is tier-aware: "🔥 BUY READY" vs "📈 POTENTIAL BUY"
      vs "⚡ MOMENTUM" headers; Momentum card includes fundamental disclaimer line.
- [x] `sepa/run_daily.py`: passes `df=hist.get(t)` and `funda_note` to `decide_tier`;
      alerts fire on NEW/PROMOTED into Buy Ready OR Potential Buy; Momentum alerts fire
      separately only when `momentum_breakout=True`; resume guard SQL updated; heartbeat
      shows all tier counts including Momentum.
- [x] `sepa/db.py`: pre-existing bug fixed — `write_signal` now uses explicit column names.
- [x] `sepa/providers.py`: `stage2_breakout` archetype added (`ZZBRK` ticker).
- [x] **GATE PASSED (offline): `python -m pytest -q` → 68 passed in 367s**
- [ ] **GATE (user, mini PC):** run nightly scan on live data; verify Potential Buy alerts
      reach Telegram; confirm a real Buy Ready fires when a name breaks out with volume.
      `NEEDS-LIVE-VERIFY`

### Phase 2 Momentum tier (2026-06-18)  ✅ DONE (offline)
- [x] **Momentum tier**: Stage 2 · TT ≥ 7 · RS ≥ 85 but funda_pass=False → "Momentum"
      instead of Watch/Buy Alert. Replaces those tiers so INTC-style turnarounds don't
      clutter the SEPA watchlists.
- [x] `sepa/config.py`: `MOMENTUM_RS_MIN=85`, `MOMENTUM_TT_MIN=7` added. Both tunable via .env.
- [x] `sepa/classify.py`: Momentum override runs after regular tier logic and market_tone gate.
      `funda_note` passed in so the card and logs say "unprofitable" / "funda score 2/3" etc.
- [x] `sepa/run_daily.py`: stores `momentum_reason` and `momentum_breakout` flags on Momentum
      signals; fires `alerter.process` separately for breakout-confirmed Momentum stocks.
- [x] `sepa/run_intraday.py`: "Momentum" added to `_SCAN_TIERS` so intraday scanner checks
      pivot crossings for Momentum stocks at 9:45 AM and 12:30 PM ET.
- [x] `sepa/alerter.py`: "⚡ MOMENTUM" header + "⚠️ Fundamentals: <reason> — technical play
      only" disclaimer line in the Telegram card.
- [x] `sepa/reporter.py`: Momentum in `_TIER_CFG` (amber `#fff0d0` accent), in `_DISPLAY_ORDER`
      (at end, below Watch), has dedicated amber disclaimer banner. Excluded from main
      subject counts but appended as "⚡Momentum" suffix.
- [x] 5 new unit tests: positive fixture (funda-fail → Momentum), negative fixtures (RS below
      threshold → Watch, TT below threshold → non-Momentum, funda-pass → non-Momentum,
      correction → None).
- [x] **GATE PASSED: all 5 Momentum tests pass; `python -m pytest -k momentum -v` → 5 passed in 0.25s**
- [ ] **GATE (user, mini PC):** confirm INTC-like ticker shows in ⚡ Momentum section of email;
      confirm Telegram card fires with ⚡ header and disclaimer on real breakout.
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
- [x] Momentum alerts bypass AI validator (already flagged as non-SEPA)
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
- [x] `deploy/windows/intraday_0945.xml` and `intraday_1230.xml`: Windows Task Scheduler XMLs
      for 9:45 AM ET (14:45 London) and 12:30 PM ET (17:30 London)
- [ ] **GATE (user):** Task Scheduler XML files imported manually; mid-run kill recovers clean;
      full scan in budget `NEEDS-LIVE-VERIFY`

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
- [x] Momentum alerts bypass the AI validator (fundamental disqualification already surfaced)
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

**EDGAR revenue/op_margin date mismatch (2026-06-18)**
- Root cause: Revenue and operating-margin series were fetched separately; when their fiscal
  quarters had different end-dates the alignment was off, producing all-zero sales columns.
- Fix: sort + align series by report date before passing to fundamental_screen.

---

## Recent fixes (2026-06-18)

**BUY_ZONE_WIDTH gate for intraday alerts (2026-06-15)**
- Intraday `near_pivot` check now uses `0 <= pct_above <= C.BUY_ZONE_WIDTH` (5% ceiling).
  Without the upper bound, any stock that broke out months ago would re-fire every intraday
  scan because the stored pivot is not updated until the next nightly classify.

---

## External audit fixes (2026-06-21) ✅ DONE (offline)

Five bugs from an external audit of a real (non-synthetic) signal report; all fixed
and unit-tested. **No live DB queries were run** — all tests use synthetic fixtures
per the user's instruction; the live-data versions of these fixes are `NEEDS-LIVE-VERIFY`
on the mini PC.

**Bug 1 (CRITICAL) — pivot sanity check, corrupted-data guard**
- Root cause: GRC's stored pivot ($86.74) exceeded its true ATH ($72.16) — a bad
  price-data join fabricated a Buy Ready signal off an impossible pivot.
- Fix: `sepa/classify.py:pivot_sanity_check()` compares the setup's pivot against the
  52-week high computed from the same price history (`hi_lo_52w(df)` — no separate live
  DB query needed, the engine already has the full series in `df`). If
  `pivot > 52wk_high × PIVOT_SANITY_MAX_ABOVE_52WK (1.05)` → CRITICAL log, tier capped
  at Watch. If `pivot < current_close × PIVOT_STALE_BELOW_PRICE (0.90)` (stock already
  ran past the base) → WARNING log, also capped at Watch. Wired into `decide_tier()` via
  `_apply_sanity_caps()`, applied in both the Power Play and main-ladder branches plus
  the Momentum branch.
- Config: `PIVOT_SANITY_MAX_ABOVE_52WK=1.05`, `PIVOT_STALE_BELOW_PRICE=0.90`.
- Tests: `test_pivot_above_52wk_high_suppresses_signal`, `test_pivot_below_price_suppresses_promotion`,
  `test_valid_pivot_passes_sanity` (tests/test_classify.py).

**Bug 2 (HIGH) — Fund ✓ false positives (DDOG, FLEX, HNGE, CROX, ALGT, NUTX, NXPI, GIII)**
- Root cause: `fundamental_screen()` only hard-gated on the latest quarter's EPS; a single
  profitable quarter could mask an otherwise loss-making trailing year. Revenue growth used
  a single quarter-over-same-quarter-last-year compare, noisy for seasonal/lumpy revenue.
- Fix: two new hard gates before any scoring — TTM net income (sum of last 4 quarters' EPS)
  must be positive, and ROE must be non-negative. Revenue growth check switched to strict
  trailing GAAP TTM-vs-prior-TTM (last 4 quarters summed vs the prior 4), requiring 8 quarters
  of history; EPS growth check (already trailing GAAP — last Q vs same Q last year) left as-is.
- Config: `FUND_REQUIRE_POSITIVE_TTM_EPS=True` (env-overridable).
- Tests: `test_negative_ttm_eps_fails_hard_gate`, `test_negative_roe_fails_hard_gate`,
  `test_positive_ttm_eps_proceeds_to_scoring`, `test_sales_ttm_growth_uses_full_year_not_single_quarter`
  (tests/test_screens.py).

**Bug 3 (HIGH) — M&A acquisition targets flagged as buys (OGN @ $14, pinned by Sun Pharma deal)**
- Fix: `sepa/screens.py:is_merger_arb(df)` — coefficient of variation (stdev/mean) of the
  last 20 closes; CV < 1.5% flags price-pinning. Wired into `decide_tier()`'s
  `_apply_sanity_caps()`, gated on `len(df) >= 252` (a full year of history) so the check
  only fires on genuinely sustained, multi-month pinning — not on a short/synthetic fixture
  or a legitimately tight pre-breakout base (VCP final leg, Power Play flag), which is also
  low-volatility over 20 days but arises from a real prior advance, not a pinned deal price.
- Config: `MERGER_ARB_CV_THRESHOLD=0.015`.
- Tests: `test_merger_arb_detected_on_tight_range`, `test_normal_stock_not_flagged`
  (tests/test_classify.py + tests/test_screens.py, both the direct `is_merger_arb()` unit
  check and the `decide_tier()` integration).

**Bug 4 (MEDIUM) — climax/extension cap (STX +700%/1yr, DELL, ALAB, MXL, REPL, CAR, MRAM)**
- Fix: `sepa/classify.py:_apply_climax_cap()` — when extension above the 200SMA exceeds
  `CLIMAX_EXTENSION_CAP (1.00 = 100%)`, demote Buy Ready → Potential Buy or Potential Buy →
  Buy Alert. Momentum has no lower rung of its own (parallel category, not part of the main
  ladder) so it's tagged but not remapped. A separate `climax_risk` boolean (independent of
  the tier the demotion landed on) flows through `run_daily.py` → `signals.climax_risk`
  (new DB column, migrated) → both the email report (`reporter.py`) and Telegram card
  (`alerter.py`) now show "⚠️ CLIMAX RISK: +X% above 200SMA" when set.
- Config: `CLIMAX_EXTENSION_CAP=1.00`.
- Tests: `test_climax_extension_demotes_potential_buy`, `test_within_cap_not_demoted`,
  `test_climax_tag_propagates_to_card` (tests/test_classify.py).

**Bug 5 (MEDIUM) — AI CAUTION was annotation-only, never demoted the tier**
- This was the literal gap behind CLAUDE.md's own prime directive ("The AI can demote an
  alert, never create one") — until this fix, a CAUTION verdict only added a note to the
  card; the tier (and thus the alert/report) stayed at Buy Ready/Potential Buy regardless.
- Fix: `sepa/run_daily.py:apply_ai_caution_demotion(sig, verdict)` — pure, non-mutating
  helper; demotes Buy Ready → Potential Buy or Potential Buy → Buy Alert on CAUTION, logs
  `TICKER: AI CAUTION → demoted from X to Y`. Wired into the AI-verdict loop right after the
  `ai_note`/`ai_summary` fields are set, before the signal is appended to `confirmed`.
- Scope note: this demotes the sig used for the Telegram alert/card. It does **not**
  retroactively rewrite `watchlist_state`/the email report's tier for that ticker, since
  state is persisted earlier in `run()`, before the AI validator runs — fixing that would
  require reordering the pipeline (AI validation before state diffing), which is out of
  scope for this fix. Flagged here for a future pass if the email report needs to agree.
- Test: `test_ai_caution_demotes_tier` (tests/test_validator.py).

- [x] **GATE PASSED 2026-06-21:** `python -m pytest -q` → **95 passed in 368s** (15 new tests
  added this session: 8 in tests/test_classify.py, 6 in new tests/test_screens.py, 1 in
  tests/test_validator.py). No live DB queries, no live network calls — all fixtures
  synthetic per the user's explicit instruction for this task.
- [ ] **GATE (user, mini PC):** confirm against real data — GRC pivot now suppressed, the
  8 named Fund-✓ false positives now fail the hard gates, OGN-style M&A names cap at Watch,
  a real climax-extended name (e.g. a +100%-above-200SMA breakout) gets demoted + tagged in
  both the email report and Telegram card. `NEEDS-LIVE-VERIFY`

---

## Climax 52wk-gain tag + Momentum fundamentals-improving tag (2026-06-22) ✅ DONE

**Climax tag now shows 52-week gain context**
- The generic `⚠️ CLIMAX RISK: +X% above 200SMA` tag didn't tell the user *why* — a
  name extended +100% above its 200SMA could be a fresh breakout or a year-long
  blow-off; the 52wk gain disambiguates.
- `sepa/run_daily.py`: `gain_52wk_pct` computed alongside the existing `ret_1y`
  (same formula — 252-trading-day price return — kept under its own key so the
  climax tag's meaning doesn't depend on `ret_1y` being repurposed elsewhere).
- `sepa/alerter.py` / `sepa/reporter.py`: when `climax_risk=True` and `gain_52wk_pct`
  is available, the tag reads `⚠️ CLIMAX RISK: +X% / 52wk — still building base`;
  falls back to the old `above 200SMA` wording when 52wk data isn't available
  (<252 bars of history) so `test_climax_tag_propagates_to_card` still passes
  unchanged.
- `sepa/db.py`: new `signals.gain_52wk_pct` column (migrated) so the email report
  can show the same tag from a DB-only read.

**Momentum tier: "Fundamentals Improving" trend label**
- Momentum-tier stocks (pass all technicals, fail the fundamental screen) previously
  showed only the generic failure reason. A subset are turnaround stories — EPS or
  revenue accelerating into the failed quarter — worth distinguishing from a pure
  technical play.
- `sepa/screens.py:fundamental_trend(f)` — pure function, same `{eps, sales}` input
  shape as `fundamental_screen()`. Returns `eps_trend`/`rev_growth_trend` (last 4
  quarters), `eps_accelerating`/`rev_accelerating` (2+ consecutive rising steps),
  `improving` (either accelerating), and a human-readable `trend_label` (e.g.
  `"EPS $-0.12→$0.31→$0.58 (↑)"` or `"Rev 8%→15%→22% YoY (↑)"`). Returns all-False/empty
  when fewer than 3 quarters of EPS are available.
- `sepa/run_daily.py`: called right after a stock is classified Momentum; stores
  `funda_improving` + `funda_trend_label` on the signal.
- `sepa/alerter.py`: Momentum card disclaimer becomes `⚡ Fundamentals Improving: ...
  — watch for fund confirmation` when `funda_improving=True`; unchanged
  `⚠️ Fundamentals: ... — technical play only` otherwise.
- `sepa/reporter.py`: Momentum card in the email shows the same trend-label line
  when improving.
- `sepa/db.py`: new `signals.funda_improving` / `funda_trend_label` columns
  (migrated).
- Tests: `test_fundamental_trend_accelerating_eps`, `test_fundamental_trend_flat`,
  `test_fundamental_trend_insufficient_data` (tests/test_screens.py).

- [x] **GATE PASSED 2026-06-22:** `python -m pytest -q` → **98 passed in 367s** (3 new
  tests in tests/test_screens.py).
- [x] **Spot-checked against the real live DB** (`python -m sepa.run_daily`, 2,853-ticker
  universe): `gain_52wk_pct` populated on all 5 climax-flagged names sampled (e.g. STX
  +726%/52wk, MU +833%/52wk); 32 of 207 Momentum names flagged `funda_improving=1` with
  correct trend labels (e.g. `BE`: `EPS $-380.00→$-0.37→$0.23 (↑)`; `SMTC`:
  `Rev 13%→15%→16% YoY (↑)`). **Note:** this same invocation is the script's normal nightly
  entrypoint — it sent a real email report and committed+pushed the run log to GitHub
  (`origin/main`), matching the already-established automated logging pattern in this
  repo's history. No Telegram alerts fired (0 newly-buyable signals this run).

---

## Intraday float/Series bug + error-rate alerting + scheduler XML fix (2026-06-22) ✅ DONE

**Root cause: yfinance MultiIndex columns broke scalar extraction**
- The 14:00 intraday scan logged 296 `float() argument must be a string or a real
  number, not 'Series'` warnings — 42% of tickers failed silently, 0 alerts sent.
- Some installed yfinance versions return `(Price, Ticker)` MultiIndex columns even
  for a single-ticker `yf.download()` call. Unflattened, `df["close"]` is a
  one-column DataFrame, not a Series, so `df["close"].iloc[-1]` itself returns a
  one-element Series and `float(...)` on it raises.
- `sepa/run_intraday.py`: added `_flatten_columns()` (collapses MultiIndex to
  single-level) and `_last_close_and_volume()` (always returns plain floats) —
  used in place of the inline `float(df5["close"].iloc[-1])` call.
- Per-ticker exception handler changed from `log.warning(..., e)` (message only)
  to `log.error(..., exc_info=True)` (full traceback) so a real failure mode is
  visible in the log instead of just the exception string.

**Error-rate alerting (silent degraded-scan problem)**
- A scan that mostly fails (like the 296-warning one) previously produced *no*
  signal that anything was wrong beyond log noise — 0 alerts looks identical to
  "quiet market" and "broken scanner."
- `sepa/run_intraday.py`: tracks `error_count`/`total_count`/`error_messages`
  through the scan loop; after the loop, if `error_rate > C.INTRADAY_ERROR_RATE_THRESHOLD`
  fires `log.critical(...)` + a Telegram text alert via the new `alerter.send_text()`.
- `sepa/config.py`: new `INTRADAY_ERROR_RATE_THRESHOLD` (env-overridable, default
  0.05) — kept as a config threshold per the "never inline a magic number" rule.
- `sepa/alerter.py`: new `send_text(text)` — thin wrapper around the existing
  `send()` for text-only ops alerts (no chart), reusing the same Telegram
  token/chat-id config and the same no-op-when-unconfigured safety behavior.

**Scheduler XML times were wrong**
- `deploy/windows/intraday_0945.xml` had `StartBoundary` `14:45:00` (a leftover
  London-time value) instead of `09:45:00`; `intraday_1230.xml` had `17:30:00`
  instead of `12:30:00`. Both fixed on disk; **not re-registered** — the user
  needs to re-run `schtasks /create ... /f` manually to pick up the corrected XML.

- [x] **GATE PASSED 2026-06-22:** `python -m pytest -q` → **103 passed in 369s**
  (5 new tests in `tests/test_intraday.py`, including
  `test_intraday_error_rate_alert_fires`: 10/20 mock tickers raising trips the
  alert, the other 10 are still scanned without the exception propagating).
- [x] **Live run verified** (`python -m sepa.run_intraday`, market open): 703
  tickers scanned, **0 unhandled errors** (down from 296 warnings / 42% failure),
  19 alerts sent. The only `ERROR`-level lines in the run are yfinance's own
  "possibly delisted" notices for 5 tickers, which correctly resolve to an empty
  `df5` and `continue` rather than an exception — not counted as scan errors.

---

## yfinance "possibly delisted" retry + stale-price detection (2026-06-25) ✅ DONE (offline)

**Root cause: silent universe drop on transient yfinance batch glitches**
- FTNT (and others) were disappearing from the universe with no error: yfinance's
  batch `yf.download()` occasionally returns empty/all-NaN rows for one ticker in
  an otherwise-good batch ("possibly delisted; no price data found"), which is a
  transient API glitch, not a real delisting. The ticker got no price data, no TT
  score, no tier, and never appeared in signals — failing silently per the Phase 6
  ops-hardening gap this closes.

**Fix 1 — individual retry for batch-missing tickers**
- `sepa/ingest.py`: `_process_batch()` now distinguishes two failure modes —
  a ticker with **entirely empty raw rows** (the glitch) is routed to a new
  `missing_out` list; a ticker with **real data that fails the hygiene filter**
  (penny stock, illiquid) is still counted as `skipped` as before. Only the
  former is retried — a correct hygiene exclusion must never be retried.
- New `_fetch_individual_with_retry(t, period=, start=, end=)`: retries
  `yf.Ticker(t).history(...)` up to `C.INGEST_RETRY_COUNT` times with
  `C.INGEST_RETRY_BACKOFF`-second sleeps; logs a `WARNING` per attempt, an
  `INFO` on recovery, and a final `ERROR` ("...ticker will be stale") if every
  attempt comes back empty.
- New `_retry_missing(con, missing, counter, ...)`: drives the retry for a
  batch's missing list, applies the same column-normalize + hygiene-filter
  path as the main batch, and upserts any ticker that recovers. Wired into
  both the new-ticker and incremental branches of `load_prices()`.
- `sepa/config.py`: `INGEST_RETRY_COUNT` (default 3), `INGEST_RETRY_BACKOFF`
  (default 5s) — env-overridable, no inlined magic numbers.

**Fix 2 — stale-price detection (safety net for retries that still fail)**
- `sepa/db.py`: `get_stale_tickers(con, max_age_days)` — LEFT JOIN of
  `securities` against `MAX(date)` per ticker in `prices`; returns active
  tickers with no price newer than `max_age_days` (or no price at all).
- `sepa/ingest.py`: `check_stale_prices(con, max_age_days=None)` — logs a
  `WARNING` per stale ticker; if the stale count exceeds
  `C.STALE_TICKER_ALERT_THRESHOLD` (default 10), sends a Telegram ops alert
  via the existing `alerter.send_text()` (same pattern as the intraday
  error-rate alert from the 2026-06-22 fix). Called at the end of
  `ingest_us()`.
- `sepa/config.py`: `INGEST_STALE_DAYS` (default 3), `STALE_TICKER_ALERT_THRESHOLD`
  (default 10).

- [x] **GATE PASSED 2026-06-25:** `python -m pytest -q` → **112 passed in 373s**
  (10 new tests in `tests/test_ingest.py`: missing-vs-skipped routing, retry
  recovery on a later attempt, retry exhaustion + final-error log, upsert on
  recovery, persistent-failure counting, stale-ticker logging, fresh-ticker
  not flagged, and the >threshold Telegram-alert trigger).
- [ ] **GATE (user, mini PC):** `NEEDS-LIVE-VERIFY` — confirm a real "possibly
  delisted" batch glitch (FTNT-style) recovers via individual retry on a live
  nightly run, and that the stale-ticker WARNING/alert fires correctly if the
  yfinance feed degrades for real.

---

## Stale-ticker false-positive fix: hygiene-excluded tickers wrongly flagged stale (2026-06-25) ✅ DONE (offline)

**Bug report:** the 2026-06-25 21:30 ingest run flagged 2250 of 5083 active
securities as stale — reported as "basically the whole universe."

**Investigated as a date-comparison/timezone/off-by-one bug per the original
report and ruled that out**: raw SQL against `data/sepa.db` showed `MAX(date)`
stored as plain `YYYY-MM-DD` (no timezone suffix), and `INGEST_STALE_DAYS` was
already 5 (bumped from 3 by commit `920dd77`, made between the 21:30 log run
and this fix, which also added the 20%-of-universe Telegram-suppression guard).
A raw `date('now','-5 days')` comparison against `prices` directly found only
98 genuinely stale tickers, not 2250.

**Actual root cause:** `get_stale_tickers()` LEFT JOINs `securities` against
`prices`; any active security with **no price row at all** shows up with
`last_date IS NULL` and is reported stale ("last updated never"). 2152 of the
5083 active securities have *never* had a price row, almost entirely because
`hygiene_filter()` correctly and permanently rejects them (penny stock /
illiquid — by design, per its own docstring: "a correct exclusion, not a
glitch"). Nothing marked these tickers as excluded, so `active` stayed `1`
forever and they re-triggered the same false "stale" warning every single
night. 2152 (never-ingested/hygiene-excluded) + 98 (genuinely stale) = 2250,
exactly matching the reported count.

Confirmed commit `920dd77`'s 20%-suppression guard already stops the Telegram
alert in this exact case (2250/5083 = 44% > 20%) — but it only suppresses the
*alert*; the 2250 misleading per-ticker WARNING log lines still print every
run, and the guard's own test (`test_stale_ticker_alert_above_threshold`) was
broken by it (a small all-stale test universe always exceeds 20%) — found
failing on `main` before this fix.

**Fix**
- `sepa/db.py`: new `hygiene_excluded` column on `securities` (schema +
  `_migrate()`), new `set_hygiene_excluded(con, ticker, bool)` helper.
  `get_stale_tickers()` now excludes `hygiene_excluded=1` tickers — they are
  intentionally never given price data, not stale.
- `sepa/ingest.py`: `_process_batch()` sets `hygiene_excluded=True` when real
  (non-empty) price data fails `hygiene_filter()`, and clears it on the next
  successful load — self-heals if a ticker's price/volume later qualifies.
- `tests/test_ingest.py`: fixed `test_stale_ticker_alert_above_threshold` to
  use a realistic universe size (stale tickers ~9% of total) so it tests the
  absolute-threshold alert path distinctly from the percentage-suppression
  path. Added `test_stale_pct_above_20pct_suppresses_alert`,
  `test_hygiene_excluded_ticker_not_flagged_stale`, and
  `test_hygiene_excluded_clears_when_ticker_recovers`.
- [x] **GATE PASSED 2026-06-25:** `python -m pytest -q` → **115 passed in
  370s**.
- [ ] **GATE (user, mini PC):** `NEEDS-LIVE-VERIFY` — after this lands, the
  next real nightly ingest should show the stale-ticker WARNING count drop
  from ~2250 to roughly the genuinely-stale figure (~98 on 2026-06-25's data).

**Side effect during this fix, disclosed to user:** running `python -m
sepa.run_daily` to satisfy the CLAUDE.md acceptance gate turned out to **not**
be offline/synthetic — it made live Anthropic API calls (validator), sent a
real daily email report, and auto-committed+pushed log files directly to
`origin/main` (commit `d9858af`, log files only, no code). No Telegram alerts
fired (0 alerts that run). Flagged here since CLAUDE.md describes this command
as the "offline synthetic run" gate, which it is not — `run_daily` is a live
production command. `VERIFY-AGAINST-BOOK` not applicable; this is a tooling/
docs accuracy gap worth fixing separately (PLAN.md or CLAUDE.md should name
the actual offline-safe entry point, if one exists, instead of `run_daily`).

---

## Intraday scanner rewrite: re-evaluate from scratch, not trust yesterday's tier (2026-06-26) DONE (offline) / NEEDS-LIVE-VERIFY pending

**Problem with the old `run_intraday.py`:** it trusted the DB's last-stored
tier (`db.prev_state()`) and pivot, then asked only "is price within
`BUY_ZONE_WIDTH` of that pivot with volume pace >= threshold?" That re-fires
on any stock that broke out months ago and is still drifting near its old
pivot (the QMCO case) and never re-checks whether the stock is still Stage 2
intraday.

**Rewrite:**
- `sepa/run_intraday.py`: `run_intraday()` renamed to `run_scan()` (no other
  module referenced the old name - verified via repo-wide grep). Old 5-minute
  bar volume-pace extrapolation replaced with:
  - `load_watchlist(con)`: pulls every ticker from the latest nightly
    `signals` row with `stage=2 AND tt>=5 AND pivot>0` - Stage 2 leaders
    only, not every Watch/Buy Alert/Momentum ticker.
  - `load_daily_history(con, ticker)`: last 252 trading days of close/volume
    from the DB (no live history pull).
  - `get_live_quote(ticker)`: the one yfinance call per ticker - 1-minute
    bars for today, collapsed to (live price, cumulative intraday volume).
  - `evaluate_breakout(...)`: appends the live quote as a synthetic last
    bar, recomputes SMAs/Stage/trend-template from scratch via
    `indicators.add_mas` + `screens.trend_template`/`classify_stage`, then
    gates an alert on ALL of: Stage 2 now, TT>=5 now, direction check
    (`prev_close < pivot <= live_price` - a fresh cross today, not already
    cleared), stale-pivot guard (52wk high AND prev close already greater
    than `pivot * (1 + INTRADAY_STALE_PIVOT_RUN)` means the base broke out
    long ago), and volume pace >= `BREAKOUT_VOL_MULT`.
- `sepa/config.py`: new `INTRADAY_STALE_PIVOT_RUN` (default 0.10, env-overridable).
- Old MultiIndex-flattening helpers (`_flatten_columns`, `_last_close_and_volume`,
  `_names_match`) and the `--mode` CLI arg removed - no longer applicable to
  the new single-quote-per-ticker shape. Ticker-reassignment name-mismatch
  guard was dropped in the rewrite, not reintroduced (`run_scan` only walks
  tickers already in `securities`/`signals`, not raw yfinance lookups).
- `tests/test_intraday.py`: fully rewritten for the new logic - direction
  check (fires / QMCO already-past-pivot case), stale-pivot guard, Stage-2
  failure on an underlying downtrend, and the error-rate alert path (now
  mocking `get_live_quote` instead of `yfinance.download`). All mocked, no
  real network calls.
- [x] **GATE PASSED 2026-06-26:** `python -m pytest -q -m "not live"` ->
  **113 passed, 2 deselected in 372.98s**.
- [ ] **GATE (user, mini PC):** `NEEDS-LIVE-VERIFY` - a prior attempt to
  live-verify `get_live_quote()` against real yfinance during this session
  hung on the network call and was abandoned; the rewrite has not been run
  against a real market-hours quote yet. Confirm on the mini PC during
  market hours that `python -m sepa.run_intraday` completes without hanging
  and that `evaluate_breakout` fires correctly on a real Stage-2 breakout.
- `deploy/windows/intraday_0945.xml` and `intraday_1230.xml` still passed
  `--mode intraday` to the scheduled task command line after the flag was
  dropped from the script; harmless (unused argv is ignored, no argparse to
  reject it) but updated both XMLs to `-m sepa.run_intraday` for accuracy.

---

## Investigated: 101 stale tickers, examples AAC/AIOS/AMEGF/AMSS/ARSMF (2026-06-27)

**User's hypothesis was wrong for 4 of the 5 named examples.** AIOS, AMEGF,
AMSS, and ARSMF are not OTC-foreign tickers yfinance can't serve — live check
(`yf.Ticker(t).history(period="5d")`) returned real data for all four right
now. Only AAC is genuinely unfetchable ("possibly delisted; no price data
found", confirmed failing on 5 consecutive nightly ingest runs 2026-06-22
through 2026-06-26).

**Root-cause breakdown of the 101** (cross-referenced each stale ticker's
position in a fresh, unlimited `fetch_us_universe()` call against
`UNIVERSE_LIMIT=5000` from `.env`, then live-checked yfinance fetchability):

| Cause | Count | Detail |
|---|---|---|
| **Dropped out of the top-5000 universe window** | 78 (77%) | Fetchable via yfinance, but `fetch_us_universe(limit)` truncates to `rows[:5000]` — SEC's `company_tickers.json` ordering is not stable day-to-day, so a ticker that was inside the top 5000 when first added to `securities` (and so `active=1` forever, since `upsert_security`'s `ON CONFLICT` never touches `active`) can drift past index 5000 on a later day and simply stop being passed to `load_prices()`. No error, no log line — it's never attempted, so `get_stale_tickers()` flags it forever. **AIOS, AMEGF, AMSS, ARSMF (3 of the user's 5 examples) are this case** — indices 5107/7454/5305/7499 respectively in the full (unlimited) fetch. |
| **Genuinely unfetchable, still inside the universe window** | 17 | Confirmed "possibly delisted; no price data found" on a live check just now: AAC, AVAC, AYR, BRKH, CONE, CURLF, FWAC, LVPA, MSSHY, NANO, OBOCY, PFSTY, PHD, PMVC, PTAC, SEAH, VII. Several (AAC, AVAC, BRKH, FWAC, PTAC) look like SPAC tickers that liquidated/de-registered, not OTC-foreign names. **AAC (1 of the user's 5 examples) is this case.** |
| **Dropped from the SEC universe entirely** | 4 | BIOT, JMG, OPTN, TCGL no longer appear in SEC's `company_tickers.json` at all (deregistered/merged) *and* are unfetchable via yfinance — genuinely dead by both signals. |
| **Dropped from SEC universe but still fetchable** | 1 | IXAQF — gone from the SEC list, but yfinance still serves it fine. Same underlying "fell out of the source list" issue as the 78 above, different source list. |
| **Transient lag, not dead** | 1 | WHK — DB last price 2026-06-18 (8 days stale), but a live check just returned 1 day of data fine. Likely just lagging the retry budget, not broken. |

**Action taken: none, deliberately.** Two reasons:
1. A concurrent in-progress change in this same working tree (`sepa/ingest.py`
   `_update_fail_streaks` + `sepa/db.py` `increment_fail_streaks` /
   `deactivate_stale_streaks`, gated by new `INGEST_DEACTIVATE_STREAK`) already
   auto-deactivates a ticker after `INGEST_DEACTIVATE_STREAK` (default 3)
   consecutive `load_prices()` failures *while it's still in the attempted
   universe* — this is exactly the right mechanism for the 17-ticker "genuinely
   unfetchable, still in-window" bucket (including AAC) and needs no help from
   this investigation; it'll self-resolve within 3 nights of that code landing.
2. The dominant 77% bucket is **not** a "permanently unfetchable ticker" problem
   — these are real, currently-tradeable, yfinance-fetchable securities that
   the universe selection simply stopped looking at. Marking them `active=0`
   would be silencing real coverage to make a noise metric look better, which
   is the wrong fix (and exactly what CLAUDE.md's "never fake a result to pass
   a check" rules out). The dropped-from-SEC-entirely buckets (4 dead + 1
   fetchable) have the same shape but a different source list.

**Recommended real fix (not implemented — architecture decision, flagged for
the user):** `fetch_us_universe(limit)` truncates with `rows[:limit]` against
whatever order SEC's JSON happens to be in that day. Either (a) raise/remove
`UNIVERSE_LIMIT` (currently 5000, full unfiltered universe is ~9,841 post
ETF/shell filter), (b) sort deterministically before truncating (e.g. by CIK
ascending) so the top-N window is stable across days instead of churning, or
(c) extend the `securities` row with a "missing from universe fetch" streak
(parallel to the new yfinance-failure streak) and auto-deactivate on that
instead of just on fetch failure. Until one of these lands, any ticker that
drifts past the cutoff will permanently and silently stop being analyzed —
this is a coverage gap, not just stale-alert noise.

---

## Auto-deactivation of persistently-failing tickers (2026-06-27) ✅ DONE (offline)

Closes the mechanism flagged as "in-progress" in the 2026-06-27 stale-ticker
investigation above (item 1 in that section's "Action taken" rationale) — a
ticker that fails `load_prices()` for real (no usable data even after the
individual retry from the 2026-06-25 fix) for `INGEST_DEACTIVATE_STREAK`
(default 3) consecutive nightly runs is now marked `active=0`, so it stops
permanently polluting `check_stale_prices()`'s warnings/alerts instead of
re-flagging forever.

- `sepa/db.py`: new `securities.yfinance_fail_streak` column (migrated, default
  0). Three new pure-SQL helpers: `reset_fail_streaks(con, tickers)` (zero the
  streak for tickers that loaded successfully this run), `increment_fail_streaks(con,
  tickers)` (bump by 1 for tickers that didn't), `deactivate_stale_streaks(con,
  threshold)` (sets `active=0` for any security whose streak has reached
  `threshold`, returns the list of tickers it just deactivated).
- `sepa/ingest.py`: `_process_batch()` and `_retry_missing()` both take an
  optional `failed_out` list and append a ticker to it when it has no usable
  data after all retries (exception during batch processing, or still empty
  after the individual retry) — distinct from a hygiene-filter skip, which is
  an intentional exclusion, not a failure. `load_prices()` accumulates a
  `failed_tickers` list across every batch (new-ticker and incremental, plus
  whole-batch download exceptions) and calls the new `_update_fail_streaks(con,
  failed_tickers, tickers)` once at the end. That function resets the streak
  for everything that succeeded, increments it for everything that didn't,
  deactivates anything at threshold, and — matching the existing
  `check_stale_prices()` ops-alert pattern — fires a Telegram text alert via
  `alerter.send_text()` naming the deactivated tickers (capped to first 5 in
  the message, first 10 in the log line).
- `sepa/config.py`: `INGEST_DEACTIVATE_STREAK` (default 3, env-overridable).
  Note: this constant already existed in `config.py` before this task (restored
  by commit `7456c26` as one of several constants that went missing in the
  intraday-scanner rewrite) but was dead — nothing in `db.py`/`ingest.py`
  referenced it until this change actually wired it up.
- `tests/test_ingest.py`: 4 new tests — `test_fail_streak_increments` (0→1→2
  across repeated failures), `test_fail_streak_resets_on_success` (streak=2
  then a success run resets to 0), `test_auto_deactivate_at_threshold` (streak
  hits `INGEST_DEACTIVATE_STREAK` → `active=0` + exactly one `alerter.send_text`
  call naming the ticker), `test_successful_tickers_not_deactivated` (control
  ticker that always succeeds stays `active=1`, streak=0, no alert).
- [x] **GATE PASSED 2026-06-27:** `python -m pytest -q` → **119 passed in 375s**.
- [ ] **GATE (user, mini PC):** `NEEDS-LIVE-VERIFY` — confirm on a real nightly
  ingest that AAC (or another of the 17 genuinely-unfetchable tickers named in
  the 2026-06-27 stale-ticker investigation above) actually flips to `active=0`
  after its 3rd consecutive failed night, and that the Telegram ops alert
  fires correctly when that happens.

---

## Known limitations / pending work
- **Prices can be 1–2 days stale** if the nightly ingest didn't complete (yfinance incremental
  pull only fetches since last stored date). Partially mitigated 2026-06-25:
  `ingest.check_stale_prices()` now logs a WARNING per stale ticker and fires a
  Telegram alert above `STALE_TICKER_ALERT_THRESHOLD` — visibility, not auto-fix.
- **Pivot staleness**: the nightly classify recomputes the pivot from the last 65 bars of price
  history, but if a stock is in the `done` checkpoint set on a resume run, its pivot comes from
  the DB (last classify) rather than fresh price data. Stale pivots cause intraday alerts to
  reference old levels. Not yet fixed — needs a "re-pivot" step on resume.
- **ZZBRK synthetic test fixture**: breakout archetype exists in SyntheticProvider but the
  full-funnel golden test (`test_funnel_golden_tiers`) doesn't yet assert ZZBRK lands in
  Buy Ready. This is a coverage gap, not a runtime bug.
- **Task Scheduler registration**: XMLs are in `deploy/windows/` but the user must import
  them manually via `schtasks /Create /XML ...` or the Task Scheduler GUI. Not automated.
- **Stale pivot recalculation**: not yet built. After a long gap between scans, the stored
  pivot in DB may refer to a base that has been invalidated. Nightly classify should
  re-run detect_setups even for checkpoint-skipped tickers when `asof` differs by more
  than N days from last classify date. Backlog item.
- **INTC-style fundamental turnarounds now tracked as Momentum**: stocks with RS≥85, TT≥7,
  Stage 2 but negative/weak EPS land in the Momentum tier. Once fundamentals improve
  (next EDGAR fetch shows positive EPS + score ≥ FUND_MIN_SCORE), the nightly scan
  will automatically promote them to Buy Alert / Potential Buy / Buy Ready.

---

## Backlog / future upgrades
- [ ] **Universe: switch to S&P 1500** (S&P 500 + MidCap 400 + SmallCap 600) instead of first-N
  from SEC registry. Current approach takes first-`UNIVERSE_LIMIT` (5000) SEC registrants in
  whatever order `company_tickers.json` returns them — **not stable by CIK as previously
  noted here**: confirmed 2026-06-27 (see "Investigated: 101 stale tickers" above) that
  borderline tickers drift across the cutoff day to day, permanently dropping real, fetchable
  securities out of analysis with no error logged. S&P 1500 is the true institutional universe
  Minervini targets and would give cleaner signal quality AND fix the drift bug (a fixed
  constituent list doesn't reorder daily). Approach: fetch constituent list from a free source
  (e.g. Wikipedia S&P 500 table + iShares ETF holdings for the other two), replace
  `fetch_us_universe()` with a constituent loader.
- [ ] **Stale pivot recalculation** — re-run detect_setups for checkpoint-skipped tickers
  when last classify date is > 3 days old.
- [ ] **ZZBRK golden-test assertion** — add Buy Ready assertion to `test_funnel_golden_tiers`.
- [ ] **AI CAUTION demotion doesn't reach watchlist_state/email report** — `run_daily.py`
  persists `watchlist_state` (and thus the tier the email report reads) before the AI
  validator runs; `apply_ai_caution_demotion()` (2026-06-21) only demotes the in-memory sig
  used for the Telegram alert. Fixing this needs the AI validation step moved earlier in
  `run()`, before the state diff/persist — a pipeline reordering, not a small patch.

---

## Discovered work / TODOs found mid-build
- NEEDS-LIVE-VERIFY (2026-06-22 audit of intraday STX/CRWD/GFS alerts): cross-checked the
  15:51:09-intraday log against live yfinance. The logged close/pivot/vol_ratio for all
  three exactly matched the alert text (not corrupted, not hallucinated). But all three
  fired at ~10:51 AM ET, only ~21% into the session — `vol_ratio` extrapolates from
  `_minutes_elapsed()` (run_intraday.py), and a small-sample early-session extrapolation
  is noisy. Live recheck at 1:54 PM ET (~68% elapsed) showed pace had decayed to
  STX 1.2x, CRWD 0.8x, GFS 0.7x — all now below BREAKOUT_VOL_MULT (1.3, config.py:212).
  CRWD's price had also fallen back below its pivot by midday (signal failed/reversed).
  Consider gating early-session vol_ratio alerts behind a minimum elapsed-time floor
  (e.g. don't alert before ~60-90 min into the session) to reduce false-confidence pace
  reads. Note: BREAKOUT_VOL_MULT is 1.3 in config, not 1.5 — if 1.5x is the intended bar,
  config.py needs updating; GFS's 1.35-1.4x cleared 1.3 but would have failed 1.5.
- TODO before 2026-07-02 (CRWD 4-for-1 forward split, confirmed effective that date):
  grepped ingest.py and run_intraday.py — there is no split-detection or back-adjustment
  logic anywhere in the pipeline. Pre-split pivot/price history is stored as-is in SQLite.
  When the split executes, post-split quotes (~1/4 of pre-split) will silently desync
  from the locally cached pre-split history (pivot, 50-day avg volume, stage calcs) for
  CRWD specifically, and any other ticker with an announced split. Needs a split-detection
  step in ingest.py (compare yfinance split-adjusted vs raw close, or re-pull full history
  on detected discontinuity) before 2026-07-02.
- FIXED (2026-06-23): `deploy/windows/intraday_0945.xml` and `intraday_1230.xml` had been
  miswritten with StartBoundary times of 09:45/12:30, five hours before NYSE open. The mini
  PC clock runs UK local time (BST), not US Eastern, so these tasks would have fired hours
  before the market opened. Reverted StartBoundary to 14:45/17:30 (BST 14:45 = NYSE 09:45
  EDT open+15min; BST 17:30 = NYSE 12:30 EDT mid-session) and updated the in-file comments
  to spell out the BST→EDT mapping so this isn't miscorrected again. File names still say
  `_0945`/`_1230` (EDT-derived) even though the StartBoundary is BST — not renamed since
  task names registered via `schtasks` reference these filenames.
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
- Momentum tier (2026-06-18): INTC-class names (RS≥85, TT≥7, Stage 2, funda-fail) get their
  own tier rather than polluting Watch/Buy Alert. Alerts only on confirmed breakout. The
  RS threshold (85) is intentionally higher than the regular RS_MIN (70) to keep only the
  very strongest technical setups; funda-fail names with RS 70-84 still go to Watch/Buy Alert.

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
- MOMENTUM_RS_MIN (default 85) and MOMENTUM_TT_MIN (default 7) tunable via .env if too strict/loose
