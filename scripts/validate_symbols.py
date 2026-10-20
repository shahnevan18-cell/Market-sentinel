"""Check every configured NSE symbol against the live provider: python scripts/validate_symbols.py

Fetches the 25 watchlist shares, the NIFTY 50 benchmark (^NSEI), the NSE sector indices and the SENSEX from
Yahoo Finance (through yfinance, as the app does) and checks rows, history length, currency (INR), exchange,
time zone, instrument type, freshness and volume. Results are printed and written to
docs/symbol_validation_result.md with the time of the run. A FAIL means the symbol must be corrected or removed
from config/watchlist.py; the script never edits that file itself and never fills in data.

Exit code 0 when nothing failed, 1 otherwise.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.market import fmt_market_time  # noqa: E402
from config.settings import load_settings  # noqa: E402
from config.watchlist import LIVE_UNIVERSE  # noqa: E402
from providers.market_data import make_provider  # noqa: E402
from providers.symbol_validation import summary, validate_universe  # noqa: E402


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    settings = load_settings()
    provider = make_provider(settings)
    now = datetime.now(timezone.utc)
    print(f"Checking {len(LIVE_UNIVERSE.all_symbols)} symbols with {provider.label} ...", flush=True)
    checks = validate_universe(LIVE_UNIVERSE, provider, settings.data.history_days, now)
    for c in checks:
        print(f"[{c.status:4s}] {c.symbol:15s} {c.role:13s} rows {c.rows:4d}  {c.first_date or '':10s} to "
              f"{c.last_date or '':10s}  {c.currency or '-':4s} {c.exchange or '-':6s} {c.timezone or '-':13s} "
              f"{c.instrument_type or '-'}" + (f"  | {'; '.join(c.problems)}" if c.problems else ""))
    s = summary(checks)
    print(f"\n{s['pass']} passed, {s['warn']} passed with warnings, {s['fail']} failed out of {s['total']}.")
    if s["failed_symbols"]:
        print("Failed: " + ", ".join(s["failed_symbols"]) + ". Correct or remove them in config/watchlist.py.")

    lines = [
        "# Provider-symbol validation",
        "",
        f"Run at {fmt_market_time(now)} ({now:%Y-%m-%d %H:%M:%S} UTC) with `python scripts/validate_symbols.py`.",
        f"Provider: {provider.label}. History requested: {settings.data.history_days} calendar days.",
        "",
        f"Result: {s['pass']} passed, {s['warn']} passed with warnings, {s['fail']} failed out of {s['total']}.",
        "",
        "| Status | Symbol | Role | Name | Rows | First | Last | Currency | Exchange | Time zone | Type | Notes |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for c in checks:
        notes = "; ".join(c.problems).replace("|", "/")
        lines.append(f"| {c.status} | {c.symbol} | {c.role} | {c.name} | {c.rows} | {c.first_date or ''} | "
                     f"{c.last_date or ''} | {c.currency or ''} | {c.exchange or ''} | {c.timezone or ''} | "
                     f"{c.instrument_type or ''} | {notes} |")
    out = ROOT / "docs" / "symbol_validation_result.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out}")
    return 1 if s["fail"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
