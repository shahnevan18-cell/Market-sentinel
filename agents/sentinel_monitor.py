"""Agent 1: Sentinel Monitor.

A rule-based agent. It does not use the LLM: detection has to be reproducible
and testable, so it runs deterministic statistical tools over the whole
watchlist, groups alerts on consecutive days into episodes, and decides which
events to escalate for investigation using the priority score.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from analytics.anomaly_detection import ScanResult, scan_universe
from config.settings import AnalysisConfig
from providers.market_data import MarketDataset

ACTOR = "Sentinel Monitor"
EPISODE_GAP = 3  # alerts for the same stock within 3 sessions belong to one episode


@dataclass
class MonitorOutput:
    scan: ScanResult
    events: pd.DataFrame
    summary: dict


def add_episodes(events: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    if events.empty:
        out = events.copy()
        out["episode_id"] = pd.Series(dtype=str)
        out["episode_day"] = pd.Series(dtype=int)
        return out
    pos = {d: i for i, d in enumerate(calendar)}
    out = events.sort_values(["ticker", "date"]).copy()
    episode_ids, episode_days = [], []
    last_ticker, last_pos, current, day = None, None, None, 0
    for _, row in out.iterrows():
        p = pos.get(row["date"])
        if row["ticker"] == last_ticker and p is not None and last_pos is not None and p - last_pos <= EPISODE_GAP:
            day += 1
        else:
            current, day = row["event_id"], 1
        episode_ids.append(current)
        episode_days.append(day)
        last_ticker, last_pos = row["ticker"], p
    out["episode_id"] = episode_ids
    out["episode_day"] = episode_days
    return out.sort_values(["date", "priority_score"], ascending=[False, False]).reset_index(drop=True)


def recent_priority_alert(events: pd.DataFrame, calendar: pd.DatetimeIndex, sessions: int = 10) -> str | None:
    """The alert a demonstration should open first: the most recent Critical or High alert of the last
    `sessions` sessions, or failing that the strongest alert in that period."""
    if events.empty or len(calendar) == 0:
        return None
    recent = events[events["date"] >= calendar[max(len(calendar) - sessions, 0)]]
    recent = recent.sort_values(["date", "priority_score"], ascending=[False, False])
    strong = recent[recent["severity"].isin(["Critical", "High"])]
    if len(strong):
        return strong.iloc[0]["event_id"]
    if len(recent):
        return recent.sort_values("priority_score", ascending=False).iloc[0]["event_id"]
    return None


class SentinelMonitor:
    def __init__(self, cfg: AnalysisConfig):
        self.cfg = cfg

    def run(self, dataset: MarketDataset) -> MonitorOutput:
        scan = scan_universe(dataset.frames, dataset.universe, self.cfg, drop_dates=dataset.partial_dates())
        events = add_episodes(scan.events, scan.panel.calendar)
        if not events.empty:
            events["escalate"] = events["priority_score"] >= self.cfg.severity_high
        last = scan.last_date
        recent = events[events["date"] == last] if (last is not None and not events.empty) else events.iloc[0:0]
        summary = {
            "latest_session": None if last is None else f"{last:%Y-%m-%d}",
            "events_total": int(len(events)),
            "events_latest_session": int(len(recent)),
            "escalated_total": int(events["escalate"].sum()) if not events.empty else 0,
            "securities_scanned": len(scan.features),
            "securities_missing": scan.missing_symbols,
            "excluded_partial_dates": [f"{d:%Y-%m-%d}" for d in scan.excluded_dates],
        }
        return MonitorOutput(scan=scan, events=events, summary=summary)
