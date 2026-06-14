"""Day-over-day state. This is the heart of 'move in / move out': we diff
today's tier assignments against the last run and label every change."""
import json
from . import config as C

ORDER = {name: i for i, name in enumerate(C.TIER_ORDER)}


def load_state(path=C.STATE_PATH) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def save_state(state: dict, path=C.STATE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, default=str))


def transitions(prev: dict, curr: dict) -> dict[str, str]:
    """Label each ticker: NEW, PROMOTED, DEMOTED, SAME, or DROPPED."""
    out = {}
    for t, info in curr.items():
        if t not in prev:
            out[t] = "NEW"
        else:
            old, new = prev[t]["tier"], info["tier"]
            if old == new:
                out[t] = "SAME"
            elif ORDER.get(new, -1) > ORDER.get(old, -1):
                out[t] = "PROMOTED"
            else:
                out[t] = "DEMOTED"
    for t in prev:
        if t not in curr:
            out[t] = "DROPPED"      # fell off all watch lists -> move out
    return out
