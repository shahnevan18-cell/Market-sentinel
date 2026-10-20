"""Historical replay and evaluation.

Detection in the replay uses only information available at the close of each
simulated day: every feature is computed from trailing windows, and
tests/test_historical_replay.py proves that recomputing on data truncated at a
date gives identical features for that date. Investigations launched from the
replay run on a dataset physically truncated at the event date, with news after
that day's close excluded.

What happened AFTER each event (forward returns, cumulative abnormal returns)
is attached only as retrospective evaluation. These columns are prefixed
"after_" and were not available when the alert fired.

There is no ground-truth label for "this move deserved an alert" in live
market data, so no accuracy figure is claimed for live NSE data; the replay
reports descriptive outcomes only. (The US version used SEC Form 8-K earnings
filings as a proxy label. NSE and BSE announcements cannot be collected
automatically under the exchanges' terms, so no Indian equivalent is used.)
In demonstration mode the shocks planted by the synthetic generator are known,
so label_evaluation() can measure how many of them the detector recovers.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analytics.anomaly_detection import ScanResult

HORIZONS = (1, 5, 20)


@dataclass
class ReplayResult:
    start: pd.Timestamp
    end: pd.Timestamp
    events: pd.DataFrame
    summary: dict
    outcome_table: pd.DataFrame
    car_paths: pd.DataFrame
    vol_uplift: pd.DataFrame
    notes: list[str] = field(default_factory=list)


def _forward_outcomes(df: pd.DataFrame, pos: int, horizons=HORIZONS) -> dict:
    out = {}
    alpha = df["alpha"].iloc[pos]
    beta = df["beta"].iloc[pos]
    close = df["close"]
    for h in horizons:
        if pos + h >= len(df) or pd.isna(close.iloc[pos]) or pd.isna(close.iloc[pos + h]):
            out[f"after_ret_{h}d"] = np.nan
            out[f"after_car_{h}d"] = np.nan
            out[f"after_absret_mean_{h}d"] = np.nan
            continue
        seg = df.iloc[pos + 1: pos + h + 1]
        out[f"after_ret_{h}d"] = float(close.iloc[pos + h] / close.iloc[pos] - 1.0)
        if pd.notna(beta):
            ar = seg["ret"] - (alpha + beta * seg["mkt_ret"])
            out[f"after_car_{h}d"] = float(ar.sum(min_count=1))
        else:
            out[f"after_car_{h}d"] = np.nan
        out[f"after_absret_mean_{h}d"] = float(seg["ret"].abs().mean())
    return out


def run_replay(scan: ScanResult, start, end, horizons=HORIZONS) -> ReplayResult:
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    events = scan.events
    if not events.empty:
        events = events[(events["date"] >= start) & (events["date"] <= end)].copy()
    notes = [
        "Detection columns use only data available at each event date's close.",
        "Columns starting with 'after_' were observed later and are shown only to evaluate the alerts.",
    ]
    rows = []
    for _, ev in events.iterrows():
        df = scan.features[ev["ticker"]]
        pos = df.index.get_loc(ev["date"])
        rows.append(_forward_outcomes(df, pos, horizons))
    fwd = pd.DataFrame(rows, index=events.index)
    events = pd.concat([events, fwd], axis=1) if len(events) else events

    if events.empty:
        empty = pd.DataFrame()
        return ReplayResult(start, end, events, {"n_events": 0}, empty, empty, empty,
                            notes + ["No events were detected in this period with the current thresholds."])

    sign_event = np.sign(events["abnormal_ret"].fillna(events["ret"]))
    outcome_rows = []
    for h in horizons:
        car = events[f"after_car_{h}d"]
        valid = car.notna()
        up = valid & (sign_event > 0)
        down = valid & (sign_event < 0)
        cont = (np.sign(car[valid]) == sign_event[valid]).mean() if valid.any() else np.nan
        outcome_rows.append({
            "horizon_days": h,
            "events_with_data": int(valid.sum()),
            "mean_after_car_up_events": float(car[up].mean()) if up.any() else np.nan,
            "mean_after_car_down_events": float(car[down].mean()) if down.any() else np.nan,
            "median_after_car_all": float(car[valid].median()) if valid.any() else np.nan,
            "continuation_rate": float(cont) if valid.any() else np.nan,
        })
    outcome_table = pd.DataFrame(outcome_rows)

    # Volatility after alerts compared with all stock-days in the period.
    all_abs = []
    for t, df in scan.features.items():
        seg = df.loc[(df.index > start) & (df.index <= end), "ret"].abs().dropna()
        all_abs.append(seg)
    baseline_abs = float(pd.concat(all_abs).mean()) if all_abs else np.nan
    vol_rows = []
    for h in horizons:
        after = events[f"after_absret_mean_{h}d"].dropna()
        vol_rows.append({
            "horizon_days": h,
            "mean_abs_return_after_alerts": float(after.mean()) if len(after) else np.nan,
            "mean_abs_return_all_days": baseline_abs,
            "ratio": float(after.mean() / baseline_abs) if len(after) and baseline_abs else np.nan,
            "events_with_data": int(len(after)),
        })
    vol_uplift = pd.DataFrame(vol_rows)

    paths = []
    for _, ev in events.iterrows():
        df = scan.features[ev["ticker"]]
        pos = df.index.get_loc(ev["date"])
        alpha, beta = df["alpha"].iloc[pos], df["beta"].iloc[pos]
        if pd.isna(beta):
            continue
        lo, hi = pos - 5, pos + 20
        if lo < 0 or hi >= len(df):
            continue
        seg = df.iloc[lo: hi + 1]
        ar = (seg["ret"] - (alpha + beta * seg["mkt_ret"])).fillna(0).to_numpy()
        car = np.cumsum(ar)
        direction = "Up events" if ev["abnormal_ret"] and ev["abnormal_ret"] > 0 else "Down events"
        paths.append(pd.DataFrame({"rel_day": np.arange(-5, 21), "car": car, "group": direction}))
    if paths:
        car_paths = pd.concat(paths).groupby(["group", "rel_day"], as_index=False)["car"].mean()
        counts = pd.concat(paths).groupby("group")["rel_day"].count() // 26
        car_paths["n_events"] = car_paths["group"].map(counts)
    else:
        car_paths = pd.DataFrame(columns=["group", "rel_day", "car", "n_events"])

    summary = {
        "n_events": int(len(events)),
        "n_securities": int(events["ticker"].nunique()),
        "by_severity": events["severity"].value_counts().to_dict(),
        "by_type": events["event_type"].value_counts().to_dict(),
        "events_with_20d_outcome": int(events["after_car_20d"].notna().sum()) if "after_car_20d" in events else 0,
        "period_sessions": int(((scan.panel.calendar >= start) & (scan.panel.calendar <= end)).sum()),
        "alerts_per_security_per_100_sessions": None,
    }
    sessions = max(summary["period_sessions"], 1)
    summary["alerts_per_security_per_100_sessions"] = float(len(events) / max(len(scan.features), 1) / sessions * 100)
    return ReplayResult(start, end, events.sort_values("date", ascending=False), summary, outcome_table, car_paths,
                        vol_uplift, notes)


def label_evaluation(events: pd.DataFrame, labelled_days: dict[str, list[pd.Timestamp]], start, end,
                     label_definition: str) -> dict:
    """Precision and recall of the detected events against known labels (ticker -> list of sessions).

    Used with the synthetic demonstration data, where the planted shocks are known. A detected event "matches"
    when it falls on a labelled session for that ticker. Detected events on unlabelled days are not necessarily
    wrong: the generator's random returns have fat tails, so some ordinary-looking days are genuinely unusual.
    """
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    labelled = {(t, pd.Timestamp(d)) for t, days in labelled_days.items() for d in days if start <= pd.Timestamp(d) <= end}
    detected = {(r.ticker, pd.Timestamp(r.date)) for r in events.itertuples()} if len(events) else set()
    tickers = set(labelled_days)
    detected_in_scope = {e for e in detected if e[0] in tickers}
    hits = detected_in_scope & labelled
    precision = len(hits) / len(detected_in_scope) if detected_in_scope else None
    recall = len(hits) / len(labelled) if labelled else None
    return {
        "label_definition": label_definition,
        "labelled_sessions": len(labelled),
        "detected_events_in_scope": len(detected_in_scope),
        "matches": len(hits),
        "precision_vs_proxy": precision,
        "recall_vs_proxy": recall,
        "matched_events": sorted(f"{t}:{d:%Y-%m-%d}" for t, d in hits),
        "missed_labels": sorted(f"{t}:{d:%Y-%m-%d}" for t, d in labelled - hits),
    }
