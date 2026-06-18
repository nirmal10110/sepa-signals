"""Decide which watch list a stock belongs on, from the three conviction axes.
This is the 'a good company is not always a good stock' logic.

Two highest tiers:
  Buy Ready    — all Potential Buy criteria + last close ≥ pivot + volume ≥ BREAKOUT_VOL_MULT × 50d avg
  Potential Buy — good setup + in buy zone, no confirmed breakout required
"""
from __future__ import annotations
import pandas as pd
from . import config as C
from .patterns import Setup


def breakout_confirmed(df: pd.DataFrame | None, setup: Setup | None) -> bool:
    """Return True when the most recent bar closes at or above the pivot AND volume
    is at least BREAKOUT_VOL_MULT × the 50-day average (computed from bars BEFORE today).

    Why exclude today from the average: we want to compare today's surge against
    the pre-breakout baseline, not dilute the reference with the event itself.
    """
    if df is None or setup is None or setup.pivot <= 0 or len(df) < 2:
        return False
    last_close = float(df["close"].iloc[-1])
    last_vol   = float(df["volume"].iloc[-1])
    n = min(50, len(df) - 1)
    avg_vol = float(df["volume"].iloc[-(n + 1):-1].mean())
    if avg_vol <= 0:
        return False
    # Round last_close to 2 decimal places (cents) to match the stored pivot precision.
    return round(last_close, 2) >= setup.pivot and last_vol >= C.BREAKOUT_VOL_MULT * avg_vol


# Keep the private alias so any direct test imports don't break.
_breakout_confirmed = breakout_confirmed


def decide_tier(stage: int, tt_score: int, rs: int | None,
                funda_pass: bool, setup: Setup | None,
                market_tone: str,
                df: pd.DataFrame | None = None,
                funda_note: str = "") -> tuple[str | None, str]:
    """Returns (tier or None, reason).

    Tier hierarchy (highest conviction first):
      Buy Ready    — buyable setup + confirmed breakout (close ≥ pivot + vol surge)
      Potential Buy — buyable setup, no breakout confirmation required
      Buy Alert    — setup present but not yet in buy zone, or market under pressure
      Watch        — Stage-2 leader on radar, no mature setup yet
      Momentum     — all technical criteria met but fundamental screen failed;
                     alerts fire only on confirmed breakout (not on tier entry)
    """
    rs = rs or 0
    is_power = setup is not None and setup.type == "Power Play"

    # Power plays bypass extension filters (by design they look "extended").
    if is_power:
        if rs < C.RS_MIN:
            return None, f"power play but RS {rs} < {C.RS_MIN}"
        if market_tone == "Correction":
            return None, "market in correction — no new buys"
        if setup.buyable and funda_pass:
            tier = "Buy Ready" if breakout_confirmed(df, setup) else "Potential Buy"
        else:
            tier = "Buy Alert"
        if market_tone == "Under pressure" and tier in ("Buy Ready", "Potential Buy"):
            tier = "Buy Alert"
        return tier, f"POWER PLAY RS{rs} {'fund✓' if funda_pass else 'fund?'} {setup.footprint}"

    # Hard technical gate for everything else: only Stage 2 names.
    if stage != 2 or tt_score < 5 or rs < C.RS_MIN:
        return None, f"not a Stage-2 leader (stage {stage}, TT {tt_score}/8, RS {rs})"

    technical_strong = tt_score >= 7
    aligned = funda_pass and technical_strong

    tier: str | None = None
    if setup and setup.buyable and aligned:
        tier = "Buy Ready" if breakout_confirmed(df, setup) else "Potential Buy"
    elif setup and aligned:
        tier = "Buy Alert"            # setup formed but not in buy zone yet
    elif setup or aligned:
        tier = "Buy Alert" if setup else "Watch"
    else:
        tier = "Watch"                # Stage-2 leader, no mature setup → radar

    # Market-tone gate (third axis): degrade in weak tape.
    if market_tone == "Correction":
        return None, "market in correction — no new buys"
    if market_tone == "Under pressure" and tier in ("Buy Ready", "Potential Buy"):
        tier = "Buy Alert"

    # Momentum override: technically strong (TT≥MOMENTUM_TT_MIN, RS≥MOMENTUM_RS_MIN)
    # but fundamentally disqualified.  Replaces Watch/Buy Alert so these names appear
    # in their own report section rather than cluttering the SEPA watchlists.
    # Alerts fire separately (only when a confirmed breakout is detected in run_daily).
    if not funda_pass and tt_score >= C.MOMENTUM_TT_MIN and rs >= C.MOMENTUM_RS_MIN:
        fund_detail = funda_note or f"funda score below {C.FUND_MIN_SCORE}"
        reason = (f"MOMENTUM stage2 TT{tt_score}/8 RS{rs} fund✗({fund_detail}) "
                  + (f"{setup.type}{'(buyable)' if setup.buyable else ''}" if setup
                     else "no setup"))
        return "Momentum", reason

    reason = (f"stage2 TT{tt_score}/8 RS{rs} "
              + ("fund✓ " if funda_pass else "fund✗ ")
              + (f"{setup.type}{'(buyable)' if setup.buyable else ''}" if setup else "no setup"))
    return tier, reason
