"""Historical replay: walk-forward detection over a past period, then compare alerts with later outcomes."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.historical_replay import label_evaluation, run_replay
from config.market import DISCLOSURE_TERMS_NOTE, OFFICIAL_DISCLOSURE_LINKS
from providers.market_data import demo_planted_sessions, demo_scenarios
from ui import components as c
from ui.nav import open_investigation
from ui.state import app_data


@st.cache_resource(max_entries=6, show_spinner=False)
def _replay(key: str, start: str, end: str, _scan):
    return run_replay(_scan, start, end)


def render() -> None:
    ds, mon = app_data()
    c.page_header("Historical replay",
                  "Replay a past period as if each day were live: alerts use only the information available at that "
                  "day's close. What happened next is shown separately, to evaluate the alerts.", ds)
    if mon is None:
        c.no_data_screen(ds)
        return
    scan = mon.scan
    cfg = scan.config
    cal = scan.panel.calendar
    if len(cal) < cfg.beta_window + 30:
        st.info("Not enough history for a replay. At least about 150 sessions are needed.")
        return
    first_ok = cal[cfg.beta_window]
    last = cal[-1]
    default_start = max(first_ok, cal[-250] if len(cal) > 250 else first_ok)

    a, b, d = st.columns([1.3, 1.3, 2.4], vertical_alignment="bottom")
    with a:
        start = st.date_input("Replay from", value=default_start.date(), min_value=first_ok.date(), max_value=last.date())
    with b:
        end = st.date_input("Replay to", value=last.date(), min_value=first_ok.date(), max_value=last.date())
    with d:
        st.caption(f"The first {cfg.beta_window} sessions are reserved for estimating baselines and beta, so the "
                   f"earliest replay date is {first_ok:%d %b %Y}.")
    if pd.Timestamp(start) >= pd.Timestamp(end):
        st.warning("Choose a start date before the end date.")
        return
    if ds.is_demo:
        _demo_scenarios(mon)
    key = f"{ds.mode}|{ds.loaded_at}|{sorted(cfg.as_dict().items())}"
    rr = _replay(key, f"{pd.Timestamp(start):%Y-%m-%d}", f"{pd.Timestamp(end):%Y-%m-%d}", scan)
    if rr.events.empty:
        st.info("No alerts in this period with the current thresholds.")
        return

    out = rr.outcome_table.set_index("horizon_days")
    vu = rr.vol_uplift.set_index("horizon_days")
    cont5 = out.loc[5, "continuation_rate"] if 5 in out.index else None
    ratio5 = vu.loc[5, "ratio"] if 5 in vu.index else None
    c.kpi_strip([
        {"label": "Alerts in period", "value": str(rr.summary["n_events"]),
         "sub": f"{rr.summary['n_securities']} securities, {rr.summary['period_sessions']} sessions"},
        {"label": "Alert rate", "value": f"{rr.summary['alerts_per_security_per_100_sessions']:.1f}",
         "sub": "per security per 100 sessions"},
        {"label": "Moves that continued, next 5 days", "value": c.fmt_pct(cont5, False, 0) if cont5 is not None else "n/a",
         "sub": "share with same-sign abnormal return afterwards"},
        {"label": "Volatility after alerts", "value": f"{ratio5:.2f}x" if ratio5 else "n/a",
         "sub": "mean |return| next 5 days vs all days"},
        {"label": "Alerts with 20-day outcome", "value": str(rr.summary["events_with_20d_outcome"]),
         "sub": "later alerts lack enough future data"},
    ])

    left, right = st.columns([1, 1], gap="large")
    with left:
        c.section("Average path around alerts (event study)",
                  "Cumulative abnormal return from 5 days before to 20 days after, with alpha and beta frozen at "
                  "the alert date. Day 0 is the alert. The shaded part was not known when the alert fired.")
        st.plotly_chart(c.car_chart(rr.car_paths), width="stretch", config=c.PLOT_CONFIG)
    with right:
        c.section("Alert strength against what happened next",
                  "Each dot is one alert. The horizontal axis was known at detection; the vertical axis was observed later.")
        st.plotly_chart(c.outcome_scatter(rr.events, 5), width="stretch", config=c.PLOT_CONFIG)

    c.section("Outcome summary by horizon",
              "Descriptive statistics only. There is no ground-truth label for a correct alert, so no accuracy is claimed.")
    tbl = rr.outcome_table.merge(rr.vol_uplift[["horizon_days", "mean_abs_return_after_alerts", "mean_abs_return_all_days", "ratio"]],
                                 on="horizon_days")
    show = pd.DataFrame({
        "Horizon (sessions)": tbl["horizon_days"],
        "Alerts with data": tbl["events_with_data"],
        "Mean CAR after up alerts %": tbl["mean_after_car_up_events"] * 100,
        "Mean CAR after down alerts %": tbl["mean_after_car_down_events"] * 100,
        "Continuation rate %": tbl["continuation_rate"] * 100,
        "Mean |return| after alerts %": tbl["mean_abs_return_after_alerts"] * 100,
        "Mean |return| all days %": tbl["mean_abs_return_all_days"] * 100,
    })
    st.dataframe(show, hide_index=True, width="stretch",
                 column_config={k: st.column_config.NumberColumn(format="%+.2f" if "CAR" in k else "%.2f")
                                for k in show.columns if "%" in k})

    c.section("Replayed alerts", "Known at detection on the left, observed afterwards on the right.")
    ev = rr.events
    table = pd.DataFrame({
        "Date": ev["date"].dt.date,
        "Symbol": ev["ticker"].map(c.short_symbol),
        "Company": ev["name"],
        "Alert type": ev["event_type_short"],
        "Priority": ev["priority_score"],
        "Severity": ev["severity"],
        "Return % (known)": ev["ret"] * 100,
        "Abnormal z (known)": ev["z_abn"],
        "Volume x (known)": ev["volume_ratio"],
        "Next day % (later)": ev["after_ret_1d"] * 100,
        "CAR 5d % (later)": ev["after_car_5d"] * 100,
        "CAR 20d % (later)": ev["after_car_20d"] * 100,
    })
    sel = st.dataframe(table, hide_index=True, width="stretch", height=340, on_select="rerun",
                       selection_mode="single-row", key="replay_table",
                       column_config={
                           "Priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
                           "Return % (known)": st.column_config.NumberColumn(format="%+.2f"),
                           "Abnormal z (known)": st.column_config.NumberColumn(format="%+.2f"),
                           "Volume x (known)": st.column_config.NumberColumn(format="%.1f"),
                           "Next day % (later)": st.column_config.NumberColumn(format="%+.2f"),
                           "CAR 5d % (later)": st.column_config.NumberColumn(format="%+.2f"),
                           "CAR 20d % (later)": st.column_config.NumberColumn(format="%+.2f"),
                       })
    rows = sel.selection.rows if sel and hasattr(sel, "selection") else []
    if rows:
        chosen = ev.iloc[rows[0]]
        l2, r2 = st.columns([3, 1], vertical_alignment="center")
        with l2:
            st.plotly_chart(c.event_chart(scan, chosen["ticker"], chosen["date"], before=90, after=20,
                                          title=f"{chosen['name']} around the alert on {chosen['date']:%d %b %Y}",
                                          price_label="Price (synthetic ₹)" if ds.is_demo else "Price (₹)"),
                            width="stretch", config=c.PLOT_CONFIG)
        with r2:
            st.markdown("Investigate this alert exactly as it could have been investigated that evening: prices up to "
                        "the alert date only, and no news published after that day's close.")
            if st.button("Investigate as of that day", type="primary", width="stretch"):
                open_investigation(chosen["event_id"], historical=True)
    else:
        st.caption("Select a row to see the price path around that alert and to investigate it as of that day.")

    if ds.is_demo:
        with st.expander("Check against the planted scenarios (demonstration data)"):
            st.markdown(
                "The synthetic generator planted known shocks, so here the detector can be checked against a true "
                "label. Recall is the share of planted stock-days that raised an alert. Precision is the share of "
                "alerts that fall on a planted stock-day; it is low by design, because the generator's random returns "
                "have fat tails and some unplanned days are genuinely unusual. Real NSE data has no such labels.")
            for title, specific in (("Stock-specific shocks only", True), ("All planted shocks", False)):
                res = label_evaluation(rr.events, demo_planted_sessions(stock_specific_only=specific), start, end,
                                       title)
                st.markdown(f"**{title}**")
                c.kpi_strip([
                    {"label": "Planted stock-days in period", "value": str(res["labelled_sessions"])},
                    {"label": "Detected", "value": str(res["matches"])},
                    {"label": "Recall", "value": c.fmt_pct(res["recall_vs_proxy"], False, 0)},
                    {"label": "Precision", "value": c.fmt_pct(res["precision_vs_proxy"], False, 0)},
                ])
                if res["missed_labels"]:
                    st.caption("Not detected: " + ", ".join(res["missed_labels"]))
    else:
        with st.expander("Why there is no accuracy score for live NSE data"):
            st.markdown(
                "There is no ground-truth list of days that deserved an alert. A natural proxy label would be the "
                "dates of quarterly results and board meetings, but those are published as NSE and BSE "
                "announcements, which this app does not collect automatically: " + DISCLOSURE_TERMS_NOTE
                + " To compare alerts with results dates by hand, use:")
            for link in OFFICIAL_DISCLOSURE_LINKS[:3]:
                st.markdown(f"- [{link['label']}]({link['url']}): {link['how']}")


def _demo_scenarios(mon) -> None:
    """Designed demonstration scenarios, ready to investigate as of their own day (no waiting for a live alert)."""
    table = demo_scenarios()
    events = mon.events
    detected = set(events["event_id"]) if not events.empty else set()
    rows, options = [], []
    for row in table.itertuples():
        ids = [f"{t}:{row.date:%Y-%m-%d}" for t in row.affected]
        hits = events[events["event_id"].isin(ids)].sort_values("priority_score", ascending=False) \
            if not events.empty else events
        top = hits.iloc[0] if len(hits) else None
        rows.append({"Date": row.date.date(), "Scenario": row.description,
                     "Stocks affected": ", ".join(c.short_symbol(t) for t in row.affected[:4])
                     + (f" and {len(row.affected) - 4} more" if len(row.affected) > 4 else ""),
                     "Alerts raised": len(hits),
                     "Strongest alert": None if top is None else f"{c.short_symbol(top['ticker'])} "
                                                                  f"({top['severity']}, {top['priority_score']:.0f})"})
        if top is not None and top["event_id"] in detected:
            options.append((top["event_id"], f"{row.date:%d %b %Y}: {row.description}"))
    c.section("Designed demonstration scenarios",
              "SYNTHETIC DEMONSTRATION DATA. Each row is a shock planted in the fictional dataset, with its fictional "
              "announcement where there is one. Investigate any of them as of its own day, without waiting for a "
              "live alert.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if options:
        a, b = st.columns([3, 1], vertical_alignment="bottom")
        with a:
            pick = st.selectbox("Scenario to investigate", [o[0] for o in options], key="demo_scenario_pick",
                                format_func=lambda e: dict(options).get(e, e))
        with b:
            if st.button("Investigate as of that day", key="demo_scenario_go", type="primary", width="stretch"):
                open_investigation(pick, historical=True)
