"""Decide which watch list a stock belongs on, from the three conviction axes.
This is the 'a good company is not always a good stock' logic."""
from . import config as C
from .patterns import Setup


def decide_tier(stage: int, tt_score: int, rs: int | None,
                funda_pass: bool, setup: Setup | None,
                market_tone: str) -> tuple[str | None, str]:
    """Returns (tier or None, reason)."""
    rs = rs or 0
    is_power = setup is not None and setup.type == "Power Play"

    # Power plays are designed to look "too extended" — they bypass the
    # Trend Template extension guards, gating on RS + the thrust/flag signature.
    if is_power:
        if rs < C.RS_MIN:
            return None, f"power play but RS {rs} < {C.RS_MIN}"
        if market_tone == "Correction":
            return None, "market in correction — no new buys"
        tier = "Buy Ready" if (setup.buyable and funda_pass) else "Buy Alert"
        if market_tone == "Under pressure" and tier == "Buy Ready":
            tier = "Buy Alert"
        return tier, f"POWER PLAY RS{rs} {'fund✓' if funda_pass else 'fund?'} {setup.footprint}"

    # hard technical gate for everything else: only Stage 2 names are candidates
    if stage != 2 or tt_score < 5 or rs < C.RS_MIN:
        return None, f"not a Stage-2 leader (stage {stage}, TT {tt_score}/8, RS {rs})"

    technical_strong = tt_score >= 7
    aligned = funda_pass and technical_strong

    tier = None
    if setup and setup.buyable and aligned:
        tier = "Buy Ready"
    elif setup and aligned:
        tier = "Buy Alert"            # setup formed but not in buy zone yet
    elif setup or aligned:
        tier = "Buy Alert" if setup else "Watch"
    else:
        tier = "Watch"                # stage-2 leader, no mature setup -> radar

    # market-tone gate (third axis): degrade in weak tape
    if market_tone == "Correction":
        return None, "market in correction — no new buys"
    if market_tone == "Under pressure" and tier == "Buy Ready":
        tier = "Buy Alert"

    reason = f"stage2 TT{tt_score}/8 RS{rs} " + \
             ("fund✓ " if funda_pass else "fund✗ ") + \
             (f"{setup.type}{'(buyable)' if setup.buyable else ''}" if setup else "no setup")
    return tier, reason
