"""Alert-table helpers shared by the pages: filtering, concise labels and plain-English descriptions.

Kept free of Streamlit so the behaviour can be tested directly. Filtering rules:

* An empty multiselect means "no restriction". Clearing Severity or Alert type therefore shows every severity or
  type, and the result says so, instead of silently showing nothing.
* A filter combination that matches nothing returns a frame with zero rows and every column of the alert contract
  (analytics.anomaly_detection.EVENT_COLUMNS), so later code can still sort, count and display it.
* Every mask is built as an explicit boolean Series. Indexing a frame with an empty object-dtype Series selects
  columns, not rows, which is what made the Anomaly monitor lose its columns and crash with a KeyError.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from analytics.anomaly_detection import EVENT_COLUMNS, SHORT_TYPE

SEVERITIES = ["Critical", "High", "Moderate", "Low"]
ALERT_TYPES = list(SHORT_TYPE)          # Large price move, Market-relative move, Volume spike


class AlertSchemaError(ValueError):
    """The alert frame does not carry the columns the pages rely on. Raised, never swallowed."""


def check_schema(events: pd.DataFrame, required: list[str] | None = None) -> None:
    missing = [col for col in (required or EVENT_COLUMNS) if col not in events.columns]
    if missing:
        raise AlertSchemaError(f"Alert data is missing required column(s): {', '.join(missing)}.")


@dataclass
class AlertFilters:
    tickers: list[str] = field(default_factory=list)      # empty: all securities
    start: object = None                                  # date or None
    end: object = None
    severities: list[str] = field(default_factory=list)   # empty: all severities
    types: list[str] = field(default_factory=list)        # empty: all alert types
    min_score: float = 0.0


@dataclass
class FilterResult:
    view: pd.DataFrame
    notes: list[str]          # which cleared filters were treated as "all"
    total: int                # alerts before filtering

    @property
    def empty(self) -> bool:
        return self.view.empty


def _mask(series: pd.Series, fn) -> pd.Series:
    return series.map(fn).astype(bool) if len(series) else pd.Series(False, index=series.index, dtype=bool)


def filter_alerts(events: pd.DataFrame, f: AlertFilters) -> FilterResult:
    check_schema(events)
    notes = []
    keep = pd.Series(True, index=events.index, dtype=bool)
    if f.tickers:
        keep &= events["ticker"].isin(f.tickers)
    if f.start is not None:
        keep &= events["date"] >= pd.Timestamp(f.start)
    if f.end is not None:
        keep &= events["date"] <= pd.Timestamp(f.end)
    if f.severities:
        keep &= events["severity"].isin(f.severities)
    else:
        notes.append("No severity is selected, so all severities are shown.")
    if f.types:
        wanted = set(f.types)
        keep &= _mask(events["event_types"], lambda ts: bool(wanted.intersection(ts or [])))
    else:
        notes.append("No alert type is selected, so all alert types are shown.")
    if f.min_score:
        keep &= events["priority_score"].fillna(-1) >= float(f.min_score)
    view = events.loc[keep.astype(bool)]
    view = view.sort_values(["date", "priority_score"], ascending=[False, False]).reset_index(drop=True)
    return FilterResult(view=view, notes=notes, total=int(len(events)))


def short_symbol(ticker: str) -> str:
    for suffix in (".NS", ".BO", ".DEMO"):
        if ticker.endswith(suffix):
            return ticker[: -len(suffix)]
    return ticker


def alert_label(ev: dict | pd.Series) -> str:
    """Concise, scannable option label, for example 'BAJFINANCE · 31 Jul 2026 · Price + volume · Priority 83'."""
    kind = ev.get("event_type_short") or "Alert"
    score = ev.get("priority_score")
    pr = "Priority n/a" if score is None or pd.isna(score) else f"Priority {score:.0f}"
    return f"{short_symbol(str(ev['ticker']))} · {pd.Timestamp(ev['date']):%d %b %Y} · {kind} · {pr}"


def _pct(x) -> str:
    return f"{abs(x):.1%}"


def plain_reason(ev: dict | pd.Series, benchmark_name: str, lookback: int = 60) -> str:
    """One or two sentences a non-specialist can read: what was unusual, compared with what."""
    types = set(ev.get("event_types") or [])
    ret, abn, vol_x = ev.get("ret"), ev.get("abnormal_ret"), ev.get("volume_ratio")
    mkt = ev.get("mkt_ret")
    parts = []
    if "Large price move" in types and ret is not None and not pd.isna(ret):
        word = "rose" if ret > 0 else "fell"
        parts.append(f"the stock {word} {_pct(ret)} in one session, far outside its usual daily range over the "
                     f"previous {lookback} sessions")
    if "Market-relative move" in types and abn is not None and not pd.isna(abn):
        side = "better" if abn > 0 else "worse"
        mkt_txt = "" if mkt is None or pd.isna(mkt) else f" (the {benchmark_name} moved {mkt:+.1%})"
        parts.append(f"it did {_pct(abn)} {side} than its usual link to the {benchmark_name} would predict{mkt_txt}")
    if "Volume spike" in types and vol_x is not None and not pd.isna(vol_x):
        parts.append(f"trading volume was {vol_x:.1f} times its typical level")
    if not parts:
        return "Flagged by the monitor's statistical tests; see the measures below."
    text = "; ".join(parts)
    return f"Flagged because {text}. Unusual is not the same as explained: the cause still has to be investigated."


def monitor_state(mon) -> tuple[str, str]:
    """('no_data' | 'no_alerts' | 'ok', explanation). 'no_data' means prices are missing, not that the market was calm."""
    if mon is None:
        return "no_data", "No market data is loaded, so no alerts can be computed."
    scan = mon.scan
    if not scan.features:
        missing = ", ".join(short_symbol(t) for t in scan.missing_symbols[:8]) or "every symbol"
        return "no_data", (f"Prices were not available for {missing}, so the monitor had nothing to scan. "
                           "This is a data or provider problem, not a sign that nothing unusual happened.")
    if mon.events.empty:
        return "no_alerts", ("The monitor scanned the data and found no move above the alert thresholds. "
                             "Lower the thresholds in the sidebar to see weaker events.")
    return "ok", ""
