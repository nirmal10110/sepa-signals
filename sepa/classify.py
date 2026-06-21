"""Decide which watch list a stock belongs on, from the three conviction axes.
This is the 'a good company is not always a good stock' logic.

Two highest tiers:
  Buy Ready    — all Potential Buy criteria + last close ≥ pivot + volume ≥ BREAKOUT_VOL_MULT × 50d avg
  Potential Buy — good setup + in buy zone, no confirmed breakout required
"""
from __future__ import annotations
import logging
import pandas as pd
from . import config as C
from .patterns import Setup
from .indicators import hi_lo_52w, ext_from_200
from .screens import is_merger_arb

log = logging.getLogger("sepa.classify")


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


def pivot_sanity_check(setup: Setup | None, df: pd.DataFrame | None,
                       ticker: str = "") -> tuple[bool, str, str]:
    """Guard against a pivot computed from corrupted or stale price data.

    Returns (violated, kind, note):
      kind == "corrupted" — pivot sits above the real 52-week high by more
        than PIVOT_SANITY_MAX_ABOVE_52WK (a bad price-data join fabricating
        an impossible pivot — this is how GRC's $86.74 pivot got through
        against a true $72.16 ATH).
      kind == "stale" — pivot sits more than (1 - PIVOT_STALE_BELOW_PRICE)
        below the current close (the stock already ran past this base).
    """
    if setup is None or setup.pivot <= 0 or df is None or df.empty:
        return False, "", ""
    tag = ticker or "?"
    hi, _ = hi_lo_52w(df)
    if hi > 0 and setup.pivot > hi * C.PIVOT_SANITY_MAX_ABOVE_52WK:
        note = (f"{tag}: pivot ${setup.pivot:.2f} exceeds 52wk high ${hi:.2f} "
                "— data corruption suspected, signal suppressed")
        log.critical(note)
        return True, "corrupted", note
    close = float(df["close"].iloc[-1])
    if close > 0 and setup.pivot < close * C.PIVOT_STALE_BELOW_PRICE:
        note = (f"{tag}: pivot ${setup.pivot:.2f} is more than "
                f"{(1 - C.PIVOT_STALE_BELOW_PRICE) * 100:.0f}% below current price "
                f"${close:.2f} — stock already ran, promotion suppressed")
        log.warning(note)
        return True, "stale", note
    return False, "", ""


def _apply_sanity_caps(tier: str | None, setup: Setup | None,
                       df: pd.DataFrame | None, ticker: str = "") -> tuple[str | None, str]:
    """Cap the tier at Watch when the pivot is corrupted/stale, or the price
    looks M&A-pinned. Returns (possibly-capped tier, reason suffix)."""
    if tier is None:
        return tier, ""
    violated, _kind, note = pivot_sanity_check(setup, df, ticker)
    if violated:
        return "Watch", " [" + note + "]"
    # M&A pinning is a sustained, multi-month phenomenon — require a full
    # year of history before trusting the signal. This also keeps the check
    # from colliding with a genuinely tight pre-breakout base (VCP final leg,
    # Power Play flag), which is short-lived and arises from a real prior
    # advance, not from being anchored to a deal price for months.
    if df is not None and len(df) >= 252:
        flagged, cv = is_merger_arb(df)
        if flagged:
            note = (f"{ticker or '?'}: price appears M&A-pinned (CV={cv * 100:.1f}%) "
                    "— suppressing from buy tiers")
            log.warning(note)
            return "Watch", " [" + note + "]"
    return tier, ""


# Tiers that the climax-extension cap can demote, and where they land.
# Momentum has no lower rung of its own (it's a parallel category, not part
# of the main Buy ladder) — it is tagged climax-extended by the caller but
# its tier is left unchanged here.
_CLIMAX_DEMOTE = {"Buy Ready": "Potential Buy", "Potential Buy": "Buy Alert"}


def _apply_climax_cap(tier: str | None, df: pd.DataFrame | None) -> tuple[str | None, str]:
    """Demote a Buy Ready/Potential Buy tier one notch when price has run more
    than CLIMAX_EXTENSION_CAP above the 200SMA — blow-off territory, not a
    fresh breakout (STX +700%/1yr, DELL, ALAB all slipped through this gap)."""
    if tier not in _CLIMAX_DEMOTE or df is None or "sma200" not in df.columns:
        return tier, ""
    ext = ext_from_200(df)
    if ext <= C.CLIMAX_EXTENSION_CAP:
        return tier, ""
    new_tier = _CLIMAX_DEMOTE[tier]
    note = f" [CLIMAX RISK: +{ext * 100:.0f}% above 200SMA, {tier}->{new_tier}]"
    return new_tier, note


def decide_tier(stage: int, tt_score: int, rs: int | None,
                funda_pass: bool, setup: Setup | None,
                market_tone: str,
                df: pd.DataFrame | None = None,
                funda_note: str = "",
                ticker: str = "") -> tuple[str | None, str]:
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
        # TT gates apply even to Power Plays — extension filter is bypassed but
        # institutional conviction (TT score) must still meet the tier minimum.
        if tier == "Buy Ready" and tt_score < C.BUY_READY_TT_MIN:
            tier = "Potential Buy"
        if tier == "Potential Buy" and tt_score < C.POTENTIAL_BUY_TT_MIN:
            tier = "Buy Alert"
        tier, sanity_note = _apply_sanity_caps(tier, setup, df, ticker)
        tier, climax_note = _apply_climax_cap(tier, df)
        reason = (f"POWER PLAY RS{rs} {'fund✓' if funda_pass else 'fund?'} "
                  f"{setup.footprint}{sanity_note}{climax_note}")
        return tier, reason

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

    # TT minimum gates for tier promotion.
    if tier == "Buy Ready" and tt_score < C.BUY_READY_TT_MIN:
        tier = "Potential Buy"
    if tier == "Potential Buy" and tt_score < C.POTENTIAL_BUY_TT_MIN:
        tier = "Buy Alert"

    # Momentum override: technically strong (TT≥MOMENTUM_TT_MIN, RS≥MOMENTUM_RS_MIN)
    # but fundamentally disqualified.  Replaces Watch/Buy Alert so these names appear
    # in their own report section rather than cluttering the SEPA watchlists.
    # Alerts fire separately (only when a confirmed breakout is detected in run_daily).
    if (not funda_pass and tt_score >= C.MOMENTUM_TT_MIN and rs >= C.MOMENTUM_RS_MIN
            and tt_score >= C.POTENTIAL_BUY_TT_MIN):
        fund_detail = funda_note or f"funda score below {C.FUND_MIN_SCORE}"
        momentum_tier, sanity_note = _apply_sanity_caps("Momentum", setup, df, ticker)
        # Climax cap tags Momentum (climax_risk surfaces via run_daily's own
        # extension check) but has no lower rung to demote it to.
        reason = (f"MOMENTUM stage2 TT{tt_score}/8 RS{rs} fund✗({fund_detail}) "
                  + (f"{setup.type}{'(buyable)' if setup.buyable else ''}" if setup
                     else "no setup")
                  + sanity_note)
        return momentum_tier, reason

    tier, sanity_note = _apply_sanity_caps(tier, setup, df, ticker)
    tier, climax_note = _apply_climax_cap(tier, df)
    reason = (f"stage2 TT{tt_score}/8 RS{rs} "
              + ("fund✓ " if funda_pass else "fund✗ ")
              + (f"{setup.type}{'(buyable)' if setup.buyable else ''}" if setup else "no setup")
              + sanity_note + climax_note)
    return tier, reason
