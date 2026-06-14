# SEPA Signals Engine

Automates the Minervini watch list: ingests daily data, scores every stock on
the three conviction axes (fundamental / technical / market), detects setups,
classifies each name into **Watch → Buy Alert → Buy Ready**, diffs against
yesterday to **move stocks in and out**, and writes it all into
`SEPA_Watchlist.xlsx` with the changes highlighted.

## Pipeline (run nightly after the close)

```
providers  ->  indicators  ->  RS rank (cross-universe)
           ->  stage + trend template + fundamentals
           ->  pattern detection (VCP, power play)
           ->  tier decision (3-axis + market gate)
           ->  diff vs yesterday (NEW / PROMOTED / DEMOTED / DROPPED)
           ->  write workbook (formulas preserved, rows highlighted)
```

## The one seam you implement to go live

Everything is real except the data feed — this sandbox can't reach providers.
In `sepa/providers.py` swap `SyntheticProvider` for `YFinanceProvider`
(free, included as a stub) or `EODHDProvider` (recommended for global EOD +
fundamentals). Match the documented return schema and nothing downstream
changes.

```python
# run_daily.py
from sepa.providers import YFinanceProvider
run(provider=YFinanceProvider(my_ticker_list))
```

## Run

```bash
pip install pandas numpy openpyxl
python -m sepa.run_daily          # updates data/SEPA_Watchlist.xlsx
```

## Layout

| file | role |
|---|---|
| `config.py` | every threshold (account, risk, RS, VCP, power play, market tone) |
| `providers.py` | data layer + synthetic demo + real-provider stubs |
| `indicators.py` | MAs, 52w hi/lo, swing points, contractions |
| `screens.py` | Trend Template (8), stage classifier, RS rank, fundamentals |
| `patterns.py` | VCP (+footprint+pivot), power play; `Setup` object |
| `classify.py` | three-axis → tier; power-play extension bypass |
| `state.py` | persistence + move-in/move-out transition diff |
| `writer.py` | updates the three tier sheets, preserves formulas, highlights |
| `run_daily.py` | orchestrator / entry point |

The engine manages only the three watch-list tabs. **Positions** and **Reset
Watch** stay user-managed (the manual/auto boundary we drew).

## Honest scope

Real & tested: stage, trend template, RS ranking, fundamentals, VCP + power
play detection, tier logic, the diff engine, and the Excel writer.

Scaffolded (clear extension points): cheat / Livermore / cup-with-handle
detectors (add to `patterns.py` beside VCP), the squat / failure-reset monitors,
and a real market-tone gauge (currently a config switch). Detector thresholds
are first-pass — backtest and tune against your own data before trusting size.
