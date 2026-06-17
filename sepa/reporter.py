"""Daily HTML watchlist digest — sent after every nightly scan.

Queries all tiers from watchlist_state (joined with the latest signals)
and renders a mobile-friendly collapsible-card email.
One <details>/<summary> card per stock; tier sections ordered
Buy Ready → Potential Buy → Buy Alert → Watch.
Watch tier renders as a compact table (too many to card-ify).
"""
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date
from . import config as C

log = logging.getLogger("sepa.reporter")

# (text-colour, background-colour, emoji)
_TIER_CFG = {
    "Buy Ready":    ("#155724", "#d4edda", "🟢"),
    "Potential Buy":("#004085", "#cce5ff", "🔵"),
    "Buy Alert":    ("#856404", "#fff3cd", "🟡"),
    "Watch":        ("#383d41", "#e2e3e5", "⚪"),
}
_FALLBACK_CFG = ("#495057", "#f8f9fa", "•")
_DISPLAY_ORDER = ["Buy Ready", "Potential Buy", "Buy Alert", "Watch"]


# ── HTML helpers ────────────────────────────────────────────────────────────

def _badge(tier: str) -> str:
    fg, bg, _ = _TIER_CFG.get(tier, _FALLBACK_CFG)
    return (
        f'<span style="display:inline-block;padding:1px 7px;border-radius:10px;'
        f'font-size:10px;font-weight:700;letter-spacing:.5px;white-space:nowrap;'
        f'color:{fg};background:{bg}">{tier.upper()}</span>'
    )


def _position_line(sig: dict) -> str:
    e = sig.get("entry") or 0.0
    s = sig.get("stop") or 0.0
    if not e or not s or e <= s:
        return ""
    risk_pts = e - s
    risk_pct = risk_pts / e * 100
    shares = int(round(C.ACCOUNT_SIZE * C.RISK_PER_TRADE / risk_pts))
    target = round(e + 3 * risk_pts, 2)
    return (
        f'<div style="margin:4px 0;font-size:12px;color:#333">'
        f'Entry <b>${e:,.2f}</b> · Stop <b>${s:,.2f}</b> '
        f'(-{risk_pct:.1f}%) · Target <b>${target:,.2f}</b> (3:1) · '
        f'<b>{shares} sh</b> @ {C.RISK_PER_TRADE*100:.2f}% risk'
        f'</div>'
    )


def _stock_card(sig: dict, full: bool = True) -> str:
    """Single collapsible card. full=True shows position sizing."""
    t = sig["ticker"]
    tier = sig.get("tier", "")
    setup = sig.get("setup") or "—"
    rs = sig.get("rs") or "—"
    fp = sig.get("footprint") or "—"
    pivot = sig.get("pivot") or 0.0
    tt = sig.get("tt") or "—"
    stage = sig.get("stage") or "—"
    funda = "✓" if sig.get("funda") else "✗"
    asof = sig.get("asof") or sig.get("added") or "—"
    name = sig.get("name") or t
    ai_note = sig.get("ai_note") or ""
    ai_summary = sig.get("ai_summary") or ""

    _, bg, _ = _TIER_CFG.get(tier, _FALLBACK_CFG)

    # Collapsed summary: ticker + badge + setup/RS + AI snip
    ai_snip = ""
    if ai_note:
        icon = "⚠️" if "CAUTION" in ai_note else "✅"
        snip = ai_note[:60] + ("…" if len(ai_note) > 60 else "")
        ai_snip = (
            f'<span style="font-size:11px;color:#666;font-weight:400">'
            f' {icon} {snip}</span>'
        )

    summary_inner = (
        f'<span style="font-weight:700;font-size:14px;min-width:56px;'
        f'display:inline-block">{t}</span>'
        f'&thinsp;{_badge(tier)}&thinsp;'
        f'<span style="color:#555;font-size:12px">{setup} · RS {rs}'
        f'{ai_snip}</span>'
    )

    # Expanded detail rows
    rows = []
    if name and name != t:
        rows.append(f'<b>{name}</b>')
    sector = sig.get("sector") or ""
    if sector and sector != "—":
        rows.append(f'<span style="color:#666;font-size:11px">{sector}</span>')
    rows.append(
        f'Stage&nbsp;{stage} · TT&nbsp;{tt}/8 · RS&nbsp;{rs} · '
        f'Fund&nbsp;{funda} · <code>{fp}</code>'
    )
    if pivot:
        rows.append(f'Pivot: <b>${pivot:,.2f}</b> · Signal date: {asof}')
    if full:
        ps = _position_line(sig)
        if ps:
            rows.append(ps)
    if ai_note:
        icon = "⚠️" if "CAUTION" in ai_note else "✅"
        rows.append(f'{icon} <i style="color:#444">{ai_note}</i>')
    if ai_summary:
        rows.append(
            f'<span style="color:#666;font-size:11px">{ai_summary}</span>'
        )

    detail_html = "".join(
        f'<div style="margin:3px 0;font-size:12px;color:#222">{r}</div>'
        for r in rows
    )

    return (
        f'<details style="margin:4px 0;border-radius:6px;overflow:hidden">'
        f'<summary style="padding:9px 12px;background:{bg};cursor:pointer;'
        f'font-family:inherit;list-style:none;-webkit-appearance:none;'
        f'display:flex;align-items:center;gap:6px">'
        f'{summary_inner}'
        f'</summary>'
        f'<div style="padding:8px 12px 10px;border:1px solid #dee2e6;'
        f'border-top:none;background:#fff;border-radius:0 0 6px 6px">'
        f'{detail_html}'
        f'</div>'
        f'</details>\n'
    )


def _watch_table(sigs: list) -> str:
    """Compact table for Watch-tier stocks (too many to card-ify individually)."""
    rows_html = "".join(
        f'<tr style="border-bottom:1px solid #eee">'
        f'<td style="padding:4px 8px;font-weight:600;font-size:12px">'
        f'{s["ticker"]}</td>'
        f'<td style="padding:4px 8px;font-size:12px;color:#555">'
        f'{s.get("setup") or "—"}</td>'
        f'<td style="padding:4px 8px;font-size:12px;color:#555">'
        f'{s.get("rs") or "—"}</td>'
        f'<td style="padding:4px 8px;font-size:12px;color:#555">'
        f'St {s.get("stage") or "—"} · TT {s.get("tt") or "—"}/8</td>'
        f'</tr>'
        for s in sigs
    )
    return (
        f'<table style="width:100%;border-collapse:collapse;font-family:inherit">'
        f'<thead><tr style="background:#dee2e6">'
        f'<th style="padding:4px 8px;font-size:11px;font-weight:700;text-align:left">'
        f'Ticker</th>'
        f'<th style="padding:4px 8px;font-size:11px;font-weight:700;text-align:left">'
        f'Setup</th>'
        f'<th style="padding:4px 8px;font-size:11px;font-weight:700;text-align:left">'
        f'RS</th>'
        f'<th style="padding:4px 8px;font-size:11px;font-weight:700;text-align:left">'
        f'Stage / TT</th>'
        f'</tr></thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
    )


def _tier_section(tier: str, sigs: list) -> str:
    if not sigs:
        return ""
    _, bg, icon = _TIER_CFG.get(tier, _FALLBACK_CFG)
    full = tier in ("Buy Ready", "Potential Buy")
    body = _watch_table(sigs) if tier == "Watch" else "".join(
        _stock_card(s, full=full) for s in sigs
    )
    return (
        f'<div style="margin-bottom:20px">'
        f'<h2 style="font-size:14px;font-weight:700;color:#222;margin:0 0 8px;'
        f'padding-bottom:5px;border-bottom:2px solid {bg}">'
        f'{icon}&nbsp;{tier} ({len(sigs)})</h2>'
        f'{body}'
        f'</div>\n'
    )


# ── main render ─────────────────────────────────────────────────────────────

def build_html(sigs: list, asof: str, tone: str = "—", breadth: str = "—") -> str:
    by_tier = {t: [] for t in _DISPLAY_ORDER}
    for s in sigs:
        t = s.get("tier", "")
        if t in by_tier:
            by_tier[t].append(s)

    counts_str = " · ".join(
        f'{len(by_tier[t])} {t}' for t in _DISPLAY_ORDER if by_tier[t]
    )
    sections = "".join(_tier_section(t, by_tier[t]) for t in _DISPLAY_ORDER)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>SEPA Signal Desk — {asof}</title>
<style>
details summary::-webkit-details-marker {{ display:none }}
details > summary {{ list-style:none }}
details > summary::marker {{ display:none }}
</style>
</head>
<body style="margin:0;padding:0;background:#f0f2f5;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif">

<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5">
<tr><td align="center" style="padding:12px 8px">
<table width="100%" style="max-width:640px">

  <!-- ── header ─────────────────────────────────────────── -->
  <tr><td style="background:#0d1b2a;padding:18px 20px;
                 border-radius:10px 10px 0 0">
    <div style="font-size:10px;letter-spacing:1.5px;color:#6a8090;
                text-transform:uppercase;margin-bottom:4px">SEPA SIGNAL DESK</div>
    <div style="font-size:20px;font-weight:700;color:#fff;
                margin-bottom:6px">{asof}</div>
    <div style="font-size:12px;color:#aabbc8">{counts_str}</div>
    <div style="font-size:11px;color:#6a8090;margin-top:3px">
      Market: {tone} · Breadth {breadth}</div>
  </td></tr>

  <!-- ── body ───────────────────────────────────────────── -->
  <tr><td style="background:#f8f9fa;padding:16px 14px;
                 border-radius:0 0 10px 10px">
    {sections}
    <p style="margin:12px 0 0;font-size:10px;color:#bbb;text-align:center">
      Personal decision-support tool · not investment advice
    </p>
  </td></tr>

</table>
</td></tr>
</table>

</body>
</html>"""


# ── DB query ────────────────────────────────────────────────────────────────

def _query(con) -> list:
    rows = con.execute("""
        SELECT ws.ticker, ws.tier, ws.added,
               s.stage, s.tt, s.rs, s.funda, s.setup, s.footprint,
               s.pivot, s.entry, s.stop, s.asof,
               sec.name, sec.sector,
               s.ai_note, s.ai_summary
        FROM watchlist_state ws
        LEFT JOIN signals s
            ON  s.ticker = ws.ticker
            AND s.asof   = (SELECT MAX(asof) FROM signals s2
                            WHERE s2.ticker = ws.ticker)
        LEFT JOIN securities sec ON sec.ticker = ws.ticker
        ORDER BY
            CASE ws.tier
                WHEN 'Buy Ready'     THEN 1
                WHEN 'Potential Buy' THEN 2
                WHEN 'Buy Alert'     THEN 3
                WHEN 'Watch'         THEN 4
                ELSE 5
            END,
            COALESCE(s.rs, 0) DESC
    """).fetchall()

    keys = ["ticker", "tier", "added", "stage", "tt", "rs", "funda",
            "setup", "footprint", "pivot", "entry", "stop", "asof",
            "name", "sector", "ai_note", "ai_summary"]
    return [dict(zip(keys, r)) for r in rows]


# ── public entry point ───────────────────────────────────────────────────────

def send_report(con, asof: str = None, tone: str = "", breadth: str = "") -> bool:
    """Render and email the daily HTML report. Returns True on success."""
    if not C.SMTP_USER or not C.SMTP_PASS or not C.REPORT_TO:
        log.warning("email report skipped — SMTP_USER/SMTP_PASS/REPORT_TO not set")
        return False

    asof = asof or str(date.today())
    sigs = _query(con)
    if not sigs:
        log.info("watchlist empty — skipping report")
        return False

    html = build_html(sigs, asof, tone=tone or "—", breadth=breadth or "—")

    by_tier: dict[str, int] = {}
    for s in sigs:
        by_tier[s["tier"]] = by_tier.get(s["tier"], 0) + 1
    subject = (
        f"SEPA {asof} — "
        + " · ".join(
            f'{by_tier[t]} {t}'
            for t in _DISPLAY_ORDER
            if by_tier.get(t, 0) > 0
        )
    )

    msg = MIMEMultipart("alternative")
    msg["From"] = f"SEPA Signal Desk <{C.SMTP_USER}>"
    msg["To"] = C.REPORT_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(C.SMTP_HOST, C.SMTP_PORT, timeout=30) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(C.SMTP_USER, C.SMTP_PASS)
            srv.sendmail(C.SMTP_USER, C.REPORT_TO, msg.as_string())
        log.info("daily report → %s  (%d stocks)", C.REPORT_TO, len(sigs))
        return True
    except Exception as e:
        log.error("report send failed: %s", e)
        return False
