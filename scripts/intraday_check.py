"""Check which intraday intervals Yahoo Finance (through yfinance) serves for NSE symbols, from this computer.

    python scripts/intraday_check.py

It requests NIFTY 50 and four watchlist stocks at several bar intervals and reports what came back: rows,
sessions, first and last bar in IST, bars per session, missing bars in the last complete session, whether a bar
was still forming, and missing volume. It then runs the app's own intraday store and detector once on real
5-minute bars and writes docs/intraday_check_result.md.

Nothing is invented: a request that fails is reported as failed. It sends about 40 small requests to Yahoo
Finance and none to the LLM.
"""
from __future__ import annotations

import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analytics.intraday import scan_intraday  # noqa: E402
from config.market import is_trading_day  # noqa: E402
from providers.intraday import (INTERVAL_MINUTES, IntradayStore, YahooIntradayFetcher, bars_per_session,  # noqa: E402
                                normalise_intraday, to_ist)

SYMBOLS = ["^NSEI", "RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS"]
REQUESTS = [("1m", "5d"), ("2m", "5d"), ("5m", "5d"), ("5m", "60d"), ("15m", "5d"), ("30m", "5d"), ("60m", "1mo")]


def check_one(sym: str, interval: str, period: str) -> dict:
    import yfinance as yf
    minutes = INTERVAL_MINUTES[interval]
    started = time.perf_counter()
    row = {"symbol": sym, "interval": interval, "period": period}
    try:
        raw = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=False, actions=False,
                                     prepost=False, timeout=20)
    except Exception as exc:  # noqa: BLE001 - reported as a failure
        row.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:160]}",
                   seconds=round(time.perf_counter() - started, 1))
        return row
    received = datetime.now(timezone.utc)
    row["seconds"] = round(time.perf_counter() - started, 1)
    if raw is None or raw.empty:
        row.update(ok=False, error="no rows returned")
        return row
    frame, notes = normalise_intraday(raw, minutes, received, is_index=sym.startswith("^"))
    if frame.empty:
        row.update(ok=False, error=f"no regular-session bars ({notes})")
        return row
    sessions = sorted(frame["session"].unique())
    complete_sessions = [s for s in sessions if is_trading_day(s) and not frame[frame["session"] == s]["partial"].any()
                         and s != to_ist(received).date()]
    last_full = complete_sessions[-1] if complete_sessions else None
    expected = bars_per_session(minutes)
    got_last = int((frame["session"] == last_full).sum()) if last_full else 0
    row.update(ok=True, raw_tz=str(raw.index.tz), rows=len(frame), sessions=len(sessions),
               first=f"{frame.index[0]:%d %b %H:%M}", last=f"{frame.index[-1]:%d %b %H:%M}",
               bars_per_session=int(frame.groupby("session").size().median()), expected_per_session=expected,
               last_full_session=str(last_full) if last_full else "none",
               missing_in_last_full=(expected - got_last) if last_full else None,
               forming_bar=bool(frame["partial"].any()), dropped=notes,
               volume_missing=notes.get("volume_missing", 0))
    return row


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    import yfinance as yf
    started = datetime.now(timezone.utc)
    print(f"Intraday check at {to_ist(started):%d %b %Y %H:%M:%S} IST, yfinance {yf.__version__}, "
          f"Python {platform.python_version()}\n")
    rows = []
    for interval, period in REQUESTS:
        for sym in SYMBOLS:
            r = check_one(sym, interval, period)
            rows.append(r)
            if r["ok"]:
                print(f"  {sym:12s} {interval:>3s} {period:>4s}: {r['rows']:5d} bars, {r['sessions']:2d} sessions, "
                      f"{r['first']} to {r['last']} IST, {r['bars_per_session']}/{r['expected_per_session']} per "
                      f"session, missing in last full session {r['missing_in_last_full']}, forming bar "
                      f"{'yes' if r['forming_bar'] else 'no'} ({r['seconds']} s)")
            else:
                print(f"  {sym:12s} {interval:>3s} {period:>4s}: FAILED {r['error']} ({r['seconds']} s)")
            time.sleep(0.3)

    print("\nRunning the app's intraday store and detector on 5-minute bars ...")
    store = IntradayStore(YahooIntradayFetcher())
    first = store.get(SYMBOLS, benchmark="^NSEI", mode="manual")
    time.sleep(16)
    second = store.get(SYMBOLS, benchmark="^NSEI", mode="manual")
    for label, v in (("first request", first), ("second request", second)):
        print(f"  {label}: {v.label}. {v.explanation}")
    scan_lines = []
    if first.history:
        scan = scan_intraday(first.history, "^NSEI", 5)
        print(f"  evaluated session: {scan.session}")
        for _, r in scan.rows.iterrows():
            line = (f"{r['symbol']:12s} bar {r['bar_time']:%H:%M} IST" if r.get("bar_time") is not None and
                    str(r.get("bar_time")) != "NaT" else f"{r['symbol']:12s} no bar")
            for col, name in (("z_return", "z"), ("z_relative", "z vs NIFTY"), ("z_volume", "z volume"),
                              ("n_sessions", "baseline sessions")):
                val = r.get(col)
                if val is not None and val == val:
                    line += f", {name} {val:+.1f}" if col != "n_sessions" else f", {name} {int(val)}"
            if r.get("flagged"):
                line += f", FLAGGED: {r['reasons']}"
            if r.get("note"):
                line += f" ({r['note']})"
            scan_lines.append(line)
            print("   ", line)

    ok5 = [r for r in rows if r["ok"] and r["interval"] == "5m" and r["period"] == "60d"]
    report = [
        "# Intraday data check", "",
        f"Run at {to_ist(started):%d %b %Y %H:%M:%S} IST ({started:%Y-%m-%d %H:%M:%S} UTC) with "
        f"`python scripts/intraday_check.py`; yfinance {yf.__version__}, Python {platform.python_version()}.", "",
        f"5-minute bars over 60 days returned for {len(ok5)} of {len(SYMBOLS)} symbols.", "",
        "| Symbol | Interval | Period | Result | Bars | Sessions | First (IST) | Last (IST) | Bars per session "
        "(expected) | Missing in last full session | Forming bar | Seconds |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["ok"]:
            report.append(f"| {r['symbol']} | {r['interval']} | {r['period']} | ok | {r['rows']} | {r['sessions']} | "
                          f"{r['first']} | {r['last']} | {r['bars_per_session']} ({r['expected_per_session']}) | "
                          f"{r['missing_in_last_full']} | {'yes' if r['forming_bar'] else 'no'} | {r['seconds']} |")
        else:
            report.append(f"| {r['symbol']} | {r['interval']} | {r['period']} | failed: {r['error']} | | | | | | | | "
                          f"{r['seconds']} |")
    report += ["", "## App store and detector on 5-minute bars", "",
               f"- First request: **{first.label}**. {first.explanation}",
               f"- Second request 16 s later: **{second.label}**. {second.explanation}", "",
               "```", *(scan_lines or ["No bars to evaluate."]), "```", ""]
    out = ROOT / "docs" / "intraday_check_result.md"
    out.write_text("\n".join(report), encoding="utf-8")
    print(f"\nWrote {out}")
    return 0 if ok5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
