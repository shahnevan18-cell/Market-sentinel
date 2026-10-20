"""Provider-symbol validation for the live NSE universe.

Every configured symbol is fetched from the configured provider and checked against what the analysis needs:

* rows returned, and enough history for the baselines (120 sessions for beta, about 250 for one-year VaR);
* currency INR, so rupee amounts are real rupees (a different currency is a failure, never relabelled);
* exchange time zone Asia/Kolkata and an NSE listing (BSE for the SENSEX), so dates are NSE sessions;
* the expected instrument type (EQUITY for shares, INDEX for indices);
* a recent last bar, measured in NSE trading sessions;
* non-zero volume for shares.

A symbol that fails is reported with the reason. Nothing is filled in, and the app never keeps a failed symbol
quietly: at run time it appears as "unavailable" in the data-status table. Used by scripts/validate_symbols.py
and by the unit tests (with a fake provider).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import pandas as pd

from config.market import CURRENCY, TZ_NAME, expected_latest_session, sessions_between
from config.watchlist import Universe

MIN_ROWS_FAIL = 120     # fewer rows than the beta window: the market model cannot be estimated
MIN_ROWS_WARN = 250     # fewer than about a year: one-year VaR and the replay are limited
STALE_SESSIONS = 3


@dataclass
class SymbolCheck:
    symbol: str
    role: str                        # stock | benchmark | sector index | display index
    name: str
    status: str = "PASS"             # PASS | WARN | FAIL
    rows: int = 0
    first_date: str | None = None
    last_date: str | None = None
    currency: str | None = None
    exchange: str | None = None
    timezone: str | None = None
    instrument_type: str | None = None
    problems: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.status = "FAIL"
        self.problems.append(msg)

    def warn(self, msg: str) -> None:
        if self.status != "FAIL":
            self.status = "WARN"
        self.problems.append(msg)

    def as_dict(self) -> dict:
        return asdict(self)


def role_of(universe: Universe, symbol: str) -> str:
    if universe.get(symbol):
        return "stock"
    if symbol == universe.benchmark:
        return "benchmark"
    if symbol in universe.sector_indices.values():
        return "sector index"
    return "display index"


def check_symbol(universe: Universe, symbol: str, frame: pd.DataFrame | None, meta: dict | None,
                 failure: str | None, now: datetime) -> SymbolCheck:
    role = role_of(universe, symbol)
    chk = SymbolCheck(symbol=symbol, role=role, name=universe.display_name(symbol))
    if failure or frame is None or frame.empty:
        chk.fail(f"No data from the provider: {failure or 'empty result'}. Remove or correct this symbol.")
        return chk
    meta = meta or {}
    chk.rows = int(len(frame))
    chk.first_date = f"{frame.index[0]:%Y-%m-%d}"
    chk.last_date = f"{frame.index[-1]:%Y-%m-%d}"
    chk.currency = meta.get("currency")
    chk.exchange = meta.get("exchange")
    chk.timezone = meta.get("timezone")
    chk.instrument_type = meta.get("instrument_type")

    if chk.rows < MIN_ROWS_FAIL:
        chk.fail(f"Only {chk.rows} daily rows; at least {MIN_ROWS_FAIL} are needed to estimate beta.")
    elif chk.rows < MIN_ROWS_WARN:
        chk.warn(f"Only {chk.rows} daily rows; one-year VaR and the replay will be limited.")
    if not chk.currency:
        chk.fail("The provider did not report a currency, so the prices cannot be confirmed as rupees.")
    elif chk.currency.upper() != CURRENCY:
        chk.fail(f"Currency {chk.currency}, not {CURRENCY}. The values must not be relabelled as rupees.")
    if chk.timezone and chk.timezone != TZ_NAME:
        chk.warn(f"Exchange time zone {chk.timezone}, expected {TZ_NAME}.")
    exch = (chk.exchange or "").upper()
    expected_exch = ("BSE",) if symbol in ("^BSESN",) or symbol.endswith(".BO") else ("NSE", "NSI")
    if not exch:
        chk.warn("Exchange not reported by the provider.")
    elif not any(x in exch for x in expected_exch):
        chk.warn(f"Exchange '{chk.exchange}', expected {' or '.join(expected_exch)}.")
    expected_type = "EQUITY" if role == "stock" else "INDEX"
    if chk.instrument_type and chk.instrument_type.upper() != expected_type:
        chk.warn(f"Instrument type {chk.instrument_type}, expected {expected_type}.")
    lag = sessions_between(frame.index[-1], expected_latest_session(now))
    if lag >= STALE_SESSIONS:
        chk.warn(f"Last bar {chk.last_date} is {lag} NSE sessions behind the expected latest session.")
    if role == "stock" and "volume" in frame.columns:
        recent = frame["volume"].iloc[-20:]
        if recent.notna().sum() == 0 or (recent.fillna(0) <= 0).all():
            chk.warn("No positive volume in the last 20 sessions.")
    return chk


def validate_universe(universe: Universe, provider, history_days: int = 760,
                      now: datetime | None = None) -> list[SymbolCheck]:
    """Fetch every symbol of the universe once and check it. Returns one SymbolCheck per symbol, in order."""
    now = now or datetime.now(timezone.utc)
    end = pd.Timestamp(now.date()) + pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=history_days)
    res = provider.fetch(universe.all_symbols, start, end)
    out = []
    for sym in universe.all_symbols:
        out.append(check_symbol(universe, sym, res.frames.get(sym), res.meta.get(sym), res.failures.get(sym), now))
    return out


def summary(checks: list[SymbolCheck]) -> dict:
    return {
        "total": len(checks),
        "pass": sum(c.status == "PASS" for c in checks),
        "warn": sum(c.status == "WARN" for c in checks),
        "fail": sum(c.status == "FAIL" for c in checks),
        "failed_symbols": [c.symbol for c in checks if c.status == "FAIL"],
    }
