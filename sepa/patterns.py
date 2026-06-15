"""Pattern detectors. Each returns a Setup or None. The Setup carries the
pivot, entry/stop, and the Minervini-style footprint string."""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from . import config as C
from .indicators import swing_points, contractions


@dataclass
class Setup:
    type: str
    pivot: float
    entry: float
    stop: float
    footprint: str
    buyable: bool                 # price within buy zone of pivot now
    base_weeks: int = 0
    n_contractions: int = 0
    vol_dryup: bool = False
    entry_type: str = "pivot"     # "pivot" | "cheat" | "low-cheat"
    notes: str = ""


# ---------------------------------------------------------------- VCP / 3C
def detect_vcp(df: pd.DataFrame) -> Setup | None:
    """Minervini VCP: >= 2 contractions each shallower, volume dries into pivot.
    Footprint: [wks]W [1st%]/[last%] [n]T"""
    base = df.iloc[-C.VCP_BASE_MAX_DAYS:]
    close = base["close"].to_numpy()
    if len(close) < 20:
        return None
    depths = contractions(close, k=3)
    if len(depths) < C.VCP_MIN_CONTRACTIONS:
        return None
    depths = depths[-4:]
    if not (depths[-1] <= C.VCP_FINAL_TIGHTNESS and depths[-1] <= max(depths) * 0.7):
        return None
    vol = base["volume"].to_numpy()
    if vol[-len(vol)//3:].mean() >= C.VCP_VOL_DRYUP * vol.mean():
        return None
    highs, _ = swing_points(close, k=3)
    if not highs:
        return None
    pivot = float(np.max(close))
    last = float(close[-1])
    buyable = pivot * (1 - C.BUY_ZONE_WIDTH) <= last <= pivot * (1 + C.BUY_ZONE_WIDTH)
    stop = min(close[-int(len(close)/4):]) * 0.99
    weeks = max(1, len(close) // 5)
    fp = f"{weeks}W {int(round(max(depths)*100))}/{int(round(depths[-1]*100))} {len(depths)}T"
    return Setup("VCP / 3C", round(pivot, 2), round(max(pivot, last), 2), round(stop, 2),
                 fp, buyable, weeks, len(depths), True,
                 "pivot", "contractions " + "/".join(f"{d*100:.0f}" for d in depths))


# ---------------------------------------------------------------- Power Play
def detect_power_play(df: pd.DataFrame) -> Setup | None:
    """Minervini Power Play (high-tight flag): +100% in <8wks from dormancy,
    then flag <= 25% deep, volume dries into flag. Bypasses extension filters."""
    close = df["close"].to_numpy()
    vol = df["volume"].to_numpy()
    if len(close) < C.PP_THRUST_DAYS + C.PP_FLAG_MAX_DAYS + 20:
        return None
    flag_len = None
    gain = 0.0
    w0 = 0
    for fl in range(C.PP_FLAG_MIN_DAYS, C.PP_FLAG_MAX_DAYS + 1):
        flag = close[-fl:]
        depth = (flag.max() - flag.min()) / flag.max()
        if depth > C.PP_FLAG_MAX_DEPTH:
            continue
        thrust_end = len(close) - fl
        _w0 = max(0, thrust_end - C.PP_THRUST_DAYS)
        thrust_lo = close[_w0:thrust_end].min()
        thrust_hi = close[_w0:thrust_end].max()
        if thrust_lo <= 0:
            continue
        _gain = thrust_hi / thrust_lo - 1
        if _gain < C.PP_THRUST_PCT:
            continue
        pre = close[max(0, _w0 - 60):_w0]
        if len(pre) > 10:
            rv = np.std(np.diff(np.log(pre)))
            if rv > C.PP_DORMANCY_VOL:
                continue
        if vol[-fl:].mean() >= vol[_w0:thrust_end].mean():
            continue
        flag_len = fl
        gain = _gain
        w0 = _w0
        break
    if flag_len is None:
        return None
    flag = close[-flag_len:]
    pivot = float(flag.max())
    last = float(close[-1])
    buyable = pivot <= last * (1 + C.BUY_ZONE_WIDTH) and last >= pivot * (1 - 0.05)
    stop = float(flag.min()) * 0.99
    return Setup("Power Play", round(pivot, 2), round(max(pivot, last), 2), round(stop, 2),
                 f"+{int(gain*100)}%/{(len(close)-flag_len-w0)}d flag {flag_len}d",
                 buyable, max(1, flag_len // 5), 1, True, "pivot",
                 "thrust then tight flag; extension filters bypassed")


# ---------------------------------------------------------------- Cup-with-Handle
def detect_cup_handle(df: pd.DataFrame) -> Setup | None:
    """Cup-with-handle: U-shaped base ending near left-side high, then a
    shallow low-volume handle (final VCP contraction) just under the rim.
    Handle high ≈ pivot; buy on handle breakout.

    Rules encoded:
    - Cup >= 7 weeks, depth 12-35% (not too shallow, not too deep)
    - Handle <= 8 weeks, depth <= 12% (shallower than the cup)
    - Handle stays in upper half of the cup
    - Volume dries in handle vs cup formation
    - Handle high is within 1-2% of the cup's right-side high (the rim)
    """
    close = df["close"].to_numpy()
    vol = df["volume"].to_numpy()
    n = len(close)
    if n < 60:
        return None

    # Scan handle lengths 5..40 bars
    for handle_len in range(5, min(40, n // 3)):
        handle = close[-handle_len:]
        handle_high = float(handle.max())
        handle_low = float(handle.min())
        handle_depth = (handle_high - handle_low) / handle_high

        # Handle must be shallow
        if handle_depth > C.CUP_HANDLE_MAX_DEPTH:
            continue

        # Cup body is everything before the handle
        cup_start = max(0, n - C.CUP_MAX_BARS)
        cup = close[cup_start: n - handle_len]
        if len(cup) < C.CUP_MIN_BARS:
            continue

        left_rim = float(cup[0])
        cup_low = float(cup.min())
        cup_depth = (left_rim - cup_low) / left_rim

        if not (C.CUP_MIN_DEPTH <= cup_depth <= C.CUP_MAX_DEPTH):
            continue

        # Right rim of cup should be within ~5% of left rim (recovery)
        right_rim = float(cup[-1])
        if right_rim < left_rim * (1 - C.CUP_RIM_TOLERANCE):
            continue

        # Handle must stay in upper half of the cup
        mid_cup = cup_low + (left_rim - cup_low) * 0.5
        if handle_low < mid_cup:
            continue

        # Handle high ≈ pivot (within buy zone of the rim)
        pivot = handle_high
        if pivot < right_rim * (1 - C.CUP_RIM_TOLERANCE):
            continue

        # Volume: handle avg must be lower than cup avg
        cup_vol = vol[cup_start: n - handle_len]
        handle_vol = vol[-handle_len:]
        if handle_vol.mean() >= C.VCP_VOL_DRYUP * cup_vol.mean():
            continue

        last = float(close[-1])
        buyable = pivot * (1 - C.BUY_ZONE_WIDTH) <= last <= pivot * (1 + C.BUY_ZONE_WIDTH)
        stop = handle_low * 0.99
        cup_weeks = max(1, (n - handle_len - cup_start) // 5)
        handle_weeks = max(1, handle_len // 5)
        fp = f"{cup_weeks}W cup {int(cup_depth*100)}% deep / {handle_weeks}W handle {int(handle_depth*100)}%"
        return Setup("Cup-with-Handle",
                     round(pivot, 2), round(max(pivot, last), 2), round(stop, 2),
                     fp, buyable, cup_weeks + handle_weeks, 1, True, "pivot",
                     f"cup {int(cup_depth*100)}% left-to-right rim ≈{int(abs(right_rim/left_rim-1)*100)}% gap")

    return None


# ---------------------------------------------------------------- Cheat (4-phase)
def detect_cheat(df: pd.DataFrame) -> Setup | None:
    """Minervini Cheat (4-phase): A downtrend → B uptrend (recoup 33-50% of A)
    → C pause/plateau 5-10% (ideally a shakeout) → D breakout above C plateau high.

    The 'cheat' entry is buying within the C phase before the D breakout,
    giving a better risk/reward than waiting for the D pivot.

    Algorithm:
      - C_high = most recent swing high  (the D breakout level / pivot)
      - C_low  = deepest low after C_high (the plateau floor)
      - A_low  = deepest low before C_high (the bottom of the prior decline)
      - A_start= highest high before A_low (the pre-A peak)
      - b_recoup = (C_high - A_low) / (A_start - A_low)

    VERIFY-AGAINST-BOOK: exact recoup % and plateau depth thresholds.
    """
    close = df["close"].to_numpy()
    n = len(close)
    if n < C.CHEAT_MIN_BARS:
        return None

    window = close[-C.CHEAT_LOOKBACK:]
    highs, lows = swing_points(window, k=3)

    if len(highs) < 2 or len(lows) < 2:
        return None

    # C high = most recent swing high (= D breakout pivot)
    c_high_idx, c_high = highs[-1]

    # C low = deepest low after C high (the plateau floor)
    c_lows_after = [(i, p) for i, p in lows if i > c_high_idx]
    if not c_lows_after:
        return None
    c_low_idx, c_low = min(c_lows_after, key=lambda x: x[1])

    plateau_depth = (c_high - c_low) / c_high
    if not (C.CHEAT_PLATEAU_MIN <= plateau_depth <= C.CHEAT_PLATEAU_MAX):
        return None

    # A low = deepest low before C high (bottom of prior downtrend / B start)
    lows_before = [(i, p) for i, p in lows if i < c_high_idx]
    if not lows_before:
        return None
    a_low_idx, a_low = min(lows_before, key=lambda x: x[1])

    # A start = highest high before A low (the peak before the A decline)
    highs_before_a = [(i, p) for i, p in highs if i < a_low_idx]
    if not highs_before_a:
        return None
    a_start_idx, a_start = max(highs_before_a, key=lambda x: x[1])

    # B recoup: how much of the A decline did the B uptrend recover?
    a_decline = a_start - a_low
    if a_decline <= 0:
        return None
    b_recoup = (c_high - a_low) / a_decline
    if not (C.CHEAT_B_RECOUP_MIN <= b_recoup <= C.CHEAT_B_RECOUP_MAX):
        return None

    # Price must currently be in the C plateau band
    last = float(close[-1])
    in_plateau = c_low <= last <= c_high * (1 + 0.01)
    if not in_plateau:
        return None

    near_low_cheat = last <= c_low * (1 + C.CHEAT_LOW_ENTRY_ZONE)
    entry_type = "low-cheat" if near_low_cheat else "cheat"
    pivot = float(c_high)
    stop = float(c_low) * 0.98
    weeks = max(1, len(window) // 5)
    fp = (f"{weeks}W cheat: A-{int((1-a_low/a_start)*100)}% "
          f"B+{int(b_recoup*100)}% C-{int(plateau_depth*100)}%")
    return Setup("Cheat", round(pivot, 2), round(last, 2), round(stop, 2),
                 fp, True, weeks, 0, False, entry_type,
                 f"phase ABCD: recoup={b_recoup:.0%} plateau={plateau_depth:.0%}")


# ---------------------------------------------------------------- Livermore Pivot Point
def detect_livermore_pp(df: pd.DataFrame) -> Setup | None:
    """Livermore Pivot Point (LP): after a downtrend, TWO reaction (pullback)
    highs form. Buy on breakout above the 2nd reaction high.

    Pattern: downtrend → reaction 1 (first bounce high) → new low →
             reaction 2 (second bounce high, higher or equal to reaction 1) →
             price breaks above reaction 2 high = pivot.

    VERIFY-AGAINST-BOOK: exact LP rules regarding reaction symmetry.
    """
    close = df["close"].to_numpy()
    n = len(close)
    if n < C.LPP_MIN_BARS:
        return None

    window = close[-C.LPP_LOOKBACK:]
    highs, lows = swing_points(window, k=3)

    if len(highs) < 2 or len(lows) < 2:
        return None

    # Find two consecutive reaction highs with a lower low between them
    # Work backwards through swing highs
    for j in range(len(highs) - 1, 0, -1):
        r2_idx, r2_high = highs[j]
        r1_candidates = [(i, p) for i, p in highs if i < r2_idx]
        if not r1_candidates:
            continue
        r1_idx, r1_high = r1_candidates[-1]

        # Find the low between r1 and r2
        mid_lows = [(i, p) for i, p in lows if r1_idx < i < r2_idx]
        if not mid_lows:
            continue
        mid_low_idx, mid_low = min(mid_lows, key=lambda x: x[1])

        # Mid-low must be below both reaction highs (it's the trough between bounces)
        if mid_low >= min(r1_high, r2_high):
            continue

        # The downtrend before r1: there must be a significant decline into r1
        pre_r1_lows = [(i, p) for i, p in lows if i < r1_idx]
        if not pre_r1_lows:
            continue
        pre_low_idx, pre_low = min(pre_r1_lows, key=lambda x: x[1])

        pre_high_candidates = [(i, p) for i, p in highs if i < pre_low_idx]
        if not pre_high_candidates:
            continue
        prior_high_idx, prior_high = pre_high_candidates[-1]

        prior_decline = (prior_high - pre_low) / prior_high
        if prior_decline < C.LPP_MIN_PRIOR_DECLINE:
            continue

        # R2 must be >= R1: the second reaction shows improving momentum
        # (downtrend is breaking). A lower R2 means the downtrend is still intact.
        if r2_high < r1_high * 0.97:
            continue

        # Current price must not have fallen far below R2 (still near the pivot)
        last = float(close[-1])
        if last < r2_high * (1 - 2 * C.BUY_ZONE_WIDTH):
            continue

        # Pivot = r2_high (buy above 2nd reaction high)
        pivot = float(r2_high)
        buyable = pivot * (1 - C.BUY_ZONE_WIDTH) <= last <= pivot * (1 + C.BUY_ZONE_WIDTH)

        # Stop below mid-low (the trough between the two reactions)
        stop = float(mid_low) * 0.99
        weeks = max(1, len(window) // 5)
        fp = (f"{weeks}W LP: R1={r1_high:.2f} low={mid_low:.2f} "
              f"R2={r2_high:.2f} pivot={pivot:.2f}")
        return Setup("Livermore PP",
                     round(pivot, 2), round(max(pivot, last), 2), round(stop, 2),
                     fp, buyable, weeks, 2, False, "pivot",
                     f"two-reaction PP, prior decline {prior_decline:.0%}")

    return None


# ---------------------------------------------------------------- dispatcher
def detect_setups(df: pd.DataFrame) -> Setup | None:
    """Return the highest-priority setup present.
    Priority: Power Play > VCP > Cup-with-Handle > Cheat > Livermore PP."""
    from dataclasses import replace
    s = (detect_power_play(df) or
         detect_vcp(df) or
         detect_cup_handle(df) or
         detect_cheat(df) or
         detect_livermore_pp(df))
    if s is None:
        return None
    # Hard cap: stop never wider than MAX_STOP_PCT below entry (Minervini: 7-10%)
    floor = round(s.entry * (1 - C.MAX_STOP_PCT), 2)
    if s.stop < floor:
        s = replace(s, stop=floor)
    # Extension gate: if price has run more than BUY_ZONE_WIDTH past the pivot,
    # this is a chase — mark not-buyable regardless of what the detector said.
    # Power Play explicitly bypasses extension (PP by design looks "extended"
    # vs its pre-thrust base — that is the pattern, not a flaw).
    last = float(df["close"].iloc[-1])
    if s.type != "Power Play" and s.pivot > 0:
        ext = last / s.pivot - 1
        if ext > C.BUY_ZONE_WIDTH:
            s = replace(s, buyable=False,
                        notes=(s.notes + f" [EXTENDED +{ext*100:.0f}%]").strip())
    return s
