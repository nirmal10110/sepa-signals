"""Phase 7: AI validator. Called LAST, on already-filtered Buy Ready candidates.
The AI can DEMOTE an alert (CAUTION annotates, REJECT suppresses). It can NEVER
create one. This is a bounded validator, not an analyst.

Requires:  ANTHROPIC_API_KEY env var or the key in config.py.
Marked NEEDS-LIVE-VERIFY — integration test runs on the mini PC.
"""
import base64
import logging
import time
from pathlib import Path
from typing import TypedDict

log = logging.getLogger("sepa.validator")

# Bounded prompt — the AI only evaluates what the scripts already approved.
_SYSTEM = """You are a senior stock analyst reviewing a SINGLE buy candidate that
has already passed a strict quantitative SEPA screen (Minervini methodology).
Your job is to sanity-check the alert — look for anything the quant model
cannot catch: deteriorating story, recent bad news, obvious technical red flags,
or an implausible setup.

Reply with a JSON object and nothing else:
{"verdict": "CONFIRM" | "CAUTION" | "REJECT", "reason": "<one sentence>"}

CONFIRM = the setup looks consistent with the metrics; no obvious red flags.
CAUTION = proceed with extra care (annotates the card, does not suppress).
REJECT  = clear red flag that overrides the quant signal (suppresses the alert).

Be conservative: only REJECT when there is a clear, specific reason. A CAUTION
is appropriate for genuine uncertainty. Absence of conviction is not a REJECT."""


class Verdict(TypedDict):
    verdict: str   # "CONFIRM" | "CAUTION" | "REJECT"
    reason: str


def validate(sig: dict, chart_path: str | None = None,
             headlines: list[str] | None = None) -> Verdict:
    """Run the AI validator on a single Buy Ready signal.

    Args:
        sig: the signal dict from run_daily (ticker, stage, tt, rs, …)
        chart_path: path to the rendered chart PNG (optional but strongly preferred)
        headlines: list of recent news headlines (optional)

    Returns Verdict dict. Logs token usage for cost tracking.
    On any API error: returns CAUTION so the alert is not suppressed silently.
    """
    import anthropic
    from . import config as C

    api_key = getattr(C, "ANTHROPIC_API_KEY", None) or None
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

    # Build the user message
    parts = []

    # Chart image
    if chart_path and Path(chart_path).exists():
        with open(chart_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")
        parts.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img_data}
        })

    # Metrics summary
    hl_text = "\n".join(f"- {h}" for h in headlines) if headlines else "No headlines provided."
    metrics_text = f"""Ticker: {sig['ticker']}
Setup: {sig['setup']} | Footprint: {sig['footprint']}
Stage: {sig['stage']} | Trend Template: {sig['tt']}/8 | RS: {sig['rs']}
Fundamentals: {'Pass' if sig['funda'] else 'Marginal'} | Pivot: {sig['pivot']} | Stop: {sig['stop']}
Description: {sig.get('meta', '')}

Recent headlines:
{hl_text}"""

    parts.append({"type": "text", "text": metrics_text})

    t0 = time.monotonic()
    try:
        response = client.messages.create(
            model=C.VALIDATOR_MODEL,
            max_tokens=120,
            system=_SYSTEM,
            messages=[{"role": "user", "content": parts}],
        )
        elapsed = time.monotonic() - t0
        usage = response.usage
        log.info("validator %s: %s | in=%d out=%d tokens | %.1fs",
                 sig["ticker"], response.content[0].text.strip(),
                 usage.input_tokens, usage.output_tokens, elapsed)

        import json
        raw = response.content[0].text.strip()
        result = json.loads(raw)
        verdict = result.get("verdict", "CAUTION")
        reason = result.get("reason", "")
        if verdict not in ("CONFIRM", "CAUTION", "REJECT"):
            log.warning("unexpected verdict '%s' — treating as CAUTION", verdict)
            verdict = "CAUTION"
        return Verdict(verdict=verdict, reason=reason)

    except Exception as e:
        elapsed = time.monotonic() - t0
        log.error("validator API error for %s (%.1fs): %s", sig["ticker"], elapsed, e)
        # On error: CAUTION so the alert is not silently suppressed
        return Verdict(verdict="CAUTION", reason=f"Validator unavailable: {e}")


def validate_batch(sigs: list[dict], chart_dir: str | None = None,
                   headlines_map: dict | None = None) -> dict[str, Verdict]:
    """Validate a list of signals. Returns {ticker: Verdict}."""
    results = {}
    for sig in sigs:
        t = sig["ticker"]
        chart = str(Path(chart_dir) / f"{t}_chart.png") if chart_dir else None
        hl = (headlines_map or {}).get(t, [])
        results[t] = validate(sig, chart, hl)
        time.sleep(0.3)   # avoid burst-rate limits
    return results
