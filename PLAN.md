# PLAN.md — SEPA Signals, v1 Build Plan (US-only, mini-PC, alert-first)

> Living document. Update when scope changes. Pair with `PROGRESS.md` (status)
> and `CLAUDE.md` (engineering rules). A future agent should be able to resume
> from these three files alone.

## 1. Product in one paragraph

A self-hosted personal scanner on a 24/7 mini PC. Each evening after the US
close it ingests raw price + fundamental data, runs Minervini's SEPA
methodology as a **deterministic multistage funnel**, maintains several tiered
watch lists, and sends a Telegram alert — chart + plain-English reasoning +
trade plan — the moment a stock becomes *buyable*. A single bounded AI step
reviews only the final survivors. No web UI in v1; Telegram is the interface.
No auto-execution in v1.

## 2. Hard design decisions (settled — do not relitigate)

- **Scripts decide, AI reviews.** Deterministic funnel does ~99%. AI validates
  only Buy-Ready candidates, last, and can only demote.
- **Raw data in, not screener signals.** Prices = yfinance. Fundamentals = SEC
  EDGAR. NO scraping of TradingView/screeners in the critical path — fragile,
  ToS-violating, and it would import someone else's methodology instead of ours.
- **EOD only.** No intraday anything in v1. Position-trading timeframe.
- **US-only** for v1 (EDGAR is US-complete and free; global fundamentals are
  the expensive hard part — deferred).
- **Close-based stops** (the engine treats the stop as sacred; shakeout logic
  informs placement/re-entry, never overrides a live stop).
- **TradingView's role = the human chart** you eyeball from the alert link, not
  a data source.

## 3. The funnel (each layer is pure computation; survivors pass down)

```
L0  Universe & hygiene   SEC listings; price>$10, min $-volume, no ETF/shell
L1  Fundamental gate     EDGAR: EPS accel, sales growth, op-margin trend, ROE>=17 → score>=3
L2  Stage analysis       Stage 1/2/3/4 from MA structure+slope; only Stage 2 forward
                         (power-play path bypasses extension filters by design)
L3  Technical multilevel Trend Template x/8 (>=6 visible, >=7 promote) → RS percentile (>=70)
L4  Pattern detection    VCP/3C(+footprint), cup-handle, 4-phase cheat, Livermore PP, power play
L5  Tier + market gate   3-axis alignment (fund+tech+tape) → Watch / Buy Alert / Buy Ready
                         + lifecycle lists: Positions, Reset Watch
L6  Diff + alert         move-in/out vs yesterday; Telegram on NEW Buy Ready; dedupe; heartbeat
L7  AI validator (last)  Claude reviews each NEW Buy Ready: CONFIRM/CAUTION/REJECT + 2-line why
```

The five monitored watch lists: **Watch, Buy Alert, Buy Ready, Positions,
Reset Watch.** Stage transitions (e.g. 2→3 on owned/watched names) are alert
events in their own right.

## 4. Setup library (encode exactly; thresholds in config.py)

| Setup | Defining rule (from the book) |
|---|---|
| VCP / 3C | contractions each shallower, volume dries into pivot; footprint `[wks]W [1st%]/[last%] [n]T` |
| Cup-with-handle | handle = final shallow low-volume contraction under the rim; handle high ≈ pivot |
| Cheat (4-phase) | A downtrend → B uptrend (recoup 33-50%) → C pause/plateau 5-10% (ideally a shakeout) → D breakout above plateau high |
| Livermore PP | downtrend breaks, TWO reaction pullbacks, buy above 2nd reaction high |
| Power Play | +100% in <8wks after dormancy; flag ≤20-25% over ~12d-6wk; volume dry-up just before breakout; **bypasses extension filters** |

Cheat & Livermore & cup-handle are **not yet implemented** — Phase 5.

## 5. Current codebase (already built & tested on synthetic)

```
sepa/config.py      thresholds, account/risk, paths, telegram (DONE)
sepa/db.py          SQLite schema + access (DONE)
sepa/ingest.py      SEC universe + EDGAR fundamentals + yfinance prices + synthetic seed
                    (CODE WRITTEN, network paths NEEDS-LIVE-VERIFY)
sepa/providers.py   DataProvider seam: Synthetic, DB, yfinance/EODHD stubs (DONE)
sepa/indicators.py  MAs, 52w hi/lo, swing points, contractions (DONE)
sepa/screens.py     Trend Template(8), stage classifier, RS rank, fundamentals (DONE)
sepa/patterns.py    VCP + power play + footprint (DONE; other setups pending)
sepa/classify.py    3-axis → tier; power-play bypass (DONE)
sepa/state.py       move-in/out transition diff (DONE)
sepa/alerter.py     chart render + card + dedupe + telegram send (DONE; telegram NEEDS-LIVE-VERIFY)
sepa/run_daily.py   DB-backed orchestrator (DONE on synthetic)
sepa/writer.py      optional xlsx mirror of the watch lists (DONE)
```

What is proven: full pipeline runs offline on a synthetic US universe, tiers
populate, diffs work, charts render, alert cards format, dedupe holds.
What is NOT proven: anything touching live network, and detector accuracy
against real charts.

## 6. Phases & acceptance gates

> A phase is done only when its gate passes FOR REAL (see CLAUDE.md test rules).

### Phase 0 — Repo hygiene & harness
Add `pytest`, `requirements.txt`/`pyproject`, `Makefile` (`make test`,
`make run`, `make ingest`), matplotlib `Agg`, logging config.
**Gate:** `make test` runs the existing suite green; `make run` does an offline
synthetic run clean. Paste output.

### Phase 1 — Live data spine (the real work begins here)
Implement & harden the real providers in `ingest.py`:
- yfinance price loader: batched, retried, timeout, per-ticker soft-fail.
- EDGAR fundamentals: map XBRL concepts → schema; handle filer-varying concept
  names; rate-limit ≤10 req/s; real User-Agent.
Start with ~300 liquid names.
**Gate (USER runs on mini PC):** prices for 20 hand-picked names match a
reference (e.g. TradingView close) within rounding; fundamentals (EPS/sales/
ROE) sane for those 20. Mark `NEEDS-LIVE-VERIFY` until user confirms.

### Phase 2 — Funnel calibration (the make-or-break phase)
Run L0–L5 nightly on the live ~300. Hand-check stage labels, TT scores, RS,
and VCP footprints against charts of ~20 names the user knows.
**Gate:** ≥ ~90% agreement between the engine's stage/setup calls and the
user's chart read on the sample. Tune thresholds in `config.py` until it
agrees. This is the phase that determines whether the product "actually works."

### Phase 3 — Watch-list state & lifecycle
Persist the five lists; wire Positions (manual entry of fills → follow-through/
squat status, trailing-stop reference) and Reset Watch (stopped-out →
failure-reset monitor). Stage-transition alerts on owned/watched names.
**Gate:** simulate a multi-day sequence (scripted price paths) and assert a
name walks Watch→Buy Alert→Buy Ready→Positions→Reset Watch correctly. Golden test.

### Phase 4 — Alerts hardened
Telegram card (chart + why + plan + TV link), dedupe, heartbeat, and a daily
digest message. Failure of Telegram must not break the scan.
**Gate (USER on mini PC):** a real Buy-Ready event delivers a correct card to
the user's phone; a second run does not re-alert. `NEEDS-LIVE-VERIFY`.

### Phase 5 — Remaining detectors
Implement cheat (4-phase), Livermore PP, cup-with-handle. Each with positive +
negative fixtures. Add the ranked-entry set (low-cheat/cheat/pivot) to the
setup object.
**Gate:** unit tests pass; on the live sample each newly-detected setup is
hand-confirmed on the chart by the user (no egregious false positives).

### Phase 6 — Ops & resilience
systemd service+timer, log rotation, DB vacuum, run-died heartbeat, resumable
mid-run recovery, scale test to full ~3,000 universe within time/RAM budget.
**Gate:** kill a run mid-way; re-run completes clean with no dup alerts. Full
universe scan finishes within budget on the mini PC. `NEEDS-LIVE-VERIFY`.

### Phase 7 — AI validator (last, smallest)
One Claude API call per NEW Buy Ready: inputs = chart image + computed metrics
+ recent filing/news headlines; output = structured `{verdict: CONFIRM|CAUTION|
REJECT, reason}`. Verdict can downgrade/suppress an alert, never create one.
Goes on the card.
**Gate:** with a stubbed/mocked LLM response, a REJECT suppresses the alert and
a CONFIRM passes it through; cost per night logged. Live check `NEEDS-LIVE-VERIFY`.

### Phase 8 — Paper period (defines "working")
Run live for 4–8 weeks. Log every alert and what the stock did after. No money.
**Gate:** review shows alerts are sane (followed-through rate, false-positive
rate acceptable to the user). Only now is v1 "working." v2 discussion may begin.

## 7. Explicitly out of scope for v1
Intraday data, auto-execution/broker APIs, global/non-US markets, web/mobile UI,
options, backtesting framework (informal validation only in v1). Each is a
post-v1 candidate, not v1 work.

## 8. Open questions to confirm with user (track in PROGRESS.md)
- Universe size for Phase 1 start (suggest S&P 1500 or a liquidity-filtered list)?
- Account size & risk-% for live position sizing (currently config defaults)?
- Market-tone gauge: manual switch for v1, or compute from breadth? (suggest
  manual to start, automate later.)
