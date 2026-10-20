"""Data-quality checks applied to every fetched or cached price series.

Each check produces an issue with a level (info, warning, error) and a plain
explanation of why it matters for the analysis. Cleaning is limited to safe,
recorded actions: duplicate dates are collapsed and impossible values
(non-positive prices, negative volume) are set to missing. Prices are never
invented or interpolated, and no observed bar is deleted because of its date.

Session rules (time zone, close time, holidays) come from config/market.py
(NSE, Asia/Kolkata), so this module has no exchange-specific constants.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from config.market import (CURRENCY, expected_latest_session, holiday_name, is_partial_session,  # noqa: F401
                           sessions_between)

PRICE_COLUMNS = ["open", "high", "low", "close", "adj_close"]


@dataclass
class QualityIssue:
    level: str          # info | warning | error
    code: str
    message: str


@dataclass
class QualityReport:
    symbol: str
    n_obs: int = 0
    first_date: str | None = None
    last_date: str | None = None
    status: str = "OK"
    issues: list[QualityIssue] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def add(self, level: str, code: str, message: str) -> None:
        self.issues.append(QualityIssue(level, code, message))
        if level == "error":
            self.status = "Error"
        elif level == "warning" and self.status != "Error":
            self.status = "Warning"

    def as_dict(self) -> dict:
        d = asdict(self)
        return d


def business_days_between(a, b) -> int:
    """Expected NSE trading sessions after `a` up to and including `b` (holidays and weekends excluded)."""
    return sessions_between(a, b)


def clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    actions = []
    out = df.copy()
    out.index = pd.DatetimeIndex(out.index)
    if not out.index.is_monotonic_increasing:
        out = out.sort_index()
        actions.append("Sorted rows by date.")
    dup = out.index.duplicated(keep="last")
    if dup.any():
        out = out[~dup]
        actions.append(f"Removed {int(dup.sum())} duplicated date row(s), keeping the last value.")
    for col in PRICE_COLUMNS:
        if col in out.columns:
            bad = out[col] <= 0
            if bad.any():
                out.loc[bad, col] = np.nan
                actions.append(f"Set {int(bad.sum())} non-positive '{col}' value(s) to missing.")
    if "volume" in out.columns:
        neg = out["volume"] < 0
        if neg.any():
            out.loc[neg, "volume"] = np.nan
            actions.append(f"Set {int(neg.sum())} negative volume value(s) to missing.")
    return out, actions


def check_frame(symbol: str, df: pd.DataFrame, *, calendar: pd.DatetimeIndex | None = None,
                currency: str | None = None, expected_currency: str | None = CURRENCY,
                min_required: int = 100, large_gap: float = 0.25, retrieved_at: datetime | None = None,
                is_demo: bool = False, actions: list[str] | None = None, is_index: bool = False) -> QualityReport:
    rep = QualityReport(symbol=symbol, actions=list(actions or []))
    if df is None or df.empty:
        rep.add("error", "no_data", "No rows were returned for this symbol, so it is excluded from the analysis.")
        return rep
    rep.n_obs = int(len(df))
    rep.first_date = f"{df.index[0]:%Y-%m-%d}"
    rep.last_date = f"{df.index[-1]:%Y-%m-%d}"

    if rep.n_obs < min_required:
        rep.add("warning", "short_history",
                f"Only {rep.n_obs} daily observations. Baselines need about {min_required} trading days, "
                "so early dates have no z-scores and beta may be unavailable.")

    dupes = int(df.index.duplicated().sum())
    if dupes:
        rep.add("warning", "duplicates", f"{dupes} duplicated date(s) found.")

    weekend = df.index[df.index.dayofweek >= 5]
    if len(weekend):
        sample = ", ".join(f"{d:%Y-%m-%d}" for d in weekend[:4])
        rep.add("info", "special_sessions",
                f"{len(weekend)} bar(s) fall on a weekend ({sample}). NSE holds occasional special sessions "
                "(Muhurat trading, Budget day); the bars are kept and only count if the benchmark also has them.")
    on_holiday = [d for d in df.index if d.dayofweek < 5 and holiday_name(d)]
    if on_holiday:
        sample = ", ".join(f"{d:%Y-%m-%d} ({holiday_name(d)})" for d in on_holiday[:3])
        rep.add("info", "holiday_bars",
                f"{len(on_holiday)} bar(s) are dated on listed NSE trading holidays: {sample}. These are usually "
                "special sessions such as Muhurat trading, or a provider artefact; they are kept, not invented or removed.")

    adj = df.get("adj_close")
    if adj is not None:
        missing = int(adj.isna().sum())
        if missing:
            rep.add("warning", "missing_prices",
                    f"{missing} missing adjusted close value(s); returns on and after those dates are missing.")
        rets = adj / adj.shift(1) - 1
        gaps = rets[rets.abs() >= large_gap]
        if len(gaps):
            dates = ", ".join(f"{d:%Y-%m-%d} ({v:+.0%})" for d, v in gaps.head(5).items())
            rep.add("warning", "large_gaps",
                    f"Single-day moves of {large_gap:.0%} or more on: {dates}. For a large Indian company this "
                    "usually means a corporate action the provider did not adjust (bonus issue, split, demerger) "
                    "or a data error, so check the exchange's corporate-action records before trusting the alert.")
        if "close" in df.columns:
            raw = df["close"] / df["close"].shift(1) - 1
            suspect = (raw.abs() >= 0.30) & (rets.abs() < 0.10)
            if suspect.any():
                rep.add("info", "corporate_action",
                        f"{int(suspect.sum())} day(s) where the raw close jumped but the adjusted close did not, "
                        "consistent with a split, bonus issue or special dividend handled by the adjustment.")

    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            nonpos = int((df[col] <= 0).sum())
            if nonpos:
                rep.add("error", "non_positive", f"{nonpos} non-positive '{col}' value(s).")
    if {"high", "low", "close"}.issubset(df.columns):
        inconsistent = (df["high"] < df["low"]) | (df["close"] > df["high"] * 1.005) | (df["close"] < df["low"] * 0.995)
        n_bad = int(inconsistent.fillna(False).sum())
        if n_bad:
            rep.add("warning", "ohlc_inconsistent", f"{n_bad} row(s) where close lies outside the high-low range.")

    if "volume" in df.columns:
        vol_missing = int(df["volume"].isna().sum())
        vol_zero = int((df["volume"] == 0).sum())
        if vol_missing or vol_zero:
            if is_index:
                rep.add("info", "index_volume",
                        f"Index volume missing on {vol_missing} day(s) and zero on {vol_zero} day(s). Index volume is "
                        "not used by the analysis.")
            else:
                rep.add("warning", "volume_gaps",
                        f"Volume missing on {vol_missing} day(s) and zero on {vol_zero} day(s); "
                        "abnormal-volume tests skip those days.")
    elif not is_index:
        rep.add("warning", "no_volume", "No volume column, so abnormal-volume tests are unavailable.")

    if "splits" in df.columns:
        splits = df["splits"][(df["splits"].fillna(0) != 0) & (df["splits"].fillna(1) != 1)]
        for d, v in splits.items():
            rep.add("info", "split", f"Split or bonus issue on {d:%Y-%m-%d} (ratio {v:g}). The adjusted close accounts for it.")

    if calendar is not None and len(calendar):
        cal = calendar[(calendar >= df.index[0]) & (calendar <= df.index[-1])]
        missing_days = cal.difference(df.index)
        if len(missing_days):
            sample = ", ".join(f"{d:%Y-%m-%d}" for d in missing_days[:5])
            rep.add("warning", "missing_dates",
                    f"{len(missing_days)} benchmark trading day(s) missing for this symbol (e.g. {sample}). "
                    "No return is computed across a gap such as a trading suspension.")

    if not is_demo:
        if currency is None:
            rep.add("warning", "currency_unknown",
                    "Currency not reported by the provider, so the values cannot be confirmed as rupees.")
        elif expected_currency and currency.upper() != expected_currency.upper():
            rep.add("warning", "currency_mismatch",
                    f"Currency {currency} differs from the expected {expected_currency}. The values are not relabelled "
                    "as rupees; returns stay valid but rupee amounts for this symbol would be wrong.")
        if retrieved_at is not None:
            expected = expected_latest_session(retrieved_at)
            last = pd.Timestamp(df.index[-1])
            lag = sessions_between(last, expected)
            if lag >= 2:
                rep.add("warning", "stale", f"Latest bar ({last:%Y-%m-%d}) is {lag} trading sessions behind the "
                                            f"expected latest session ({expected:%Y-%m-%d}) at retrieval time.")
            elif lag == 1:
                rep.add("info", "possibly_delayed",
                        f"Latest bar ({last:%Y-%m-%d}) is one trading session behind {expected:%Y-%m-%d}; "
                        "this is usually a provider delay.")
            if is_partial_session(last, retrieved_at):
                rep.add("info", "partial_session",
                        f"The bar for {last:%Y-%m-%d} was retrieved before 16:15 IST, when NSE's day is not final; "
                        "it is incomplete and excluded from anomaly detection.")
    return rep
