"""Anomaly monitor page: every alert with its measures, filters and a detail view."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.event_scoring import score_components
from ui import components as c
from ui.nav import open_investigation
from ui.state import app_data

TYPE_OPTIONS = ["Large price move", "Market-relative move", "Volume spike"]
SEVERITIES = ["Critical", "High", "Moderate", "Low"]


def render() -> None:
    ds, mon = app_data()
    c.page_header("Anomaly monitor",
                  "Every alert raised by the Sentinel Monitor, the measures that triggered it and its historical baseline.",
                  ds)
    if mon is None:
        c.no_data_screen(ds)
        return
    scan = mon.scan
    cfg = scan.config
    universe = scan.universe
    bench_name = universe.short_label(universe.benchmark)
    events = mon.events
    if events.empty:
        st.info("No alerts at the current thresholds. Lower them in the sidebar to see more events.")
        return

    dmin, dmax = events["date"].min().date(), events["date"].max().date()
    default_start = max(dmin, (pd.Timestamp(dmax) - pd.Timedelta(days=90)).date())
    f1, f2, f3, f4, f5 = st.columns([2.2, 1.6, 1.4, 1.8, 1.2])
    with f1:
        tickers = st.multiselect("Securities", sorted(events["ticker"].unique()), placeholder="All securities",
                                 format_func=lambda t: f"{c.short_symbol(t)}  {universe.display_name(t)}")
    with f2:
        dr = st.date_input("Date range", value=(default_start, dmax), min_value=dmin, max_value=dmax)
    with f3:
        sev = st.multiselect("Severity", SEVERITIES, default=SEVERITIES)
    with f4:
        types = st.multiselect("Alert type", TYPE_OPTIONS, default=TYPE_OPTIONS)
    with f5:
        min_score = st.number_input("Min. priority", 0, 100, 0, 5)

    view = events.copy()
    if tickers:
        view = view[view["ticker"].isin(tickers)]
    if isinstance(dr, (list, tuple)) and len(dr) == 2:
        view = view[(view["date"] >= pd.Timestamp(dr[0])) & (view["date"] <= pd.Timestamp(dr[1]))]
    view = view[view["severity"].isin(sev)]
    view = view[view["event_types"].apply(lambda ts: any(t in types for t in ts))]
    view = view[view["priority_score"] >= min_score]
    view = view.sort_values(["date", "priority_score"], ascending=[False, False]).reset_index(drop=True)

    st.caption(f"{len(view)} alert(s) shown of {len(events)} detected. Weights: price {cfg.w_price:.0%}, "
               f"market-relative {cfg.w_abnormal:.0%}, volume {cfg.w_volume:.0%}, volatility regime {cfg.w_vol_regime:.0%}. "
               "Select a row to inspect it.")
    if view.empty:
        st.info("No alerts match these filters.")
        return

    table = pd.DataFrame({
        "Date": view["date"].dt.date,
        "Symbol": view["ticker"].map(c.short_symbol),
        "Company": view["name"],
        "Alert type": view["event_type_short"],
        "Priority": view["priority_score"],
        "Severity": view["severity"],
        "Return %": view["ret"] * 100,
        "Return z": view["z_ret"],
        "Abnormal %": view["abnormal_ret"] * 100,
        "Abnormal z": view["z_abn"],
        "Volume x": view["volume_ratio"],
        "Volume z": view["z_volume"],
        f"{bench_name} %": view["mkt_ret"] * 100,
    })
    sel = st.dataframe(
        table, hide_index=True, width="stretch", height=330, on_select="rerun", selection_mode="single-row",
        key="monitor_table",
        column_config={
            "Return %": st.column_config.NumberColumn(format="%+.2f", help="Simple daily return, adjusted close"),
            "Return z": st.column_config.NumberColumn(format="%+.2f", help="Robust z against the previous baseline window"),
            "Abnormal %": st.column_config.NumberColumn(format="%+.2f", help="Return minus market-model expectation"),
            "Abnormal z": st.column_config.NumberColumn(format="%+.2f"),
            "Volume x": st.column_config.NumberColumn(format="%.1f", help="Volume divided by the prior 60-day median"),
            "Volume z": st.column_config.NumberColumn(format="%+.2f"),
            f"{bench_name} %": st.column_config.NumberColumn(format="%+.2f", help="Benchmark return the same day"),
            "Priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
        })
    rows = sel.selection.rows if sel and hasattr(sel, "selection") else []
    idx = rows[0] if rows else 0
    ev = view.iloc[idx].to_dict()

    st.divider()
    head_l, head_r = st.columns([3, 2], vertical_alignment="center")
    with head_l:
        st.html(f'<div style="font-size:1.2rem;font-weight:600">{c.esc(ev["name"])} ({c.esc(c.short_symbol(ev["ticker"]))})</div>'
                f'<div class="ms-note">{ev["date"]:%A %d %B %Y} &nbsp; {c.severity_html(ev["severity"])} &nbsp; '
                f'priority {ev["priority_score"]:.0f} of 100 &nbsp; {c.esc(ev["event_type"])}</div>')
    with head_r:
        b1, b2 = st.columns(2)
        with b1:
            if st.button("Investigate this alert", type="primary", width="stretch"):
                open_investigation(ev["event_id"], historical=False)
        with b2:
            if st.button("Investigate as of that day", width="stretch",
                         help="Uses only prices and news available at that day's close."):
                open_investigation(ev["event_id"], historical=True)

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.plotly_chart(c.event_chart(scan, ev["ticker"], ev["date"], before=120,
                                      price_label="Price (synthetic ₹)" if ds.is_demo else "Price (₹)"),
                        width="stretch", config=c.PLOT_CONFIG)
        st.plotly_chart(c.zscore_chart(scan, ev["ticker"], ev["date"]), width="stretch", config=c.PLOT_CONFIG)
    with right:
        c.section("Why it triggered")
        for t in ev["triggers"]:
            st.markdown(f"- {t}")
        c.section("Priority score breakdown")
        sc = score_components(ev["z_ret"], ev["z_abn"], ev["z_volume"], ev["vol_ratio"], cfg)
        short = {"price": "Price move", "abnormal": "Market-relative", "volume": "Volume", "vol_regime": "Volatility regime"}
        st.dataframe(pd.DataFrame([{"Component": short[k], "Normalised": p["normalised"], "Weight": p["weight"],
                                    "Points": p["points"]} for k, p in sc["components"].items()]),
                     hide_index=True, width="stretch",
                     column_config={"Normalised": st.column_config.NumberColumn(format="%.2f"),
                                    "Weight": st.column_config.NumberColumn(format="%.2f"),
                                    "Points": st.column_config.NumberColumn(format="%.1f")})
        c.section("Baseline and context")
        base = pd.DataFrame([
            ("Baseline median return", c.fmt_pct(ev["ret_median"])),
            ("Beta (120 sessions before)", c.fmt_num(ev["beta"])),
            (f"{bench_name} return (z)", f"{c.fmt_pct(ev['mkt_ret'])} ({c.fmt_z(ev['z_mkt'])})"),
            ((f"{universe.short_label(ev['sector_index'])} return (z)", f"{c.fmt_pct(ev['sector_ret'])} ({c.fmt_z(ev['z_sector'])})")
             if ev.get("sector_index") else ("Sector index", "none configured for this group (peer comparison only)")),
            ("Return vs peer median (z)", f"{c.fmt_pct(ev['rel_peer_ret'])} ({c.fmt_z(ev['z_rel_peer'])})"),
            ("Volume / 60-day median", f"{c.fmt_num(ev['volume_ratio'], 1)}x of {c.fmt_big(ev['volume_median'])} shares"),
            ("Volatility regime ratio", c.fmt_num(ev["vol_ratio"])),
            ("Episode", f"day {int(ev.get('episode_day', 1))} of an alert run starting {str(ev.get('episode_id', ev['event_id'])).split(':')[-1]}"),
        ], columns=["Measure", "Value"])
        st.dataframe(base, hide_index=True, width="stretch")
