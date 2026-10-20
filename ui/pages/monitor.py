"""Anomaly monitor page: every alert with its measures, filters and a detail view."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from analytics.alert_view import ALERT_TYPES, SEVERITIES, AlertFilters, alert_label, filter_alerts, monitor_state
from analytics.event_scoring import score_components
from ui import components as c
from ui.nav import open_investigation
from ui.state import app_data

KEYS = {"tickers": "mon_tickers", "dates": "mon_dates", "sev": "mon_sev", "types": "mon_types", "min": "mon_min"}


def _defaults(dmin, dmax) -> dict:
    start = max(dmin, (pd.Timestamp(dmax) - pd.Timedelta(days=90)).date())
    return {"tickers": [], "dates": (start, dmax), "sev": list(SEVERITIES), "types": list(ALERT_TYPES), "min": 0}


def _reset_filters(dmin, dmax) -> None:
    for name, value in _defaults(dmin, dmax).items():
        st.session_state[KEYS[name]] = value


def _sanitise_state(options: list[str], dmin, dmax) -> None:
    """Keep remembered filter values valid when the data changes (for example live to demonstration data)."""
    d = _defaults(dmin, dmax)
    for name, value in d.items():
        st.session_state.setdefault(KEYS[name], value)
    st.session_state[KEYS["tickers"]] = [t for t in st.session_state[KEYS["tickers"]] if t in options]
    dates = st.session_state[KEYS["dates"]]
    if not isinstance(dates, (list, tuple)) or any(x < dmin or x > dmax for x in dates):
        st.session_state[KEYS["dates"]] = d["dates"]


def render() -> None:
    ds, mon = app_data()
    c.page_header("Anomaly monitor",
                  "Every alert raised by the Sentinel Monitor, the measures that triggered it and its historical baseline.",
                  ds)
    state, why = monitor_state(mon)
    if state == "no_data":
        if mon is None:
            c.no_data_screen(ds)
        else:
            c.empty_state("Market data unavailable", why)
        return
    if state == "no_alerts":
        c.empty_state("No alerts at the current thresholds", why)
        return
    scan = mon.scan
    cfg = scan.config
    universe = scan.universe
    bench_name = universe.short_label(universe.benchmark)
    events = mon.events

    dmin, dmax = events["date"].min().date(), events["date"].max().date()
    ticker_options = sorted(events["ticker"].unique())
    _sanitise_state(ticker_options, dmin, dmax)
    f1, f2, f3, f4, f5 = st.columns([2.2, 1.6, 1.4, 1.8, 1.2])
    with f1:
        tickers = st.multiselect("Securities", ticker_options, key=KEYS["tickers"], placeholder="All securities",
                                 format_func=lambda t: f"{c.short_symbol(t)}  {universe.display_name(t)}")
    with f2:
        dr = st.date_input("Date range", key=KEYS["dates"], min_value=dmin, max_value=dmax)
    with f3:
        sev = st.multiselect("Severity", SEVERITIES, key=KEYS["sev"], placeholder="All severities")
    with f4:
        types = st.multiselect("Alert type", ALERT_TYPES, key=KEYS["types"], placeholder="All alert types")
    with f5:
        min_score = st.number_input("Min. priority", 0, 100, step=5, key=KEYS["min"])

    start = end = None
    if isinstance(dr, (list, tuple)) and len(dr) == 2:
        start, end = dr
    elif isinstance(dr, (list, tuple)) and len(dr) == 1:
        start = dr[0]
    result = filter_alerts(events, AlertFilters(tickers=list(tickers), start=start, end=end, severities=list(sev),
                                                types=list(types), min_score=float(min_score or 0)))
    view = result.view
    for note in result.notes:
        st.caption(note)
    st.caption(f"{len(view)} alert(s) shown of {result.total} detected. Weights: price {cfg.w_price:.0%}, "
               f"market-relative {cfg.w_abnormal:.0%}, volume {cfg.w_volume:.0%}, volatility regime "
               f"{cfg.w_vol_regime:.0%}. Click a row or use the selector below to inspect an alert.")
    if view.empty:
        c.empty_state("No alerts match these filters",
                      f"{result.total} alert(s) exist in the data, but none meet every filter above. Widen the date "
                      "range, lower the minimum priority or reset the filters.")
        st.button("Reset filters", on_click=_reset_filters, args=(dmin, dmax), key="mon_reset_empty")
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
    st.button("Reset filters", on_click=_reset_filters, args=(dmin, dmax), key="mon_reset")

    ids = list(view["event_id"])
    rows = sel.selection.rows if sel and hasattr(sel, "selection") else []
    clicked = ids[rows[0]] if rows and rows[0] < len(ids) else None
    if clicked and clicked != st.session_state.get("mon_last_click"):
        st.session_state["mon_pick"] = clicked          # a new table click drives the selector
    st.session_state["mon_last_click"] = clicked
    if st.session_state.get("mon_pick") not in ids:
        st.session_state["mon_pick"] = ids[0]
    labels = {r["event_id"]: alert_label(r) for _, r in view.iterrows()}
    st.divider()
    event_id = st.selectbox("Selected alert", ids, key="mon_pick", format_func=lambda e: labels.get(e, e),
                            help="Type a symbol to jump to it. The table row you click is selected here too.")
    ev = view[view["event_id"] == event_id].iloc[0].to_dict()
    c.alert_detail_panel(ev, bench_name, cfg.lookback)
    b1, b2, _ = st.columns([1.3, 1.3, 3])
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
        # A group without a sector index has no symbol here. pandas 3 stores that missing text as NaN, which is
        # truthy, so test for a real string rather than for truthiness.
        sector_index = ev.get("sector_index")
        has_index = isinstance(sector_index, str) and bool(sector_index)
        base = pd.DataFrame([
            ("Baseline median return", c.fmt_pct(ev["ret_median"])),
            ("Beta (120 sessions before)", c.fmt_num(ev["beta"])),
            (f"{bench_name} return (z)", f"{c.fmt_pct(ev['mkt_ret'])} ({c.fmt_z(ev['z_mkt'])})"),
            ((f"{universe.short_label(sector_index)} return (z)", f"{c.fmt_pct(ev['sector_ret'])} ({c.fmt_z(ev['z_sector'])})")
             if has_index else ("Sector index", "none configured for this group (peer comparison only)")),
            ("Return vs peer median (z)", f"{c.fmt_pct(ev['rel_peer_ret'])} ({c.fmt_z(ev['z_rel_peer'])})"),
            ("Volume / 60-day median", f"{c.fmt_num(ev['volume_ratio'], 1)}x of {c.fmt_big(ev['volume_median'])} shares"),
            ("Volatility regime ratio", c.fmt_num(ev["vol_ratio"])),
            ("Episode", f"day {int(ev.get('episode_day', 1))} of an alert run starting {str(ev.get('episode_id', ev['event_id'])).split(':')[-1]}"),
        ], columns=["Measure", "Value"])
        st.dataframe(base, hide_index=True, width="stretch")
