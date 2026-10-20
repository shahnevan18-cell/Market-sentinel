"""Intraday watch on the Market overview page: 5-minute bars with an optional timed refresh.

The refresh is a Streamlit timed fragment: it reruns only this panel, only while the page is open in a browser,
and only requests bars from the provider through the shared in-memory store (one request per process per bar
interval at most). It never calls the LLM and never touches the daily analytics.
"""
from __future__ import annotations

import inspect
from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics.intraday import MIN_SESSIONS, Z_FLAG, IntradayScan, scan_intraday
from config.watchlist import get_universe
from providers.intraday import (DEFAULT_REFRESH_MINUTES, INTERVAL_MINUTES, REFRESH_CHOICES, IntradayView, bar_end,
                                shared_store, to_ist)
from ui import components as c

STATUS_TONE = {"fresh": "live", "waiting": "", "cached": "", "stale": "warn", "unavailable": "bad"}


def _pill(text: str, cls: str = "") -> str:
    return f'<span class="ms-pill {cls}">{text}</span>'


def _status_html(view: IntradayView) -> str:
    snap = view.snapshot
    pills = [_pill(f"Status <b>{c.esc(view.label)}</b>", STATUS_TONE[view.status])]
    if view.last_attempt_at is not None:
        pills.append(_pill(f"Last request <b>{to_ist(view.last_attempt_at):%H:%M:%S} IST</b>"))
    if view.latest_bar is not None:
        end = bar_end(view.latest_bar, INTERVAL_MINUTES[view.interval])
        pills.append(_pill(f"Latest complete bar <b>{view.latest_bar:%a %d %b, %H:%M} to {end:%H:%M} IST</b>"))
    pills.append(_pill(f"Interval <b>{INTERVAL_MINUTES[view.interval]} minutes</b>"))
    pills.append(_pill("Source <b>" + c.esc(snap.source if snap else "Yahoo Finance via yfinance") + "</b>"))
    pills.append(_pill("This view <b>" + ("sent a request" if view.requested else "used no request") + "</b>"))
    return '<div class="ms-pills left">' + "".join(pills) + "</div>"


def _chart(scan: IntradayScan, name: str, received_at) -> go.Figure | None:
    """Closes of complete bars plotted at the time each bar ended; a still-forming bar's latest price is plotted at
    the time it was received, as a hollow marker."""
    bars = scan.benchmark_bars
    if bars is None or bars.empty:
        return None
    step = pd.Timedelta(minutes=scan.minutes)
    done = bars[~bars["partial"].astype(bool)]
    forming = bars[bars["partial"].astype(bool)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=done.index + step, y=done["close"], mode="lines", name=f"{name}, 5-minute closes",
                             line={"width": 2}, customdata=[f"{t:%H:%M}" for t in done.index],
                             hovertemplate="Bar %{customdata} to %{x|%H:%M} IST<br>close %{y:,.2f}<extra></extra>"))
    if len(forming) and received_at is not None:
        fig.add_trace(go.Scatter(x=[pd.Timestamp(to_ist(received_at))], y=[forming["close"].iloc[-1]],
                                 mode="markers", name="Bar still forming (excluded)",
                                 marker={"symbol": "circle-open", "size": 9},
                                 hovertemplate="Still forming at %{x|%H:%M} IST<br>%{y:,.2f} (excluded from the "
                                               "statistics)<extra></extra>"))
    if scan.benchmark_prev_close:
        fig.add_hline(y=scan.benchmark_prev_close, line_dash="dot", line_width=1,
                      annotation_text="previous session's last bar", annotation_position="bottom right")
    fig.update_layout(height=260, margin={"l": 10, "r": 10, "t": 36, "b": 10}, showlegend=False,
                      title={"text": f"{name}, session of {scan.session:%a %d %b %Y} (IST)", "font": {"size": 13}})
    fig.update_xaxes(tickformat="%H:%M")
    return fig


def _table(scan: IntradayScan) -> pd.DataFrame:
    step = pd.Timedelta(minutes=scan.minutes)
    rows = []
    for _, r in scan.rows.iterrows():
        bt = r.get("bar_time")
        has_bar = bt is not None and pd.notna(bt)
        peak_t, peak_z = r.get("today_peak_time"), r.get("today_peak_z")
        rows.append({
            "Stock": r["name"],
            "Last": r.get("last_close"),
            "Vs previous session": r.get("change_today") * 100 if pd.notna(r.get("change_today")) else None,
            "Latest bar (IST)": f"{bt:%H:%M}-{bt + step:%H:%M}" if has_bar else "",
            "5-min return %": r.get("bar_return") * 100 if pd.notna(r.get("bar_return")) else None,
            "z, time of day": r.get("z_return"),
            "z vs NIFTY 50": r.get("z_relative"),
            "Volume vs usual": r.get("volume_ratio"),
            "z, volume": r.get("z_volume"),
            "Baseline sessions": r.get("n_sessions"),
            "Largest move today": f"{peak_t:%H:%M} (z {peak_z:+.1f})" if pd.notna(peak_t) and pd.notna(peak_z) else "",
            "Flag": ("Unusual: " + r["reasons"]) if r.get("flagged") else "",
            "Note": r.get("note") or "",
        })
    out = pd.DataFrame(rows)
    for col in ("Last", "Vs previous session", "5-min return %", "z, time of day", "z vs NIFTY 50", "Volume vs usual",
                "z, volume", "Baseline sessions"):
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def render(ds) -> None:
    c.section("Intraday watch (5-minute bars)",
              "Optional. NIFTY 50 and the 25 watchlist stocks in 5-minute bars, judged against the same time of day "
              "in earlier sessions. Separate from the daily alerts: it changes no daily score and starts no "
              "investigation.")
    if ds.mode != "live":
        st.caption("Intraday bars are available with live data only. The demonstration dataset has daily bars, and "
                   "no intraday bars are simulated.")
        return
    universe = get_universe("live")
    symbols = [universe.benchmark] + list(universe.tickers)
    names = {s: universe.short_label(s) for s in symbols}
    a, b, _ = st.columns([1, 1, 2], vertical_alignment="bottom")
    with a:
        auto = st.toggle("Auto-refresh", key="intraday_auto",
                         help="Requests new 5-minute bars on a timer while this page is open. Off by default.")
    with b:
        every = st.selectbox("Refresh every", REFRESH_CHOICES, index=REFRESH_CHOICES.index(DEFAULT_REFRESH_MINUTES),
                             format_func=lambda m: f"{m:g} minutes", key="intraday_every", disabled=not auto)

    @st.fragment(run_every=timedelta(minutes=every) if auto else None)
    def panel() -> None:
        manual = st.button("Refresh now", key="intraday_refresh")
        mode = "manual" if manual else ("auto" if auto else "peek")
        store = shared_store()
        if mode == "peek":
            view = store.get(symbols, benchmark=universe.benchmark, mode="peek")
        else:
            with st.spinner("Requesting 5-minute bars"):
                view = store.get(symbols, benchmark=universe.benchmark, mode=mode)
        st.html(_status_html(view))
        st.caption(view.explanation)
        if view.snapshot is None or not view.history:
            return
        scan = scan_intraday(view.history, universe.benchmark, INTERVAL_MINUTES[view.interval], names)
        if scan.session is None:
            st.caption(" ".join(scan.notes))
            return
        flagged = scan.flagged
        if len(flagged):
            items = "".join(f"<li><b>{c.esc(r['name'])}</b> at {r['bar_time']:%H:%M} IST: {c.esc(r['reasons'])}</li>"
                            for _, r in flagged.iterrows())
            st.html(f'<div class="ms-alert"><b>Unusual for the time of day</b><ul>{items}</ul></div>')
        else:
            st.caption(f"No latest complete bar is unusual for its time of day (threshold |z| of {Z_FLAG:g} or more "
                       f"against at least {MIN_SESSIONS} earlier sessions).")
        earlier = [r for _, r in scan.rows.iterrows()
                   if pd.notna(r.get("today_peak_z")) and abs(r["today_peak_z"]) >= Z_FLAG
                   and pd.notna(r.get("today_peak_time")) and r["today_peak_time"] != r.get("bar_time")]
        if earlier:
            st.caption("Earlier in this session, 5-minute moves unusual for their time of day: " + "; ".join(
                f"{r['name']} at {r['today_peak_time']:%H:%M} IST (z {r['today_peak_z']:+.1f})" for r in earlier) + ".")
        if scan.rows["partial_excluded"].any():
            st.caption("A bar still forming at the last request is excluded from every statistic; only complete bars "
                       "are compared.")
        fig = _chart(scan, names.get(universe.benchmark, universe.benchmark), view.snapshot.received_at)
        if fig is not None:
            st.plotly_chart(fig, width="stretch", config=c.PLOT_CONFIG)
        with st.expander(f"All {len(scan.rows)} symbols, latest complete bar (most unusual first)",
                         expanded=bool(len(flagged))):
            _table_view(scan)
        snap = view.snapshot
        if snap.carried:
            st.caption("Earlier bars kept for: " + ", ".join(f"{names.get(s, s)} (received "
                                                              f"{to_ist(t):%H:%M} IST)" for s, t in snap.carried.items()))
        if snap.failures:
            with st.expander(f"Symbols without bars in the last request ({len(snap.failures)})"):
                for sym, why in snap.failures.items():
                    st.caption(f"{names.get(sym, sym)}: {why}")

    panel()
    st.caption("Auto-refresh runs only while this page is open in a browser tab; nothing collects bars in the "
               "background. Bars are kept in memory by the server and are lost when it restarts. Yahoo's 5-minute "
               "bars are unofficial and may be delayed, so this is not a real-time exchange feed.")


def _signed(decimals: int, suffix: str = ""):
    """Signed number without a negative zero (a tiny fall shows as 0.00, not -0.00)."""
    def fmt(v: float) -> str:
        text = f"{v:+.{decimals}f}"
        return (text[1:] if float(text) == 0 else text) + suffix
    return fmt


TABLE_FORMATS = {"Last": "{:,.2f}".format, "Vs previous session": _signed(2, "%"), "5-min return %": _signed(2),
                 "z, time of day": _signed(1), "z vs NIFTY 50": _signed(1), "Volume vs usual": "{:.1f}×".format,
                 "z, volume": _signed(1), "Baseline sessions": "{:.0f}".format}
MISSING = "n/a"
COLUMN_HELP = {
    "Last": "₹ for stocks, index points for NIFTY 50",
    "Vs previous session": "Against the previous session's last 5-minute bar",
    "z, time of day": "The bar's return against the same bar of the day in earlier sessions (robust z)",
    "z vs NIFTY 50": "Return after removing beta times NIFTY 50's return, against the same bar of the day",
    "Volume vs usual": "Volume divided by the median volume of this bar of the day (Yahoo reports no index volume)",
    "z, volume": "Log volume against the same bar of the day in earlier sessions (robust z)",
    "Baseline sessions": f"Earlier sessions with this bar of the day (at least {MIN_SESSIONS} needed)",
}


def display_table(scan: IntradayScan) -> pd.DataFrame:
    """The table as shown: numbers formatted, and n/a where a value does not exist (never zero). Streamlit draws an
    empty number cell as "None", so the formatted text is what goes to the page."""
    table = _table(scan)
    for col, fmt in TABLE_FORMATS.items():
        table[col] = [MISSING if pd.isna(v) else fmt(v) for v in table[col]]
    return table


# Right-aligned text columns need Streamlit 1.6x; older supported versions show them left-aligned.
_ALIGN = "alignment" in inspect.signature(st.column_config.TextColumn).parameters


def _number_column(help_text: str | None):
    return st.column_config.TextColumn(help=help_text, **({"alignment": "right"} if _ALIGN else {}))


def _table_view(scan: IntradayScan) -> None:
    config = {col: _number_column(COLUMN_HELP.get(col)) for col in TABLE_FORMATS}
    st.dataframe(display_table(scan), hide_index=True, width="stretch", column_config=config)
