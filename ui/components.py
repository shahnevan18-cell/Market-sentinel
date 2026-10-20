"""Reusable interface pieces: formatting, page header, status pills, KPI strip and charts."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from config.market import (BAR_FINAL_AFTER, CURRENCY_SYMBOL, MARKET_TZ, TZ_LABEL, fmt_inr, fmt_inr_short,  # noqa: F401
                           fmt_market_clock, fmt_market_time, group_indian, holiday_name)
from providers.market_data import MarketDataset, parse_iso
from ui.theme import AMBER, CYAN, MUTED, PANEL_2, RED, RULE, SEVERITY_COLORS, SLATE, TEAL, TEXT

PLOT_CONFIG = {"displaylogo": False, "displayModeBar": False}


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def is_missing(x) -> bool:
    if x is None:
        return True
    try:
        return bool(pd.isna(x))
    except (TypeError, ValueError):
        return False


def fmt_pct(x, signed: bool = True, digits: int = 2) -> str:
    if is_missing(x):
        return "n/a"
    if abs(x) < 0.5 * 10 ** -(digits + 2):     # avoid printing "-0.00%"
        x = 0.0
    return f"{x:+.{digits}%}" if signed else f"{x:.{digits}%}"


def fmt_z(x) -> str:
    return "n/a" if is_missing(x) else f"{x:+.2f}"


def fmt_num(x, digits: int = 2) -> str:
    return "n/a" if is_missing(x) else f"{x:,.{digits}f}"


def fmt_big(x) -> str:
    """Large counts in Indian units: 3.68 crore, 12.5 lakh, 45,000."""
    if is_missing(x):
        return "n/a"
    if abs(x) >= 1e7:
        return f"{x / 1e7:.2f} crore"
    if abs(x) >= 1e5:
        return f"{x / 1e5:.2f} lakh"
    return f"{x:,.0f}"


def short_symbol(symbol: str | None) -> str:
    """RELIANCE.NS -> RELIANCE, SAFFRON.DEMO -> SAFFRON (indices keep their symbol)."""
    return re.sub(r"\.(NS|BO|DEMO)$", "", symbol or "")


def fmt_ago(iso_value: str | None) -> str:
    ts = parse_iso(iso_value)
    if ts is None:
        return "n/a"
    delta = datetime.now(timezone.utc) - ts
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} h ago"
    return f"{hours // 24} days ago"


def fmt_utc(iso_value: str | None) -> str:
    ts = parse_iso(iso_value)
    return "n/a" if ts is None else ts.strftime("%d %b %Y, %H:%M UTC")


def fmt_ist(iso_value) -> str:
    """'30 Sep 2026, 18:05 IST' for a stored UTC timestamp (stored values stay in UTC)."""
    return fmt_market_time(iso_value) if iso_value else "n/a"


def fmt_ist_clock(iso_value) -> str:
    """'18:05:12' in India time for a stored UTC timestamp (used in the live activity log and audit trail)."""
    return fmt_market_clock(iso_value)


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ---------------------------------------------------------------------------
# Layout pieces
# ---------------------------------------------------------------------------

def status_pills(ds: MarketDataset | None) -> str:
    if ds is None:
        return ""
    f = ds.freshness()
    pills = []
    if ds.is_demo:
        pills.append('<span class="ms-pill warn"><b>Demonstration data</b> (synthetic)</span>')
    else:
        cls = "bad" if not ds.frames else ("warn" if f["is_stale"] else "live")   # never a live colour without data
        pills.append(f'<span class="ms-pill {cls}">Source <b>Yahoo Finance via yfinance (NSE)</b></span>'
                     if "yfinance" in ds.provider_label else f'<span class="ms-pill {cls}">Source <b>{esc(ds.provider_label)}</b></span>')
    if f.get("latest_bar"):
        pills.append(f'<span class="ms-pill">Latest complete session <b>{esc(f["latest_bar"])}</b></span>')
    if f.get("partial_bar"):
        pills.append(f'<span class="ms-pill warn">Session in progress <b>{esc(f["partial_bar"])}</b></span>')
    if not ds.is_demo:
        pills.append(f'<span class="ms-pill">Retrieved <b>{esc(fmt_ago(f.get("newest_retrieval")))}</b></span>')
        counts = f.get("status_counts", {})
        if counts.get("cache-stale"):
            pills.append(f'<span class="ms-pill warn">Stale cache <b>{counts["cache-stale"]}</b></span>')
        if f.get("failed_symbols"):
            pills.append(f'<span class="ms-pill bad">Unavailable <b>{len(f["failed_symbols"])}</b></span>')
    if ds.as_of:
        pills.append(f'<span class="ms-pill warn">As of <b>{esc(ds.as_of)}</b></span>')
    return '<div class="ms-pills">' + "".join(pills) + "</div>"


def page_header(title: str, subtitle: str, ds: MarketDataset | None = None) -> None:
    st.html(f'<div class="ms-head"><div><h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>{status_pills(ds)}</div>')
    if ds is None:
        return
    f = ds.freshness()
    if ds.is_demo:
        banner("Demonstration mode. Every price, volume and announcement on this screen is synthetic and refers to "
               "fictional .DEMO securities. Nothing here is a real market observation.", "warn")
    else:
        if f.get("stale_symbols"):
            banner(f"Live fetch failed for {len(f['stale_symbols'])} symbol(s); their last cached copy is shown "
                   f"with its original retrieval time ({', '.join(f['stale_symbols'][:8])}).", "warn")
        if f.get("session_lag") is not None and f["session_lag"] >= 2:
            banner(f"The latest session in the data ({f['latest_bar']}) is {f['session_lag']} NSE trading sessions "
                   f"behind the expected session ({f['expected_session']}). The data may be stale.", "warn")
        if f.get("partial_dates"):
            banner(f"The bar for {', '.join(f['partial_dates'])} was retrieved before the NSE day was final. It is "
                   f"incomplete and excluded from anomaly detection, so the analysis runs to {f['latest_bar']}. "
                   f"Refresh market data after {bar_final_text(f['partial_dates'][-1])} to include it.", "info")
        today_holiday = holiday_name(datetime.now(timezone.utc).astimezone(MARKET_TZ))
        if today_holiday:
            banner(f"Today is an NSE trading holiday ({today_holiday}), so no new session is expected today.", "info")


def bar_final_text(session_date) -> str:
    """When the daily bar of a session becomes final: 16:15 IST on that day (shown in India time on any server)."""
    return f"{BAR_FINAL_AFTER:%H:%M} {TZ_LABEL} on {pd.Timestamp(session_date):%d %b %Y}"


def banner(text: str, tone: str = "warn") -> None:
    cls = {"warn": "", "bad": " bad", "info": " info"}.get(tone, "")
    st.html(f'<div class="ms-banner{cls}">{esc(text)}</div>')


def kpi_strip(items: list[dict]) -> None:
    cells = []
    for it in items:
        tone = it.get("tone")
        cls = f' class="v {tone}"' if tone else ' class="v"'
        sub = f'<div class="s">{esc(it.get("sub", ""))}</div>' if it.get("sub") else ""
        cells.append(f'<div class="ms-kpi"><div class="l">{esc(it["label"])}</div><div{cls}>{esc(it["value"])}</div>{sub}</div>')
    st.html('<div class="ms-kpis">' + "".join(cells) + "</div>")


def section(title: str, note: str | None = None) -> None:
    st.html(f'<div class="ms-section">{esc(title)}</div>' + (f'<div class="ms-note">{esc(note)}</div>' if note else ""))


def severity_html(sev: str) -> str:
    color = SEVERITY_COLORS.get(sev, SLATE)
    return f'<span class="ms-sev" style="color:{color}">{esc(sev)}</span>'


def tone_of(x) -> str | None:
    if is_missing(x) or x == 0:
        return None
    return "pos" if x > 0 else "neg"


def no_data_screen(ds: MarketDataset) -> None:
    reasons = list(ds.failures.items())[:6]
    detail = "; ".join(f"{s}: {e}" for s, e in reasons)
    banner("Live market data could not be loaded and no cached copy exists yet. "
           f"Provider messages: {detail or 'none returned'}.", "bad")
    st.markdown(
        "What you can do: check the internet connection and press **Refresh market data** in the sidebar, "
        "or switch the data source to **Demonstration data** to explore the full workflow with clearly labelled "
        "synthetic data. The app never substitutes synthetic prices for real ones on its own."
    )


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def sentinel_grid(scan, sessions: int = 30) -> go.Figure:
    cal = scan.panel.calendar[-sessions:]
    universe = scan.universe
    tickers, sectors, names = [], [], []
    for sector in universe.sectors:
        for sec in universe.securities:
            if sec.sector == sector and sec.ticker in scan.features:
                tickers.append(sec.ticker)
                sectors.append(sector)
                names.append(sec.name)
    if not tickers or len(cal) == 0:
        return go.Figure()
    z = np.array([[scan.features[t].loc[d, "z_ret"] if d in scan.features[t].index else np.nan for d in cal] for t in tickers])
    r = np.array([[scan.features[t].loc[d, "ret"] if d in scan.features[t].index else np.nan for d in cal] for t in tickers])
    custom = np.dstack([r, np.array([[n] * len(cal) for n in names], dtype=object),
                        np.array([[s] * len(cal) for s in sectors], dtype=object)])
    labels = [short_symbol(t) for t in tickers]
    x = [d.strftime("%d %b") for d in cal]
    fig = go.Figure(go.Heatmap(
        z=np.clip(z, -6, 6), x=x, y=labels, customdata=custom, zmin=-6, zmax=6, zmid=0, xgap=2, ygap=2,
        colorscale=[[0.0, RED], [0.35, "#5A2B35"], [0.5, PANEL_2], [0.65, "#1E5550"], [1.0, TEAL]],
        colorbar=dict(title=dict(text="Robust z of daily return", side="top"), orientation="h", thickness=8,
                      len=0.35, x=0, xanchor="left", y=-0.02, yanchor="top", tickvals=[-6, -3, 0, 3, 6],
                      tickfont=dict(size=10)),
        hovertemplate="<b>%{y}</b> %{customdata[1]}<br>%{customdata[2]}<br>%{x}<br>"
                      "Return %{customdata[0]:+.2%}<br>Robust z %{z:+.2f}<extra></extra>",
    ))
    ev = scan.events
    if not ev.empty:
        recent = ev[ev["date"].isin(cal) & ev["ticker"].isin(tickers)]
        if len(recent):
            fig.add_trace(go.Scatter(
                x=[d.strftime("%d %b") for d in recent["date"]], y=[short_symbol(t) for t in recent["ticker"]],
                mode="markers", marker=dict(symbol="square-open", size=13, color=AMBER, line=dict(width=1.6)),
                customdata=np.stack([recent["event_type"], recent["priority_score"], recent["severity"]], axis=1),
                hovertemplate="<b>Alert</b> %{y}, %{x}<br>%{customdata[0]}<br>Priority %{customdata[1]:.0f} "
                              "(%{customdata[2]})<extra></extra>", showlegend=False))
    prev = None
    for i, s in enumerate(sectors):
        if s != prev:
            fig.add_annotation(x=1.0, xref="paper", xanchor="left", y=labels[i], yref="y", text=f" {s}",
                               showarrow=False, font=dict(size=10, color=MUTED), yshift=0)
            if i > 0:
                fig.add_shape(type="line", xref="paper", x0=0, x1=1, yref="y", y0=i - 0.5, y1=i - 0.5,
                              line=dict(color=RULE, width=1))
            prev = s
    fig.update_layout(height=max(360, 21 * len(tickers) + 120), margin=dict(l=10, r=150, t=10, b=60),
                      yaxis=dict(autorange="reversed", showgrid=False, tickfont=dict(size=11)),
                      xaxis=dict(showgrid=False, tickfont=dict(size=10), side="top"))
    return fig


def movers_chart(scan, date) -> go.Figure:
    date = pd.Timestamp(date)
    rows = []
    for t, df in scan.features.items():
        if date in df.index and not pd.isna(df.loc[date, "ret"]):
            rows.append((short_symbol(t), df.loc[date, "ret"], df.loc[date, "z_ret"]))
    rows.sort(key=lambda r: r[1])
    fig = go.Figure(go.Bar(
        x=[r[1] for r in rows], y=[r[0] for r in rows], orientation="h",
        marker_color=[TEAL if r[1] > 0 else RED for r in rows],
        customdata=[[r[2]] for r in rows],
        text=[f"{r[1]:+.1%}" for r in rows], textposition="auto", insidetextanchor="end",
        textfont=dict(size=10), cliponaxis=False,
        hovertemplate="<b>%{y}</b><br>Return %{x:+.2%}<br>Robust z %{customdata[0]:+.2f}<extra></extra>"))
    fig.update_layout(height=max(300, 19 * len(rows) + 40), xaxis=dict(tickformat="+.0%", zeroline=True),
                      yaxis=dict(tickfont=dict(size=11), ticksuffix="  "), margin=dict(l=10, r=40, t=10, b=10))
    return fig


def sector_chart(scan) -> go.Figure:
    universe = scan.universe
    closes = scan.panel.closes
    labels, d1, d5, m1 = [], [], [], []
    syms = [(universe.benchmark, "benchmark")] + [(idx, sec) for sec, idx in universe.sector_indices.items()]
    syms += [(sym, "display only") for sym in universe.other_indices]
    for sym, label in syms:
        if sym not in closes:
            continue
        p = closes[sym].dropna()
        if len(p) < 22:
            continue
        labels.append(f"{universe.short_label(sym)}  ({label})")
        d1.append(p.iloc[-1] / p.iloc[-2] - 1)
        d5.append(p.iloc[-1] / p.iloc[-6] - 1)
        m1.append(p.iloc[-1] / p.iloc[-22] - 1)
    fig = go.Figure()
    for name, vals, color in (("1 day", d1, CYAN), ("5 days", d5, TEAL), ("21 days", m1, SLATE)):
        fig.add_trace(go.Bar(name=name, y=labels, x=vals, orientation="h", marker_color=color,
                             hovertemplate="%{y}<br>" + name + ": %{x:+.2%}<extra></extra>"))
    fig.update_layout(barmode="group", height=max(300, 34 * len(labels) + 60),
                      xaxis=dict(tickformat="+.0%"), yaxis=dict(autorange="reversed", tickfont=dict(size=11)),
                      legend=dict(orientation="h", y=1.0, yanchor="bottom", x=0), margin=dict(l=10, r=20, t=40, b=10))
    return fig


def event_chart(scan, ticker: str, date, before: int = 120, after: int = 0, title: str | None = None,
                price_label: str = f"Price ({CURRENCY_SYMBOL})") -> go.Figure:
    df = scan.features[ticker]
    date = pd.Timestamp(date)
    pos = df.index.get_loc(date)
    seg = df.iloc[max(0, pos - before): min(len(df), pos + after + 1)]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.68, 0.32], vertical_spacing=0.04)
    fig.add_trace(go.Scatter(x=seg.index, y=seg["close"], mode="lines", line=dict(color=CYAN, width=1.8),
                             name="Adjusted close", hovertemplate="%{x|%d %b %Y}<br>Adj. close " + CURRENCY_SYMBOL
                             + "%{y:,.2f}<extra></extra>"),
                  row=1, col=1)
    ev = scan.events
    if not ev.empty:
        mine = ev[(ev["ticker"] == ticker) & (ev["date"].isin(seg.index)) & (ev["date"] != date)]
        if len(mine):
            fig.add_trace(go.Scatter(x=mine["date"], y=seg.loc[mine["date"], "close"], mode="markers",
                                     marker=dict(size=8, color=AMBER, symbol="circle-open", line=dict(width=1.8)),
                                     name="Other alerts", customdata=mine[["event_type", "priority_score"]].values,
                                     hovertemplate="%{x|%d %b %Y}<br>%{customdata[0]}<br>Priority %{customdata[1]:.0f}<extra></extra>"),
                          row=1, col=1)
    color = TEAL if df.loc[date, "ret"] > 0 else RED
    fig.add_trace(go.Scatter(x=[date], y=[df.loc[date, "close"]], mode="markers", name="Selected event",
                             marker=dict(size=13, color=color, line=dict(color=TEXT, width=1.5)),
                             hovertemplate=f"Event %{{x|%d %b %Y}}<br>Return {df.loc[date, 'ret']:+.2%}<extra></extra>"),
                  row=1, col=1)
    vol_colors = [AMBER if d == date else "#2A3D5C" for d in seg.index]
    fig.add_trace(go.Bar(x=seg.index, y=seg["volume"], marker_color=vol_colors, name="Volume",
                         hovertemplate="%{x|%d %b %Y}<br>Volume %{y:,.0f}<extra></extra>"), row=2, col=1)
    fig.add_trace(go.Scatter(x=seg.index, y=seg["volume_median"], mode="lines", line=dict(color=TEAL, width=1.2, dash="dot"),
                             name="60-day median volume (prior days)",
                             hovertemplate="Median %{y:,.0f}<extra></extra>"), row=2, col=1)
    if after > 0:
        fig.add_vrect(x0=date, x1=seg.index[-1], fillcolor=AMBER, opacity=0.06, line_width=0, row="all", col=1)
        fig.add_annotation(x=seg.index[-1], y=1, yref="paper", xanchor="right", showarrow=False,
                           text="Observed after the alert", font=dict(size=10, color=AMBER))
    fig.add_vline(x=date, line=dict(color=MUTED, width=1, dash="dot"))
    fig.update_layout(height=450, showlegend=True,
                      legend=dict(orientation="h", y=-0.08, yanchor="top", x=0, font=dict(size=11)),
                      title=title, margin=dict(l=10, r=10, t=40 if title else 10, b=10), bargap=0.15)
    fig.update_yaxes(title_text=price_label, row=1, col=1, title_font=dict(size=11, color=MUTED))
    fig.update_yaxes(title_text="Volume (shares)", row=2, col=1, title_font=dict(size=11, color=MUTED))
    return fig


def zscore_chart(scan, ticker: str, date, before: int = 120) -> go.Figure:
    cfg = scan.config
    df = scan.features[ticker]
    date = pd.Timestamp(date)
    pos = df.index.get_loc(date)
    seg = df.iloc[max(0, pos - before): pos + 1]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=seg.index, y=seg["z_ret"], name="Return z", line=dict(color=CYAN, width=1.5)))
    fig.add_trace(go.Scatter(x=seg.index, y=seg["z_abn"], name="Market-adjusted z", line=dict(color=TEAL, width=1.3)))
    fig.add_trace(go.Scatter(x=seg.index, y=seg["z_volume"], name="Volume z", line=dict(color=AMBER, width=1.2, dash="dot")))
    for level in (cfg.z_price, -cfg.z_price):
        fig.add_hline(y=level, line=dict(color=RED, width=1, dash="dash"), opacity=0.6)
    fig.add_vline(x=date, line=dict(color=MUTED, width=1, dash="dot"))
    fig.update_layout(height=260, legend=dict(orientation="h", y=1.02, yanchor="bottom", x=0, font=dict(size=11)),
                      yaxis=dict(title="z", title_font=dict(size=11, color=MUTED)), margin=dict(l=10, r=10, t=30, b=10),
                      hovermode="x unified")
    return fig


def comparison_chart(event: dict, evidence: dict, benchmark: str) -> go.Figure:
    """`benchmark` is the benchmark's display name (NIFTY 50 in live mode)."""
    bm = evidence.get("compare_with_benchmark") or {}
    pc = evidence.get("compare_with_peers") or {}
    rows = [(f"{short_symbol(event.get('ticker', ''))} (event)", event.get("ret"), "stock")]
    if bm.get("expected_return") is not None:
        rows.append(("Expected from market model", bm.get("expected_return"), "model"))
    if bm.get("benchmark_return") is not None:
        rows.append((f"{bm.get('benchmark_name') or benchmark} (benchmark)", bm.get("benchmark_return"), "ref"))
    if pc.get("sector_index_return") is not None:
        name = pc.get("sector_index_name") or short_symbol(pc.get("sector_index"))
        rows.append((f"{name} (sector index)", pc.get("sector_index_return"), "ref"))
    if pc.get("peer_median_return") is not None:
        rows.append(("Peer median", pc.get("peer_median_return"), "ref"))
    for p in pc.get("peers", []) or []:
        if p.get("return") is not None:
            rows.append((f"Peer {short_symbol(p['ticker'])}", p["return"], "peer"))
    colors = []
    for label, val, kind in rows:
        if kind == "stock":
            colors.append(TEAL if (val or 0) > 0 else RED)
        elif kind == "model":
            colors.append(MUTED)
        elif kind == "ref":
            colors.append(CYAN)
        else:
            colors.append("#3B5275")
    fig = go.Figure(go.Bar(x=[r[1] for r in rows], y=[r[0] for r in rows], orientation="h", marker_color=colors,
                           text=[f"{r[1]:+.2%}" for r in rows], textposition="auto", insidetextanchor="end",
                           textfont=dict(size=10), cliponaxis=False,
                           hovertemplate="%{y}: %{x:+.2%}<extra></extra>"))
    fig.update_layout(height=max(220, 30 * len(rows) + 40), xaxis=dict(tickformat="+.0%"),
                      yaxis=dict(autorange="reversed", ticksuffix="  "), margin=dict(l=10, r=50, t=10, b=10))
    return fig


def hypothesis_chart(rubric: dict) -> go.Figure:
    results = rubric.get("results", [])
    leading = rubric.get("leading")
    ys = [f"{r['id']}  {r['label']}" for r in results]
    colors = [(AMBER if leading == "H5" else TEAL) if r["id"] == leading else "#3B5275" for r in results]
    fig = go.Figure(go.Bar(x=[r["score"] for r in results], y=ys, orientation="h", marker_color=colors,
                           text=[f"{r['score']:.0f}" for r in results], textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}<br>Evidence score %{x:.0f} of 100<extra></extra>"))
    fig.add_vline(x=45, line=dict(color=MUTED, dash="dot", width=1))
    fig.add_annotation(x=45, y=1.08, yref="paper", text="Evidence threshold", showarrow=False,
                       font=dict(size=10, color=MUTED))
    fig.update_layout(height=250, xaxis=dict(range=[0, 108], title="Evidence score (0-100)"),
                      yaxis=dict(autorange="reversed", tickfont=dict(size=11)), margin=dict(l=10, r=30, t=26, b=10))
    return fig


def car_chart(car_paths: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for group, color in (("Up events", TEAL), ("Down events", RED)):
        g = car_paths[car_paths["group"] == group]
        if g.empty:
            continue
        n = int(g["n_events"].iloc[0]) if "n_events" in g else 0
        fig.add_trace(go.Scatter(x=g["rel_day"], y=g["car"], mode="lines+markers", name=f"{group} (n={n})",
                                 line=dict(color=color, width=2), marker=dict(size=4),
                                 hovertemplate="Day %{x}<br>Average CAR %{y:+.2%}<extra></extra>"))
    fig.add_vrect(x0=0.5, x1=20.5, fillcolor=AMBER, opacity=0.05, line_width=0)
    fig.add_annotation(x=20, y=1.02, yref="paper", xanchor="right", showarrow=False,
                       text="Observed after the alert (not available at detection)", font=dict(size=10, color=AMBER))
    fig.add_vline(x=0, line=dict(color=MUTED, dash="dot", width=1))
    fig.add_hline(y=0, line=dict(color=RULE, width=1))
    fig.update_layout(height=360, xaxis=dict(title="Trading days relative to the alert (day 0)", dtick=5),
                      yaxis=dict(title="Average cumulative abnormal return", tickformat="+.1%"),
                      legend=dict(orientation="h", y=1.12, x=0), margin=dict(l=10, r=10, t=40, b=10))
    return fig


def outcome_scatter(events: pd.DataFrame, horizon: int = 5) -> go.Figure:
    col = f"after_car_{horizon}d"
    d = events.dropna(subset=["z_abn", col])
    fig = go.Figure()
    for sev in ("Critical", "High", "Moderate", "Low"):
        g = d[d["severity"] == sev]
        if g.empty:
            continue
        fig.add_trace(go.Scatter(x=g["z_abn"], y=g[col], mode="markers", name=sev,
                                 marker=dict(color=SEVERITY_COLORS[sev], size=8, opacity=0.85,
                                             line=dict(color="#0B1628", width=0.5)),
                                 customdata=g[["event_id", "event_type"]].values,
                                 hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>Event-day abnormal z %{x:+.2f}"
                                               f"<br>CAR next {horizon} days %{{y:+.2%}}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color=RULE, width=1))
    fig.add_vline(x=0, line=dict(color=RULE, width=1))
    fig.update_layout(height=360, xaxis=dict(title="Event-day market-adjusted z (known at detection)"),
                      yaxis=dict(title=f"Abnormal return over next {horizon} days (observed later)", tickformat="+.0%"),
                      legend=dict(orientation="h", y=1.1, x=0), margin=dict(l=10, r=10, t=36, b=10))
    return fig
