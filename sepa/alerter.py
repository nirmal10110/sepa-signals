import matplotlib
matplotlib.use("Agg")  # headless mini-PC
"""Turns a 'newly buyable' signal into the Telegram card: an annotated chart
plus a plain-English 'why & what'. Dedupes so each setup alerts once."""
import logging
import time
from datetime import date
from . import config as C
from . import db

_log = logging.getLogger("sepa.alerter")


def render_chart(df, sig, path):
    """Local annotated chart: candles + 50/150/200 SMAs + pivot + stop lines."""
    import mplfinance as mpf
    import pandas as pd
    plot_df = df.tail(160).copy()
    plot_df.index = pd.DatetimeIndex(plot_df.index)
    mas = [c for c in ("sma50", "sma150", "sma200") if c in plot_df]
    add = []
    for c, col in zip(mas, ("#2962ff", "#ff9800", "#9c27b0")):
        add.append(mpf.make_addplot(plot_df[c], color=col, width=0.8))
    hlines = dict(hlines=[sig["pivot"], sig["stop"]],
                  colors=["#089981", "#f23645"], linestyle="--", linewidths=0.9)
    mpf.plot(plot_df, type="candle", style="yahoo", addplot=add, volume=True,
             hlines=hlines, figratio=(16, 9), figscale=1.1, tight_layout=True,
             title=f"\n{sig['ticker']}  {sig['setup']}  pivot {sig['pivot']}",
             savefig=dict(fname=path, dpi=130, bbox_inches="tight"))
    return path


def build_card(sig):
    """The 'clear picture of why & what'. Telegram Markdown."""
    plan_line = ""
    if sig["entry"] and sig["stop"] and sig["entry"] != sig["stop"]:
        risk_pts = sig["entry"] - sig["stop"]
        risk_pct = risk_pts / sig["entry"]
        shares = int(round((C.ACCOUNT_SIZE * C.RISK_PER_TRADE) / risk_pts))
        target = round(sig["entry"] + 3 * risk_pts, 2)     # 3:1 R:R target
        plan_line = (
            f"\n*Plan*  entry `{sig['entry']}` · stop `{sig['stop']}` "
            f"(-{risk_pct*100:.1f}%) · target `{target}` (3:1 R:R) "
            f"· size `{shares}` sh @ {C.RISK_PER_TRADE*100:.2f}% risk"
        )
    tt = sig.get("tt", 0)
    if isinstance(tt, bytes):
        tt = int.from_bytes(tt, "little")
    sig = {**sig, "tt": tt}
    tone = sig.get("market_tone", "—")
    ud = sig.get("ud_vol", 0)
    ud_tag = f"· vol ratio `{ud:.2f}` {'✅' if ud >= C.VOL_CONFIRM_RATIO else '⚠️'}" if ud else ""

    # 1-year return + 200 SMA extension + climax flag
    ret_1y  = sig.get("ret_1y")   # already in %, e.g. 150.0
    ext_200 = sig.get("ext_200", 0)
    climax  = sig.get("climax_flag", False)
    trend_line = ""
    if ret_1y is not None:
        climax_warn = "  ⚠️ *CLIMAX RISK — late-stage Power Play*" if climax else ""
        trend_line = (
            f"\n*Trend*  1yr `{ret_1y:+.0f}%` · `{ext_200:+.0f}%` above 200SMA"
            f"{climax_warn}"
        )

    # AI context block (populated by the Claude validator)
    ai_summary   = sig.get("ai_summary", "")
    ai_thesis    = sig.get("ai_thesis", "")
    ai_catalysts = sig.get("ai_catalysts", "")
    ai_note      = sig.get("ai_note", "")

    context_block = ""
    if ai_summary or ai_thesis or ai_catalysts:
        lines = []
        if ai_summary:   lines.append(f"*Company*  {ai_summary}")
        if ai_thesis:    lines.append(f"*Thesis*   {ai_thesis}")
        if ai_catalysts: lines.append(f"*Catalysts*  {ai_catalysts}")
        context_block = "\n" + "\n".join(lines)

    ai_line = f"\n*AI*  {ai_note}" if ai_note else ""

    tier = sig.get("tier", "Buy Ready")
    tier_label = "🔥 BUY READY" if tier == "Buy Ready" else "📈 POTENTIAL BUY"
    return (
        f"{tier_label} — *{sig['ticker']}*  ({sig['setup']})\n"
        f"_{sig['meta']}_\n\n"
        f"*Market*  {tone}\n"
        f"*Signal*  Stage {sig['stage']} ✓ · TT {sig['tt']}/8 · RS {sig['rs']} · "
        f"Fund {'✓' if sig['funda'] else '?'} {ud_tag}"
        f"{trend_line}\n"
        f"*Setup*  footprint `{sig['footprint']}` · pivot taken out -> in buy zone"
        f"{plan_line}"
        f"{context_block}"
        f"{ai_line}\n\n"
        f"chart: tradingview.com/chart/?symbol={sig['ticker']}"
    )


def send(token, chat_id, text, image_path=None):
    """Send to Telegram. No-op (prints) if not configured — safe offline.

    Sends chart photo first, then the signal text as a separate message.
    This avoids Telegram's 1024-char caption limit and puts the visual
    context before the analysis in the feed.
    """
    if not token or not chat_id:
        print("[telegram not configured] would send:"
              + (f"\n[image {image_path}]" if image_path else "")
              + "\n" + text)
        return True   # still log + dedupe — treat stdout delivery as success
    import requests

    # Chart photo first so the visual leads in the feed
    if image_path:
        with open(image_path, "rb") as f:
            r1 = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                               data={"chat_id": chat_id},
                               files={"photo": f}, timeout=30)
        if not r1.json().get("ok"):
            _log.warning("Chart photo send failed for %s: %s", image_path, r1.json())
        time.sleep(1)

    # Signal text card follows immediately after
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                      timeout=30)
    resp = r.json()
    if not resp.get("ok"):
        _log.error("Telegram send failed: %s", resp)
        print(f"  [telegram error] {resp}")
        return False

    return True


def process(con, buyable_sigs, histories, asof):
    """For each newly-buyable signal not already alerted: render, card, send, log."""
    C.CHART_DIR.mkdir(parents=True, exist_ok=True)
    sent = []
    for sig in buyable_sigs:
        key = f"{sig['ticker']}|{sig['setup']}|{round(sig['pivot'], 2)}"
        if db.alert_seen(con, key):
            continue
        try:
            img = str(C.CHART_DIR / f"{sig['ticker']}_{asof}.png")
            try:
                render_chart(histories[sig["ticker"]], sig, img)
            except Exception as e:
                _log.warning("chart render failed %s: %s", sig["ticker"], e)
                print(f"  chart render failed {sig['ticker']}: {e}")
                img = None
            ok = send(C.TELEGRAM_TOKEN, C.TELEGRAM_CHAT_ID, build_card(sig), img)
            if ok:
                db.log_alert(con, key, sig["ticker"], asof, sig["setup"], sig["pivot"])
                sent.append((sig["ticker"], img))
        except Exception as e:
            _log.error("alert processing failed for %s: %s", sig["ticker"], e, exc_info=True)
            print(f"  alert failed for {sig['ticker']}: {e}")
        time.sleep(10)  # pace between stocks: avoids rate limiting, readable feed
    con.commit()
    return sent
