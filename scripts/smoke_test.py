"""Live smoke test against the real external providers.

Run on a computer with internet access, from the project folder:

    python scripts/smoke_test.py            # all checks, LLM included if a key is configured
    python scripts/smoke_test.py --no-llm   # skip the LLM check

Each provider is checked on its own, then the full pipeline runs on live data.
Results are printed and written to docs/live_smoke_test_result.md with the
time of the run, so they can be quoted in the test report. Nothing is faked:
a check that cannot run is reported as FAIL or SKIPPED with the reason.
"""
from __future__ import annotations

import argparse
import platform
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from config.market import fmt_market_time  # noqa: E402
from config.settings import load_settings  # noqa: E402
from config.watchlist import LIVE_UNIVERSE  # noqa: E402

RESULTS: list[tuple[str, str, str, float]] = []


def check(name: str, fn):
    started = time.perf_counter()
    try:
        detail = fn()
        status = "PASS"
    except SkipCheck as exc:
        status, detail = "SKIPPED", str(exc)
    except Exception as exc:  # noqa: BLE001
        status, detail = "FAIL", f"{type(exc).__name__}: {str(exc)[:300]}"
        traceback.print_exc(limit=1)
    secs = time.perf_counter() - started
    RESULTS.append((name, status, detail, secs))
    print(f"[{status:7s}] {name} ({secs:.1f}s): {detail}")
    return status == "PASS"


class SkipCheck(Exception):
    pass


def main() -> int:
    # Headlines can contain characters a Windows console code page cannot show; replace them instead of crashing.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="skip the LLM check")
    args = parser.parse_args()
    settings = load_settings()
    started_at = datetime.now(timezone.utc)
    state = {}

    def yf_check():
        from providers.market_data import YFinanceProvider
        p = YFinanceProvider(timeout=settings.data.request_timeout)
        end = pd.Timestamp(datetime.now(timezone.utc).date()) + pd.Timedelta(days=1)
        res = p.fetch(["^NSEI", "RELIANCE.NS"], end - pd.Timedelta(days=45), end)
        if res.failures:
            raise RuntimeError(f"failures: {res.failures}")
        bad = {s: m.get("currency") for s, m in res.meta.items() if (m.get("currency") or "").upper() != "INR"}
        if bad:
            raise RuntimeError(f"currency is not INR: {bad}")
        nifty = res.frames["^NSEI"]
        rel = res.frames["RELIANCE.NS"]
        return (f"^NSEI {len(nifty)} rows, last bar {nifty.index[-1]:%Y-%m-%d}, currency {res.meta['^NSEI'].get('currency')}, "
                f"time zone {res.meta['^NSEI'].get('timezone')}; RELIANCE.NS {len(rel)} rows, last bar "
                f"{rel.index[-1]:%Y-%m-%d}, exchange {res.meta['RELIANCE.NS'].get('exchange')}")

    def gn_check():
        from providers.news_data import GoogleNewsRssProvider
        g = GoogleNewsRssProvider(settings.data.news_timeout)
        today = datetime.now(timezone.utc).date()
        query = GoogleNewsRssProvider.default_query("Reliance Industries")
        items, st = g.search(query, "RELIANCE.NS", today - timedelta(days=7), today + timedelta(days=1))
        if st.status == "failed":
            raise RuntimeError(st.message)
        first = f"; first: '{items[0].headline[:70]}' ({items[0].publisher})" if items else ""
        return f"{len(items)} headline(s) in the last 7 days from the India edition{first}"

    def yahoo_news_check():
        from providers.news_data import YahooFinanceNewsProvider
        items, st = YahooFinanceNewsProvider().search("RELIANCE.NS")
        if st.status == "failed":
            raise RuntimeError(st.message)
        return f"{len(items)} latest headline(s) for RELIANCE.NS"

    def dataset_check():
        from providers.market_data import load_live_dataset
        ds = load_live_dataset(LIVE_UNIVERSE, settings, force_refresh=False)
        f = ds.freshness()
        if not ds.frames:
            raise RuntimeError(f"no data loaded; failures: {list(ds.failures.items())[:3]}")
        state["ds"] = ds
        return (f"{len(ds.frames)}/{len(LIVE_UNIVERSE.all_symbols)} symbols, latest bar {f['latest_bar']}, "
                f"statuses {f['status_counts']}, failures {len(ds.failures)}")

    def monitor_check():
        from agents.sentinel_monitor import SentinelMonitor
        if "ds" not in state:
            raise SkipCheck("dataset not loaded")
        mon = SentinelMonitor(settings.analysis).run(state["ds"])
        state["mon"] = mon
        return f"{mon.summary['events_total']} alert(s) in the history; {mon.summary['events_latest_session']} in the latest session"

    def investigation_check(use_llm: bool):
        def run():
            from agents.orchestrator import run_investigation
            from providers.llm import make_backend
            if "mon" not in state:
                raise SkipCheck("monitor did not run")
            backend = make_backend(settings.llm) if use_llm else None
            if use_llm and backend is None:
                raise SkipCheck("no LLM key configured (set ANTHROPIC_API_KEY or LLM_API_KEY in .env)")
            mon = state["mon"]
            if mon.events.empty:
                raise SkipCheck("no alerts detected, so there is nothing to investigate")
            recent = mon.events[mon.events["date"] >= mon.scan.panel.calendar[-20]]
            pick = (recent if len(recent) else mon.events).sort_values("priority_score").iloc[-1]
            rec = run_investigation(pick["event_id"], state["ds"], settings, backend=backend, scan=mon.scan)
            news = ", ".join(f"{s['provider']}={s['status']}" for s in rec.news_statuses)
            if use_llm and (rec.engine["investigator"] != "llm" or rec.engine["llm_errors"]):
                # The investigation still finished, but on the rule-based fallback: that is not an LLM pass.
                raise RuntimeError("the LLM step did not complete; the run fell back to the rule-based engine: "
                                   + "; ".join(rec.engine["llm_errors"]))
            turns = (f"; model turns {rec.engine['investigator_turns']}/{rec.engine['strategist_turns']}"
                     if use_llm else "")
            return (f"{pick['event_id']}: leading '{rec.rubric['leading_label']}' ({rec.rubric['confidence']}); "
                    f"engine {rec.engine['investigator']}/{rec.engine['strategist']}{turns}; {len(rec.news)} news item(s); "
                    f"sources: {news}; saved {rec.saved_to or 'not saved'}")
        return run

    check("Market data: yfinance (^NSEI, RELIANCE.NS, currency INR)", yf_check)
    check("News: Google News RSS search, India edition", gn_check)
    check("News: Yahoo Finance headlines via yfinance", yahoo_news_check)
    RESULTS.append(("Disclosures: NSE/BSE announcements", "LINK-ONLY",
                    "Not retrieved automatically (NSE terms of use, clause 9); the app links to the official pages.", 0.0))
    print("[LINK-ONLY] Disclosures: NSE/BSE announcements are linked, not retrieved (exchange terms of use).")
    check("Pipeline: load full live watchlist (cache-first)", dataset_check)
    check("Pipeline: Sentinel Monitor scan", monitor_check)
    check("Pipeline: rule-based investigation of a recent alert", investigation_check(False))
    if args.no_llm:
        RESULTS.append(("Pipeline: LLM investigation", "SKIPPED", "--no-llm flag", 0.0))
    else:
        check("Pipeline: LLM investigation of the same alert", investigation_check(True))

    versions = {}
    for pkg in ("yfinance", "pandas", "numpy", "streamlit", "plotly", "requests", "pydantic"):
        try:
            versions[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            versions[pkg] = "not installed"
    lines = [
        "# Live smoke test result",
        "",
        f"Run at {started_at:%Y-%m-%d %H:%M:%S} UTC ({fmt_market_time(started_at)}) on {platform.system()} "
        f"{platform.release()}, "
        f"Python {platform.python_version()}.",
        "Package versions: " + ", ".join(f"{k} {v}" for k, v in versions.items()) + ".",
        f"LLM configuration: {settings.llm.describe()}.",
        "",
        "| Check | Result | Detail | Seconds |",
        "|---|---|---|---|",
    ]
    for name, status, detail, secs in RESULTS:
        lines.append(f"| {name} | {status} | {detail.replace('|', '/')} | {secs:.1f} |")
    out = ROOT / "docs" / "live_smoke_test_result.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {out}")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
