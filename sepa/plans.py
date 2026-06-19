"""Trade plan calculations: entry, stop, target, position size.

The stop floor enforces a minimum cushion between entry and stop so that
tight-pattern stops (flags, cheat entries) aren't blown out by normal
intraday noise before a thesis can play out.
"""
from . import config as C


def apply_stop_floor(entry: float, computed_stop: float) -> dict:
    """Enforce a minimum STOP_MIN_PCT gap between stop and entry.

    Tight formations — especially Power Play flags — can produce stops within
    2-3% of entry. That's too close to survive normal intraday noise. Taking
    min() pushes the stop lower when it's too tight, giving a tradeable cushion
    at the cost of needing slightly larger size to maintain the same dollar risk.
    The 3:1 R:R target is recalculated from the corrected stop.
    """
    stop = round(min(computed_stop, entry * (1.0 - C.STOP_MIN_PCT)), 2)
    risk_pts = entry - stop
    target = round(entry + 3.0 * risk_pts, 2)
    stop_pct = (stop - entry) / entry if entry > 0 else 0.0
    return {
        "stop": stop,
        "target": target,
        "stop_pct": stop_pct,
        "risk_reward": 3.0,
    }
