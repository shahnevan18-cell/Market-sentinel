"""Risk scenario lab: transparent what-if calculations on an illustrative portfolio."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from analytics import risk_metrics as rm
from analytics.anomaly_detection import threshold_sensitivity
from ui import components as c
from ui.state import app_data
from ui.theme import AMBER, CYAN, RED, TEAL

LAKH = 1e5   # charts show rupee amounts in lakh (1 lakh = ₹1,00,000) so the axis labels stay short


def _box(kind: str, title: str, body: str, formula: str | None = None) -> None:
    f = f'<div class="ms-formula">{c.esc(formula)}</div>' if formula else ""
    st.html(f'<div class="ms-box {kind}"><div class="t">{c.esc(title)}</div><div class="b">{body}</div>{f}</div>')


def render() -> None:
    ds, mon = app_data()
    c.page_header("Risk scenario lab",
                  "Try hypothetical shocks on an illustrative portfolio. Observed inputs come from market data; "
                  "everything you type in is an assumption. Nothing here is a trade or a forecast.", ds)
    if mon is None:
        c.no_data_screen(ds)
        return
    scan = mon.scan
    universe = scan.universe
    as_of = scan.last_date
    sectors = {s.ticker: s.sector for s in universe.securities}
    bench_name = universe.short_label(universe.benchmark)
    st.html('<div class="ms-note">Colour key: <span style="color:#2BB3A3">teal</span> boxes hold observed inputs, '
            '<span style="color:#E9A23B">amber</span> boxes hold your assumptions and '
            '<span style="color:#45C4E0">cyan</span> boxes hold hypothetical results.</div>')

    c.section("Illustrative portfolio", "Edit the weights (in %) and the value in rupees. Weights are rescaled to "
              "sum to 100%. The portfolio is hypothetical: it is not a recommendation or anyone's real holding.")
    key = f"portfolio_{universe.key}"
    if key not in st.session_state:
        st.session_state[key] = pd.DataFrame([{"Ticker": t, "Company": universe.display_name(t),
                                               "Sector": sectors.get(t, ""), "Weight %": w * 100}
                                              for t, w in universe.portfolio.items()])
    edited = st.data_editor(st.session_state[key], hide_index=True, width="stretch", num_rows="dynamic",
                            column_config={
                                "Ticker": st.column_config.SelectboxColumn(options=universe.tickers, required=True),
                                "Company": st.column_config.TextColumn(disabled=True),
                                "Sector": st.column_config.TextColumn(disabled=True),
                                "Weight %": st.column_config.NumberColumn(min_value=0.0, max_value=100.0, step=0.5,
                                                                          format="%.1f")},
                            key=f"editor_{universe.key}")
    edited = edited.dropna(subset=["Ticker"])
    weights = {}
    for _, r in edited.iterrows():
        if r["Ticker"] in universe.tickers and pd.notna(r["Weight %"]) and r["Weight %"] > 0:
            weights[r["Ticker"]] = weights.get(r["Ticker"], 0.0) + float(r["Weight %"]) / 100.0
    total = sum(weights.values())
    weights = rm.normalise_weights(weights)
    value = st.number_input("Illustrative portfolio value (₹, hypothetical)", min_value=1_00_000.0,
                            value=float(universe.portfolio_value), step=10_00_000.0, format="%.0f",
                            help="In rupees. The default is ₹1 crore (1,00,00,000).")
    st.caption(f"Portfolio value {c.fmt_inr(value)} ({c.fmt_inr_short(value)}), illustrative. Rupee amounts below "
               "use Indian digit grouping; charts show them in lakh.")
    if not weights:
        st.warning("Add at least one holding with a positive weight.")
        return
    if abs(total - 1.0) > 0.001:
        st.caption(f"Entered weights sum to {total:.1%}; they are rescaled to 100% for every calculation below.")

    betas, vols = {}, {}
    for t in weights:
        f = scan.features.get(t)
        if f is not None and as_of in f.index:
            betas[t] = None if pd.isna(f.loc[as_of, "beta"]) else float(f.loc[as_of, "beta"])
            vols[t] = None if pd.isna(f.loc[as_of, "vol_long_ann"]) else float(f.loc[as_of, "vol_long_ann"])
    obs = pd.DataFrame([{"Ticker": t, "Weight %": w * 100, "Beta (120 sessions)": betas.get(t),
                         "Volatility, annualised (60 sessions)": vols.get(t)} for t, w in weights.items()])
    with st.expander(f"Observed inputs as of {as_of:%d %b %Y}", expanded=False):
        st.dataframe(obs, hide_index=True, width="stretch", column_config={
            "Weight %": st.column_config.NumberColumn(format="%.1f"),
            "Beta (120 sessions)": st.column_config.NumberColumn(format="%.2f"),
            "Volatility, annualised (60 sessions)": st.column_config.NumberColumn(format="%.3f")})

    tabs = st.tabs(["Single holding shock", "Market shock", "Concentration", "Volatility rise", "Alert threshold"])

    with tabs[0]:
        a, b = st.columns([1, 2], gap="large")
        with a:
            tick = st.selectbox("Holding", list(weights), key="shock_tick")
            shock = st.select_slider("Shock to that holding", options=[-0.30, -0.20, -0.15, -0.10, -0.05, 0.05, 0.10, 0.15],
                                     value=-0.10, format_func=lambda x: f"{x:+.0%}")
            _box("assumed", "Assumption", f"{c.esc(tick)} moves {shock:+.0%}; all other holdings unchanged.")
        res = rm.stress_single_holding(weights, value, tick, shock)
        with b:
            _box("observed", "Observed input", f"Weight of {c.esc(tick)}: {res.outputs['weight']:.1%}")
            _box("result", "Hypothetical result",
                 f"Portfolio return {res.outputs['portfolio_return']:+.2%}, change in value "
                 f"{c.esc(c.fmt_inr(res.outputs['pnl'], signed=True))}, new value "
                 f"{c.esc(c.fmt_inr(res.outputs['new_value']))}.", res.formula)
            grid = [-0.15, -0.10, -0.05]
            fig = go.Figure(go.Bar(x=[f"{g:+.0%}" for g in grid],
                                   y=[rm.stress_single_holding(weights, value, tick, g).outputs["pnl"] / LAKH for g in grid],
                                   marker_color=RED, hovertemplate="Shock %{x}<br>Change ₹%{y:,.2f} lakh<extra></extra>"))
            fig.update_layout(height=230, xaxis=dict(type="category", title="Shock to the holding"),
                              yaxis=dict(title="Change in value (₹ lakh)"), margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", config=c.PLOT_CONFIG)

    with tabs[1]:
        a, b = st.columns([1, 2], gap="large")
        with a:
            mshock = st.slider(f"{bench_name} shock (%)", -20.0, 10.0, -5.0, 0.5) / 100
            _box("assumed", "Assumptions", f"{c.esc(bench_name)} moves {mshock:+.1%}. Each holding moves beta x shock "
                                          "(linear one-factor model, no idiosyncratic moves). Missing beta treated as 1.0.")
        res = rm.stress_market(weights, betas, value, mshock, beta_as_of=f"{as_of:%Y-%m-%d}")
        with b:
            _box("result", "Hypothetical result",
                 f"Portfolio return {res.outputs['portfolio_return']:+.2%}, change in value "
                 f"{c.esc(c.fmt_inr(res.outputs['pnl'], signed=True))}.",
                 res.formula)
            t = res.table
            fig = go.Figure(go.Bar(x=t["pnl"] / LAKH, y=[c.short_symbol(x) for x in t["ticker"]], orientation="h",
                                   marker_color=[RED if v < 0 else TEAL for v in t["pnl"]],
                                   customdata=t[["beta_used", "assumed_move"]].values,
                                   hovertemplate="%{y}<br>Beta %{customdata[0]:.2f}<br>Assumed move %{customdata[1]:+.2%}"
                                                 "<br>Change ₹%{x:,.2f} lakh<extra></extra>"))
            fig.update_layout(height=max(220, 24 * len(t) + 40), xaxis=dict(title="Change in value (₹ lakh)"),
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", config=c.PLOT_CONFIG)

    with tabs[2]:
        a, b = st.columns([1, 2], gap="large")
        base = rm.concentration_summary(weights, sectors)
        with a:
            tick2 = st.selectbox("Position to grow", list(weights), key="conc_tick")
            new_w = st.slider("New weight for that position (%)", 0.0, 80.0, round(weights[tick2] * 100, 1), 0.5) / 100
            _box("assumed", "Assumption", f"{c.esc(tick2)} becomes {new_w:.1%} of the portfolio; other holdings are "
                                          "scaled down in proportion.")
        neww = rm.reweight(weights, tick2, new_w)
        after = rm.concentration_summary(neww, sectors)
        with b:
            _box("observed", "Current portfolio",
                 f"HHI {base['hhi']:.3f}, effective number of holdings {base['effective_n']:.1f}, largest position "
                 f"{c.esc(base['top_ticker'])} at {base['top_weight']:.1%}.",
                 "HHI = sum of squared weights; effective number of holdings = 1 / HHI")
            _box("result", "After the change (hypothetical)",
                 f"HHI {after['hhi']:.3f}, effective number of holdings {after['effective_n']:.1f}, largest position "
                 f"{c.esc(after['top_ticker'])} at {after['top_weight']:.1%}.")
            sw0, sw1 = base["sector_weights"], after["sector_weights"]
            secs = list(dict.fromkeys(list(sw0) + list(sw1)))
            fig = go.Figure()
            fig.add_trace(go.Bar(name="Current", x=secs, y=[sw0.get(s, 0) for s in secs], marker_color=CYAN))
            fig.add_trace(go.Bar(name="After change", x=secs, y=[sw1.get(s, 0) for s in secs], marker_color=AMBER))
            fig.update_layout(barmode="group", height=260, yaxis=dict(tickformat=".0%", title="Sector weight"),
                              legend=dict(orientation="h", y=1.12, x=0), margin=dict(l=10, r=10, t=30, b=10))
            st.plotly_chart(fig, width="stretch", config=c.PLOT_CONFIG)

    with tabs[3]:
        a, b = st.columns([1, 2], gap="large")
        pr = rm.portfolio_returns(scan, weights, end=as_of, window=scan.config.var_window)
        with a:
            k = st.slider("Volatility multiplier", 1.0, 3.0, 1.5, 0.1)
            conf = st.select_slider("Confidence level", options=[0.90, 0.95, 0.99], value=0.95,
                                    format_func=lambda x: f"{x:.0%}")
            _box("assumed", "Assumptions", f"Every daily return is scaled by {k:.1f}. The shape of the distribution is "
                                          "unchanged and weights are held fixed.")
        res = rm.volatility_scenario(pr, k, value, conf, as_of=f"{as_of:%Y-%m-%d}")
        with b:
            o, ob = res.outputs, res.observed_inputs
            _box("observed", f"Observed, {ob['observations']} sessions to {as_of:%d %b %Y}",
                 f"Daily volatility {c.fmt_pct(ob['observed_daily_sigma'], False)}; one-day historical VaR "
                 f"{c.fmt_pct(ob['observed_hist_var_1d'], False)}; parametric VaR {c.fmt_pct(ob['observed_param_var_1d'], False)}.")
            _box("result", "Hypothetical result",
                 f"One-day {conf:.0%} historical VaR {c.fmt_pct(o['hist_var_1d'], False)} "
                 f"({c.esc(c.fmt_inr(o['hist_var_1d_value']))}); parametric VaR {c.fmt_pct(o['param_var_1d'], False)} "
                 f"({c.esc(c.fmt_inr(o['param_var_1d_value']))}). Lookback {ob['observations']} sessions to "
                 f"{as_of:%d %b %Y}.",
                 res.formula + ". Historical VaR is the loss exceeded on (1 - confidence) of past days; "
                               "parametric VaR assumes normal returns.")
            ks = np.round(np.arange(1.0, 3.01, 0.25), 2)
            hv = [rm.volatility_scenario(pr, kk, value, conf).outputs["hist_var_1d_value"] for kk in ks]
            hv = [None if v is None else v / LAKH for v in hv]
            fig = go.Figure(go.Scatter(x=ks, y=hv, mode="lines+markers", line=dict(color=CYAN),
                                       hovertemplate="Multiplier %{x}<br>VaR ₹%{y:,.2f} lakh<extra></extra>"))
            fig.update_layout(height=230, xaxis=dict(title="Volatility multiplier"),
                              yaxis=dict(title=f"One-day {conf:.0%} VaR (₹ lakh)"),
                              margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig, width="stretch", config=c.PLOT_CONFIG)

    with tabs[4]:
        st.markdown("How many stock-days would raise an alert if the same threshold applied to all three tests "
                    "(price, market-relative and volume)? This uses the observed features of the whole dataset.")
        thresholds = [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
        sens = threshold_sensitivity(scan, thresholds)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=sens["threshold"], y=sens["alerts_any_test"], mode="lines+markers", name="Any test",
                                 line=dict(color=TEAL)))
        fig.add_trace(go.Scatter(x=sens["threshold"], y=sens["alerts_price_test_only"], mode="lines+markers",
                                 name="Price test only", line=dict(color=AMBER)))
        fig.update_layout(height=300, xaxis=dict(title="Threshold (|z| at least)"), yaxis=dict(title="Alert count"),
                          legend=dict(orientation="h", y=1.12, x=0), margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, width="stretch", config=c.PLOT_CONFIG)
        n_days = sum(int(df["ret"].notna().sum()) for df in scan.features.values())
        st.caption(f"Out of {n_days:,} stock-days with a return. Under a normal distribution, |z| of at least 3 would "
                   "occur on about 0.27% of days; real returns have fatter tails, so the observed share is higher.")
