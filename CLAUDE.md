# CLAUDE.md — Engineering Contract for SEPA Signals

You are building a **personal stock-signals platform** that runs on the user's
**mini PC, 24/7**. It encodes Mark Minervini's SEPA methodology as a
deterministic nightly funnel and sends Telegram alerts when a stock becomes
buyable. Read `PLAN.md` for the what; this file is the *how*. Obey it on every
task.

---

## Prime directives

1. **Scripts decide, AI reviews.** All analysis is deterministic Python.
   The only AI in the runtime is a single bounded validator that runs LAST,
   on already-filtered Buy-Ready candidates (Phase 7). Never push analysis
   logic into the AI layer. The AI can demote an alert, never create one.

2. **Never fake a result to pass a check.** Do not hardcode expected values,
   stub a function to return a passing value, loosen a test to make it green,
   or claim something works without running it. If something cannot be tested
   in your environment (e.g. live network), say so explicitly and mark it
   `NEEDS-LIVE-VERIFY` in `PROGRESS.md` — do not pretend it passed.

3. **Real data shape, always.** Synthetic data is allowed ONLY for offline
   pipeline testing and must live behind the existing `SyntheticProvider`.
   It must never leak into a real run path. Tests that matter run against the
   real provider schema.

4. **Update the docs every task.** At the end of EVERY task: update
   `PROGRESS.md` (check items, add discovered work, note blockers) and, if the
   plan changed, `PLAN.md`. A future agent must be able to resume from these
   two files alone. This is not optional.

---

## Test discipline (this is the point — do it precisely)

The user explicitly asked for precise testing while building. A phase is NOT
done until its acceptance gate in `PLAN.md` passes **for real**.

- **Write the test before or with the code**, never after as an afterthought.
- **Run it and paste the actual output** into your task summary. "Should work"
  is a failure. Show the command and its real result.
- **Unit-test every detector** with at least one positive and one negative
  fixture (a real-shaped series that SHOULD fire and one that should NOT).
  Geometric detectors produce false positives; the negative fixture is how you
  catch them.
- **Golden-file the funnel**: a fixed synthetic universe must always produce
  the same tier assignments. If a change moves a name between tiers,
  that must be intentional and noted, not silent.
- **Validate against reality**: Phase 2's gate is hand-checking stage labels
  and footprints against charts of ~20 names the user knows. Numbers that pass
  a unit test but disagree with the chart are wrong — fix the logic.
- **No network in CI-style tests.** Network paths (yfinance, EDGAR, Telegram)
  get thin integration tests the user runs ON THE MINI PC, clearly separated
  and marked `NEEDS-LIVE-VERIFY` until they confirm.

Run the full check before declaring a phase done:
```bash
python -m pytest -q          # all unit + golden tests must pass
python -m sepa.run_daily     # offline synthetic run must complete clean
```

---

## Mini-PC constraints (design for the target, not your sandbox)

- **OS**: assume headless Linux (systemd available). No GUI. Charts render
  headless via matplotlib `Agg` backend.
- **Resources**: modest CPU, limited RAM. A full universe scan (~3,000 names)
  must finish in minutes and stream per-ticker, not load everything into RAM.
  Batch price pulls; don't hold 3,000 DataFrames at once if avoidable.
- **Storage**: one SQLite file. No external DB server. Keep it WAL-mode and
  vacuum periodically.
- **Network is intermittent and rate-limited.** Every external call needs a
  timeout, a retry-with-backoff, and graceful per-ticker failure (one bad
  ticker must never abort the run). SEC requires a real User-Agent and ~10
  req/s courtesy cap — respect it.
- **Idempotent + resumable.** A run that dies mid-way must be safe to re-run.
  Use upserts (already the pattern). Never duplicate alerts — the dedupe table
  is sacred.
- **Scheduling**: deliver `systemd` service + timer units, not a cron one-liner.
  The run must log to a file and emit a heartbeat the user can see.

---

## Code standards

- Pure functions for all analysis (input DataFrame/dict → output value). Side
  effects (DB, network, Telegram) isolated in `db.py`, `ingest.py`, `alerter.py`.
- All thresholds live in `config.py`. Never inline a magic number in a detector.
- Type hints on public functions. Docstring states what Minervini rule it encodes.
- Fail loud in analysis, fail soft in I/O: a bad threshold should raise; a bad
  network response should log-and-skip.
- Keep the provider seam clean: the engine only ever talks to a `DataProvider`.
  Swapping Synthetic ↔ DB ↔ live must change nothing downstream.

---

## What "done" means for v1

Not "code exists." v1 is done when, on the user's mini PC: it ingests real US
data nightly, runs the full funnel, maintains the five watchlists with
move-in/out, sends a correct Telegram card on a real Buy-Ready event, and has
survived a **4–8 week paper-trading log** showing the alerts are sane. Until
the paper period passes, v1 is "feature-complete," not "working." Never
describe it as working before then. v2 (auto-execution) is not to be started.

---

## Boundaries

- This is a personal decision-support tool, not investment advice and not an
  auto-trader (in v1). Do not add order execution. Do not weaken risk limits.
- If asked to bypass test discipline or ship untested code, refuse and explain.
- When uncertain whether a setup definition matches the book, flag it in
  `PROGRESS.md` as `VERIFY-AGAINST-BOOK` rather than guessing silently.
