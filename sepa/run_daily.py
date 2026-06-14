"""Nightly run on the mini PC:  python -m sepa.run_daily

DB-backed:  prices/fundamentals (SQLite) -> indicators -> RS rank
-> stage/trend-template/fundamentals -> patterns -> tier -> diff vs yesterday
-> persist signals/state/transitions -> Telegram alert on newly-buyable names.
"""
import logging
from datetime import date
from . import config as C
from . import db
from .providers import DBProvider
from .indicators import add_mas
from .screens import (trend_template, classify_stage, weighted_rs_return,
                      rank_rs, fundamental_screen)
from .patterns import detect_setups
from .classify import decide_tier
from .state import transitions
from . import alerter
from . import validator as val

log = logging.getLogger("sepa.run")

STAGE_NAME = {1: "Base", 2: "Advance", 3: "Top", 4: "Decline"}

# Stage transitions worth alerting when a name is in Positions or watchlist
_DANGER_TRANSITIONS = {(2, 3), (2, 4), (3, 4)}   # advance→topping/decline


def _check_stage_transitions(con, asof, stages_now: dict, prev_stages: dict):
    """Log + alert if an owned or watched name's stage deteriorated."""
    positions = {p["ticker"] for p in db.get_positions(con)}
    watched = set(db.prev_state(con).keys())
    monitored = positions | watched

    alerts = []
    for t in monitored:
        s_old = prev_stages.get(t)
        s_new = stages_now.get(t)
        if s_old is None or s_new is None or s_old == s_new:
            continue
        if (s_old, s_new) in _DANGER_TRANSITIONS:
            source = "positions" if t in positions else "watchlist_state"
            db.log_stage_transition(con, asof, t, s_old, s_new, source)
            alerts.append({"ticker": t, "from_stage": s_old, "to_stage": s_new,
                           "source": source})
    return alerts


def run(con=None, market_tone=None):
    con = con or db.connect()
    market_tone = market_tone or C.MARKET_TONE
    prov = DBProvider(con)
    tickers = prov.universe()
    asof = str(date.today())

    log.info("SEPA scan starting — %d tickers, tone=%s", len(tickers), market_tone)

    # pass 1: metrics + raw RS + cache histories (with MAs, for charts)
    hist, raw_rs = {}, {}
    for t in tickers:
        try:
            df = add_mas(prov.history(t))
        except Exception as e:
            log.warning("history failed %s: %s", t, e)
            continue
        if len(df) < 60:
            continue
        hist[t] = df
        raw_rs[t] = weighted_rs_return(df)

    rs_rank = rank_rs(raw_rs)                       # pass 2: cross-universe RS

    prev_st = db.prev_stages(con)                   # stage snapshot before this run
    prev = db.prev_state(con)
    done = db.checkpoint_get(con, asof)             # resumability: skip already-classified
    if done:
        log.info("resuming — %d tickers already classified today", len(done))

    curr, sigs, stages_now = {}, {}, {}
    for t, df in hist.items():                      # pass 3: classify
        if t in done:
            # Restore previously computed signal from the signals table
            row = con.execute("""SELECT tier, stage FROM signals
                WHERE ticker=? AND asof=?""", (t, asof)).fetchone()
            if row and row[0]:
                curr[t] = {"tier": row[0], "added": prev.get(t, {}).get("added", asof)}
                stages_now[t] = row[1]
            continue
        try:
            rs = rs_rank.get(t)
            tt, _ = trend_template(df, rs)
            stage, _ = classify_stage(df, tt)
            f_pass, f_score, f_note = fundamental_screen(prov.fundamentals(t))
            setup = detect_setups(df)
            if setup and setup.type == "Power Play":
                stage = 2
            stages_now[t] = stage
            tier, reason = decide_tier(stage, tt, rs, f_pass, setup, market_tone)
            sig = {"ticker": t, "stage": stage, "tt": tt, "rs": rs or 0, "funda": int(f_pass),
                   "setup": setup.type if setup else "—",
                   "footprint": setup.footprint if setup else "—",
                   "pivot": setup.pivot if setup else 0.0,
                   "entry": setup.entry if setup else 0.0,
                   "stop": setup.stop if setup else 0.0,
                   "buyable": bool(setup and setup.buyable),
                   "tier": tier or "", "reason": reason,
                   "meta": prov.meta(t)["summary"]}
            db.write_signal(con, asof, sig)
            db.checkpoint_done(con, asof, t)
            if tier:
                sigs[t] = sig
                curr[t] = {"tier": tier, "added": prev.get(t, {}).get("added", asof)}
        except Exception as e:
            log.warning("classify failed %s: %s", t, e)
    con.commit()

    # diff -> persist state + transitions
    trans = transitions(prev, curr)
    db.clear_state(con, [t for t in prev if t not in curr])
    for t, info in curr.items():
        db.set_state(con, t, info["tier"], info["added"], asof)
    for t, status in trans.items():
        if status != "SAME":
            frm = prev.get(t, {}).get("tier", "")
            to = curr.get(t, {}).get("tier", "")
            db.log_transition(con, asof, t, status, frm, to)
    con.commit()

    # stage-transition alerts for positions + watchlist
    stage_alerts = _check_stage_transitions(con, asof, stages_now, prev_st)
    if stage_alerts:
        for sa in stage_alerts:
            msg = (f"⚠️ STAGE CHANGE {sa['ticker']}: "
                   f"Stage {sa['from_stage']}→{sa['to_stage']} "
                   f"[{sa['source']}]")
            print(msg)
            log.warning(msg)
            alerter.send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, msg)
            db.mark_stage_transition_alerted(con, asof, sa["ticker"])
    con.commit()

    # alerts: newly Buy Ready (NEW or PROMOTED) -> AI validator -> Telegram, deduped
    buyable = [sigs[t] for t, s in trans.items()
               if s in ("NEW", "PROMOTED") and curr.get(t, {}).get("tier") == "Buy Ready"]

    # Phase 7: run AI validator on each candidate; REJECT suppresses, CAUTION annotates
    if buyable:
        verdicts = val.validate_batch(buyable, chart_dir=str(C.CHART_DIR))
        confirmed = []
        for sig in buyable:
            v = verdicts.get(sig["ticker"], {"verdict": "CONFIRM", "reason": ""})
            if v["verdict"] == "REJECT":
                log.warning("AI REJECT %s: %s", sig["ticker"], v["reason"])
                print(f"  AI REJECT {sig['ticker']}: {v['reason']}")
                continue
            sig = dict(sig)   # don't mutate the original
            if v["verdict"] == "CAUTION":
                sig["ai_note"] = f"⚠️ CAUTION: {v['reason']}"
            else:
                sig["ai_note"] = f"✅ AI CONFIRM: {v['reason']}"
            confirmed.append(sig)
        buyable = confirmed

    sent = alerter.process(con, buyable, hist, asof)

    # summary / heartbeat
    counts = {tier: sum(1 for v in curr.values() if v["tier"] == tier) for tier in C.TIER_ORDER}
    moves = {t: s for t, s in trans.items() if s != "SAME"}
    promotions = len([m for m in moves.values() if m in ("NEW", "PROMOTED")])
    hb = (f"SEPA scan {asof}: {counts.get('Buy Ready', 0)} Buy Ready, "
          f"{promotions} promotions, {len(sent)} alerts.")

    print(f"\n=== SEPA {asof} | tone {market_tone} | universe {len(hist)} ===")
    for tier in C.TIER_ORDER:
        print(f"  {tier:<10} {counts[tier]}")
    if stage_alerts:
        print(f"  stage alerts: {len(stage_alerts)}")
    print(f"  alerts sent: {len(sent)} -> {[t for t, _ in sent]}")
    print("  heartbeat:", hb)
    log.info("HEARTBEAT: %s", hb)

    # Nightly maintenance: clear checkpoint + WAL checkpoint + vacuum
    try:
        db.checkpoint_clear(con, asof)
        con.commit()     # commit before VACUUM — SQLite needs exclusive access
        db.vacuum(con)
        log.info("DB maintenance complete")
    except Exception as e:
        log.warning("DB maintenance failed: %s", e)

    return curr, trans, sent


if __name__ == "__main__":
    from .log_config import setup_logging
    setup_logging()
    run()
