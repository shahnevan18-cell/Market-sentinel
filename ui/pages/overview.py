"""Market overview page."""
from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from analytics.alert_view import alert_label
from ui import components as c
from ui.nav import open_investigation
from ui.state import app_data


WINDOWS = {"1 week": 5, "1 month": 21, "3 months": 63, "Custom": None}
GRID_KEYS = ("grid_window", "grid_metric", "grid_order", "grid_custom")


def _reset_grid() -> None:
    st.session_state["grid_window"] = "1 month"
    st.session_state["grid_metric"] = "Alert priority"
    st.session_state["grid_order"] = "Highest priority first"
    st.session_state.pop("grid_custom", None)
    st.session_state.pop("grid_chart", None)


def _sentinel_grid_section(scan) -> None:
    cfg = scan.config
    c.section("Sentinel grid",
              "Each row is a watchlist stock and each column an NSE session. Choose what the colour shows, the period "
              "and the row order below.")
    cal_all = scan.panel.calendar
    st.session_state.setdefault("grid_window", "1 month")
    k1, k2, k3, k4 = st.columns([2.9, 2.1, 2.2, 0.9], vertical_alignment="bottom")
    with k1:
        window = st.segmented_control("Period", list(WINDOWS), key="grid_window", width="stretch") or "1 month"
    with k2:
        metric = st.radio("Colour shows", ["Alert priority", "Anomaly intensity"], key="grid_metric", horizontal=True,
                          help="Alert priority: how urgently an alert should be reviewed (the priority score's "
                               "band). Anomaly intensity: how unusual the day's return was (robust z), alert or not.")
    with k3:
        order = st.radio("Row order", ["Highest priority first", "Peer group"], key="grid_order", horizontal=True)
    with k4:
        st.button("Reset view", on_click=_reset_grid, help="One month, alert priority, highest priority first.",
                  width="stretch")
    if window == "Custom":
        options = [d.strftime("%d %b %Y") for d in cal_all]
        default = (options[max(len(options) - 42, 0)], options[-1])
        if st.session_state.get("grid_custom") and not all(v in options for v in st.session_state["grid_custom"]):
            st.session_state.pop("grid_custom")
        lo, hi = st.select_slider("Sessions shown", options=options, value=default, key="grid_custom")
        i0, i1 = options.index(lo), options.index(hi)
        cal = cal_all[i0:i1 + 1]
        if len(cal) > 130:
            st.caption(f"Showing the last 130 of the {len(cal)} sessions selected, to keep cells readable.")
            cal = cal[-130:]
    else:
        cal = cal_all[-WINDOWS[window]:]
    fig, alerts = c.sentinel_grid(scan, cal, metric="priority" if metric == "Alert priority" else "intensity",
                                  order="priority" if order.startswith("Highest") else "group")
    if metric == "Alert priority":
        b = c.priority_bands(cfg)
        st.html(
            '<div class="ms-note">'
            f'<b>Low</b> (under {b[1][1]:.0f}): lower review urgency. '
            f'<b>Moderate</b> ({b[1][1]:.0f} to under {b[2][1]:.0f}): worth monitoring. '
            f'<b>High</b> ({b[2][1]:.0f} to under {b[3][1]:.0f}): needs closer investigation. '
            f'<b>Critical</b> ({b[3][1]:.0f} and above): prioritise analyst review. '
            "These are the same thresholds that label every alert. Neutral cells had no alert; a cross means no data "
            "for that session. Arrows give the direction of the move and the number is the priority score. "
            "High priority means the move deserves attention; it says nothing about whether the stock is a good or "
            "bad investment.</div>")
    else:
        st.html('<div class="ms-note">Colour is the robust z-score of the daily return against the stock\'s previous '
                '60 sessions: teal for an unusually strong rise, red for an unusually strong fall. This is how unusual '
                'the move was, not how urgent it is; outlined cells are alerts. A cross means no data.</div>')
    st.caption("Zoom with the + and - buttons at the top right of the chart, or drag across an area; the house button "
               "resets the zoom. Click an outlined alert cell to inspect it below.")
    sel = st.plotly_chart(fig, width="stretch", config=c.GRID_PLOT_CONFIG, key="grid_chart", on_select="rerun",
                          selection_mode="points")
    picked = None
    pts = (sel.selection.points if sel and hasattr(sel, "selection") else []) or []
    for pt in pts:
        cd = pt.get("customdata") if isinstance(pt, dict) else None
        if cd and isinstance(cd, (list, tuple)) and str(cd[0]) in set(alerts["event_id"]):
            picked = str(cd[0])
    if alerts.empty:
        st.caption("No alerts in this period.")
        return
    ordered = alerts.sort_values(["priority_score", "date"], ascending=[False, False])
    ids = list(ordered["event_id"])
    if picked:
        st.session_state["grid_pick"] = picked
    if st.session_state.get("grid_pick") not in ids:
        st.session_state["grid_pick"] = ids[0]
    labels = {r["event_id"]: alert_label(r) for _, r in ordered.iterrows()}
    pick = st.selectbox("Alert in this period", ids, key="grid_pick", format_func=lambda e: labels.get(e, e),
                        help="Sorted by priority. Clicking an alert cell in the grid selects it here.")
    ev = ordered[ordered["event_id"] == pick].iloc[0].to_dict()
    c.alert_detail_panel(ev, scan.universe.short_label(scan.universe.benchmark), cfg.lookback)
    if st.button("Investigate this alert", type="primary", key="grid_investigate"):
        open_investigation(ev["event_id"], historical=False)


def render() -> None:
    ds, mon = app_data()
    c.page_header("Market overview",
                  "What moved in the latest session, which moves look statistically unusual, and how fresh the data is.",
                  ds)
    if mon is None:
        c.no_data_screen(ds)
        return
    scan = mon.scan
    universe = scan.universe
    last = scan.last_date
    ctxm = scan.market_context(last)
    bench = universe.benchmark
    bench_name = universe.short_label(bench)
    bclose = scan.panel.closes[bench].dropna() if bench in scan.panel.closes else pd.Series(dtype=float)
    bret = scan.panel.returns[bench].dropna() if bench in scan.panel.returns else pd.Series(dtype=float)
    vol20 = bret.iloc[-20:].std() * math.sqrt(252) if len(bret) >= 20 else None
    events = mon.events
    recent_cut = scan.panel.calendar[-30] if len(scan.panel.calendar) >= 30 else scan.panel.calendar[0]
    recent = events[events["date"] >= recent_cut] if not events.empty else events
    latest_ev = events[events["date"] == last] if not events.empty else events

    c.kpi_strip([
        {"label": f"{bench_name} latest close", "value": c.fmt_num(bclose.iloc[-1]) if len(bclose) else "n/a",
         "sub": f"{c.fmt_pct(bret.iloc[-1]) if len(bret) else 'n/a'} on {last:%d %b %Y} (index points)",
         "tone": None},
        {"label": f"{bench_name} realised volatility", "value": c.fmt_pct(vol20, signed=False, digits=1),
         "sub": "last 20 sessions, annualised, historical"},
        {"label": "Watchlist breadth, latest session",
         "value": "n/a" if ctxm.get("share_up") is None else f"{ctxm['share_up']:.0%} up",
         "sub": f"{ctxm.get('n_stocks', 0)} stocks; median {c.fmt_pct(ctxm.get('median_ret'))}"},
        {"label": "Alerts, latest session", "value": str(len(latest_ev)),
         "sub": f"{int((latest_ev['priority_score'] >= scan.config.severity_high).sum()) if len(latest_ev) else 0} high priority or above"},
        {"label": "Alerts, last 30 sessions", "value": str(len(recent)),
         "sub": f"{int((recent['severity'] == 'Critical').sum()) if len(recent) else 0} critical"},
    ])

    _sentinel_grid_section(scan)

    left, right = st.columns([1, 1], gap="large")
    with left:
        c.section("Latest session moves", f"{last:%d %B %Y}, sorted by daily return.")
        st.plotly_chart(c.movers_chart(scan, last), width="stretch", config=c.PLOT_CONFIG)
    with right:
        c.section(f"{bench_name}, sector indices and other indices",
                  "Returns over 1, 5 and 21 sessions to the latest close. Groups without an NSE sector index are "
                  "compared with their peers instead.")
        st.plotly_chart(c.sector_chart(scan), width="stretch", config=c.PLOT_CONFIG)

    c.section("Watchlist", "Every monitored stock with recent performance, realised volatility and alert count.")
    wl = []
    for sec in universe.securities:
        f = scan.features.get(sec.ticker)
        if f is None or f.empty:
            continue
        closes = f["close"].dropna()
        n_alerts = int((recent["ticker"] == sec.ticker).sum()) if len(recent) else 0
        wl.append({
            "Symbol": c.short_symbol(sec.ticker), "Company": sec.name, "Group": sec.sector,
            "Last close (₹)": closes.iloc[-1] if len(closes) else None,
            "1D %": f["ret"].iloc[-1] * 100 if len(f) else None,
            "5D %": (closes.iloc[-1] / closes.iloc[-6] - 1) * 100 if len(closes) > 6 else None,
            "21D %": (closes.iloc[-1] / closes.iloc[-22] - 1) * 100 if len(closes) > 22 else None,
            "Vol 10D %": f["vol_short_ann"].iloc[-1] * 100,
            "z today": f["z_ret"].iloc[-1],
            "Alerts 30D": n_alerts,
            "Last 30 closes": closes.iloc[-30:].round(2).tolist(),
        })
    st.dataframe(pd.DataFrame(wl), hide_index=True, width="stretch", height=min(38 * len(wl) + 40, 520),
                 column_config={
                     "Last close (₹)": st.column_config.NumberColumn(format="%.2f",
                                                                     help="Adjusted close in Indian rupees"),
                     "1D %": st.column_config.NumberColumn(format="%+.2f"),
                     "5D %": st.column_config.NumberColumn(format="%+.2f"),
                     "21D %": st.column_config.NumberColumn(format="%+.2f"),
                     "Vol 10D %": st.column_config.NumberColumn(format="%.1f",
                                                                help="Realised volatility over 10 sessions, annualised"),
                     "z today": st.column_config.NumberColumn(format="%+.2f",
                                                              help="Robust z-score of the latest daily return"),
                     "Alerts 30D": st.column_config.NumberColumn(help="Alerts in the last 30 sessions"),
                     "Last 30 closes": st.column_config.LineChartColumn(width="medium"),
                 })

    c.section("Alerts needing attention", "Highest-priority alerts from the last 10 sessions.")
    cut10 = scan.panel.calendar[-10] if len(scan.panel.calendar) >= 10 else scan.panel.calendar[0]
    top = events[events["date"] >= cut10].sort_values("priority_score", ascending=False).head(10) if not events.empty else events
    if top.empty:
        st.info("No alerts in the last 10 sessions at the current thresholds. Lower the thresholds in the sidebar "
                "or open the historical replay to inspect earlier periods.")
    else:
        view = pd.DataFrame({
            "Date": top["date"].dt.date,
            "Symbol": top["ticker"].map(c.short_symbol),
            "Company": top["name"],
            "Alert type": top["event_type_short"],
            "Return %": top["ret"] * 100,
            "Volume x median": top["volume_ratio"],
            "Priority": top["priority_score"],
            "Severity": top["severity"],
        })
        st.dataframe(view, hide_index=True, width="stretch", column_config={
            "Return %": st.column_config.NumberColumn(format="%+.2f"),
            "Volume x median": st.column_config.NumberColumn(format="%.1f"),
            "Priority": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f"),
        })
        options = list(top["event_id"])
        col1, col2 = st.columns([3, 1], vertical_alignment="bottom")
        with col1:
            labels = {r["event_id"]: alert_label(r) for _, r in top.iterrows()}
            chosen = st.selectbox("Alert to investigate", options, key="overview_pick",
                                  format_func=lambda e: labels.get(e, e))
        with col2:
            if st.button("Open in workspace", type="primary", width="stretch"):
                open_investigation(chosen, historical=False)

    vol_alerts = latest_ev[latest_ev["event_type"].str.contains("Volume")] if len(latest_ev) else latest_ev
    if len(vol_alerts):
        c.section("Unusual volume, latest session")
        for _, r in vol_alerts.iterrows():
            st.markdown(f"- {r['name']} ({c.short_symbol(r['ticker'])}) traded {r['volume_ratio']:.1f}x its 60-day median volume "
                        f"(robust z {r['z_volume']:+.1f}) with a return of {r['ret']:+.2%}.")

    with st.expander("Data freshness and provider status"):
        f = ds.freshness()
        st.markdown(f"Mode: **{ds.mode}**. Provider: {ds.provider_label}. Dataset loaded "
                    f"{c.fmt_ist(ds.loaded_at)}; newest retrieval {c.fmt_ist(f.get('newest_retrieval'))}. "
                    f"Expected latest session: {f.get('expected_session') or 'n/a'}. Bar dates are NSE trading "
                    f"sessions; retrieval times are when this app fetched them (shown in IST, stored in UTC).")
        rows = []
        for sym, m in ds.meta.items():
            q = ds.quality.get(sym)
            rows.append({"Symbol": sym, "Name": universe.display_name(sym), "Status": m.status,
                         "Last bar": m.last_date, "Retrieved (IST)": c.fmt_ist(m.retrieved_at) if m.retrieved_at else None,
                         "Currency": m.currency, "Exchange": m.exchange, "Quality": q.status if q else "n/a",
                         "Notes": " | ".join(i.message for i in (q.issues if q else []))[:180] or m.note})
        for sym, err in ds.failures.items():
            rows.append({"Symbol": sym, "Name": universe.display_name(sym), "Status": "unavailable", "Last bar": None,
                         "Retrieved (IST)": None, "Currency": None, "Exchange": None, "Quality": "Error",
                         "Notes": err})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        for n in ds.notes:
            st.caption(n)
