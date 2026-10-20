"""Check the real LLM path end to end: python scripts/llm_check.py

Runs one investigation with the LLM configured in .env (ANTHROPIC_API_KEY, or LLM_PROVIDER, LLM_API_KEY,
LLM_BASE_URL and LLM_MODEL for an OpenAI-compatible provider). By default it uses the built-in demonstration
data, so the only network service involved is the LLM provider; add --live to investigate a recent alert in
live market data instead.

It prints every model turn (which tools the model asked for and what they returned), saves the investigation
to history so it can be opened in the app, and writes docs/llm_check_result.md. The API key is never printed
or written. Each agent is reported separately:

    PASS     both the Market Investigator and the Risk Strategist were completed by the model
    PARTIAL  the model completed the investigation, but the risk step fell back to the rule-based notes
    FAIL     the investigation itself fell back to the rule-based engine (the provider's error is shown)

The exit code is 0 only for PASS. Free-tier providers limit requests per minute; the client waits as long as the
provider asks (up to LLM_RATE_LIMIT_MAX_WAIT seconds) before giving up.

    python scripts/llm_check.py                    # demonstration data, most recent high-priority alert
    python scripts/llm_check.py --live             # live NSE data (needs Yahoo Finance and Google News too)
    python scripts/llm_check.py --event SAFFRON.DEMO:2026-09-30
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.orchestrator import run_investigation  # noqa: E402
from agents.sentinel_monitor import SentinelMonitor, recent_priority_alert  # noqa: E402
from agents.trace import decision_trace, engine_facts  # noqa: E402
from config.settings import load_settings  # noqa: E402
from config.watchlist import get_universe  # noqa: E402
from providers.llm import make_backend  # noqa: E402
from providers.market_data import load_demo_dataset, load_live_dataset  # noqa: E402


def pick_event(mon) -> str:
    """The same alert the Investigation workspace preselects, so the saved run matches the demonstration."""
    return (recent_priority_alert(mon.events, mon.scan.panel.calendar)
            or mon.events.sort_values("priority_score", ascending=False).iloc[0]["event_id"])


def trace_lines(rec: dict) -> list[str]:
    lines = []
    for actor in ("Market Investigator", "Risk Strategist"):
        turns = decision_trace(rec.get("audit") or [], actor)
        if not turns:
            continue
        lines.append(f"{actor}: {len(turns)} model turn(s)")
        for t in turns:
            asked = ", ".join(t["tools_requested"]) or "no tools"
            lines.append(f"  turn {t['turn']}: model asked for {asked}")
            if t["model_note"]:
                lines.append(f"    model note: {t['model_note'][:200]}")
            for step in t["steps"]:
                lines.append(f"    {step['status']:7s} {step['step']}: {str(step['result'])[:150]}")
    return lines


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="use live market data instead of demonstration data")
    parser.add_argument("--event", help="event id such as SAFFRON.DEMO:2026-09-30 (default: most recent "
                                        "high-priority alert)")
    args = parser.parse_args()

    settings = load_settings()
    backend = make_backend(settings.llm)
    if backend is None:
        print("No LLM is configured, so there is nothing to check.\n"
              "Add ANTHROPIC_API_KEY=... to .env (or LLM_PROVIDER, LLM_API_KEY, LLM_BASE_URL and LLM_MODEL for an "
              "OpenAI-compatible provider), then run this again.")
        return 2
    print(f"LLM under test: {settings.llm.describe()}")
    if args.live:
        ds = load_live_dataset(get_universe("live"), settings)
        if not ds.frames:
            print("Live market data could not be loaded:", list(ds.failures.items())[:3])
            return 1
    else:
        ds = load_demo_dataset(get_universe("demo"))
    mon = SentinelMonitor(settings.analysis).run(ds)
    if mon.events.empty:
        print("No alerts detected, so there is nothing to investigate.")
        return 1
    event_id = args.event or pick_event(mon)
    print(f"Investigating {event_id} with {ds.mode} data ...\n")
    started = datetime.now(timezone.utc)
    def show(entry):  # live progress, so a slow provider is visible instead of a silent window
        print(f"  {entry.timestamp[11:19]} {entry.actor}: {entry.name} [{entry.status}] {str(entry.summary)[:110]}",
              flush=True)

    rec = run_investigation(event_id, ds, settings, backend=backend, scan=mon.scan, progress=show).as_dict()
    facts = engine_facts(rec)
    lines = trace_lines(rec)
    print("\n".join(lines) if lines else "The model made no turns.")
    inv_ok = facts["investigator_engine"] == "llm"
    strat_ok = facts["strategist_engine"] == "llm"
    ok = inv_ok and strat_ok and not facts["llm_errors"]
    if ok:
        verdict = "PASS: the model completed the investigation and the risk assessment itself"
    elif inv_ok:
        verdict = ("PARTIAL: the model completed the investigation itself; the risk step fell back to the "
                   "rule-based notes (see LLM errors)")
    else:
        verdict = "FAIL: the investigation fell back to the rule-based engine (see LLM errors)"
    summary = [
        f"Engine: {facts['summary']}",
        f"Investigator model turns {facts['investigator_model_turns']}, strategist model turns "
        f"{facts['strategist_model_turns']}; successful tool calls by actor {facts['tool_calls_by_actor']}",
        f"Checks the orchestrator had to run itself: {facts['tool_calls_enforced_by_orchestrator']}",
        f"Tokens reported by the provider: {facts['tokens']}",
        f"Figures the grounding check could not match: {facts['unverified_figures']}",
        f"Leading explanation: {rec['rubric']['leading_label']} ({rec['rubric']['confidence']} confidence)",
        f"LLM errors: {'; '.join(facts['llm_errors']) or 'none'}",
        f"Saved to history as {rec.get('saved_to') or 'NOT SAVED'}",
    ]
    print("\n" + "\n".join(summary) + f"\n\n{verdict}")

    report = [
        "# LLM path check",
        "",
        f"Run at {started:%Y-%m-%d %H:%M:%S} UTC with `python scripts/llm_check.py{' --live' if args.live else ''}`.",
        f"LLM: {settings.llm.describe()}. Data: {ds.mode}. Event: {event_id}.",
        "",
        f"Result: **{verdict}**",
        "",
        *[f"- {s}" for s in summary],
        "",
        "## Model turns",
        "",
        "```",
        *(lines or ["The model made no turns."]),
        "```",
        "",
    ]
    out = ROOT / "docs" / "llm_check_result.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"Wrote {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
