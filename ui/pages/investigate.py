"""Investigation workspace: run the three-role workflow on one alert and read the report."""
from __future__ import annotations

import json
import time

import pandas as pd
import streamlit as st

from agents.orchestrator import STAGES, InvestigationError, list_records, load_record, run_investigation, stage_progress
from agents.sentinel_monitor import recent_priority_alert
from agents.trace import decision_trace, engine_facts
from config.market import DISCLOSURE_TERMS_NOTE
from reports.report_builder import build_html, build_markdown
from ui import components as c
from ui.state import app_data, get_backend, get_settings
from ui.theme import RELEVANCE_COLORS

STAGE_HINTS = {
    "Event validation": "Event found, re-detected on data up to the event date, data quality checked",
    "Price and volume analysis": "Returns, robust z-scores, volatility and abnormal volume",
    "Benchmark and peer comparison": "Market model against the benchmark, sector index, peers and market breadth",
    "Public news retrieval": "Indian news headlines around the event; official NSE/BSE pages linked for manual checks",
    "Hypothesis evaluation": "Five explanations scored with the transparent rubric",
    "Risk interpretation": "VaR, volatility regime, exposure and stress tests",
    "Final report": "Report assembled with the full audit trail",
}


def _stages_html(statuses: dict) -> str:
    items = []
    for s in STAGES:
        stt = statuses.get(s, "pending")
        cls = {"done": "done", "running": "running", "warning": "warning", "error": "error"}.get(stt, "")
        label = {"done": "completed", "running": "in progress", "warning": "completed with warnings",
                 "error": "failed", "pending": "not started"}.get(stt, stt)
        items.append(f'<li><span class="ms-dot {cls}"></span><div><div class="ms-stage-name">{c.esc(s)}</div>'
                     f'<div class="ms-stage-sub">{c.esc(STAGE_HINTS[s])}. Status: {label}.</div></div></li>')
    return '<ul class="ms-stages">' + "".join(items) + "</ul>"


def _log_line(e) -> str:
    get = (lambda k: e.get(k)) if isinstance(e, dict) else (lambda k: getattr(e, k))
    status = get("status")
    tag = {"ok": ('ok', 'done'), "error": ('err', 'failed'), "warning": ('warn', 'warning'),
           "skipped": ('warn', 'skipped')}.get(status, ('who', 'note'))
    kind = get("kind")
    name = get("name")
    what = f"called <b>{c.esc(name)}</b>" if kind == "tool_call" else f"<b>{c.esc(name)}</b>"
    t = c.fmt_ist_clock(get("timestamp"))
    return (f'<span class="who">{t} {c.esc(get("actor"))}</span> <span class="{tag[0]}">{tag[1]}</span> '
            f'{what}: {c.esc(str(get("summary"))[:230])}')


def _event_label(row) -> str:
    return (f"{c.short_symbol(row['ticker'])}  {row['name']}   {row['date']:%d %b %Y}   {row['event_type']}   "
            f"(priority {row['priority_score']:.0f}, {row['severity'].lower()})")


def _engine_strip(rec: dict) -> str:
    f = engine_facts(rec)
    if f["any_llm"]:
        by = f["tool_calls_by_actor"]
        model_calls = by.get("Market Investigator", 0) + by.get("Risk Strategist", 0)
        parts = [f"<b>LLM-directed</b> ({c.esc(rec.get('engine', {}).get('requested'))})",
                 f"model turns: investigator {f['investigator_model_turns']}, strategist {f['strategist_model_turns']}",
                 f"tool calls chosen by the model: {model_calls}",
                 f"required checks the orchestrator had to run: {f['tool_calls_enforced_by_orchestrator']}"]
        if f["tokens"]:
            parts.append(f"tokens {f['tokens']:,}")
        cls = "live" if not f["llm_errors"] else "warn"
    else:
        fallback = bool(f["llm_errors"])
        parts = ["<b>Rule-based protocol</b>" + (" after an LLM failure" if fallback else " (no LLM in use)"),
                 "fixed tool order, narrative from templates, same tools and rubric"]
        cls = "warn" if fallback else ""
    return '<div class="ms-pills left">' + "".join(f'<span class="ms-pill {cls}">{p}</span>' for p in parts) + "</div>"


def render() -> None:
    ds, mon = app_data()
    c.page_header("Investigation workspace",
                  "Run the monitor, investigator and strategist on one alert, watch each real step, and read the "
                  "evidence-backed report.", ds)
    if mon is None:
        c.no_data_screen(ds)
        return
    events = mon.events
    if events.empty:
        st.info("No alerts to investigate at the current thresholds.")
        return

    ordered = events.sort_values(["date", "priority_score"], ascending=[False, False]).reset_index(drop=True)
    ids = list(ordered["event_id"])
    wanted = st.session_state.get("selected_event")
    if wanted and wanted not in ids:
        c.banner(f"The alert {wanted} is not detected with the current thresholds, so it cannot be investigated here.",
                 "warn")
    # Nothing chosen yet: start on the most recent high-priority alert, so a demonstration can begin at once.
    preselected = None if wanted in ids else recent_priority_alert(ordered, mon.scan.panel.calendar)
    index = ids.index(wanted) if wanted in ids else (ids.index(preselected) if preselected else 0)
    label_map = {r["event_id"]: _event_label(r) for _, r in ordered.iterrows()}

    top_l, top_r = st.columns([3, 2], vertical_alignment="bottom")
    with top_l:
        event_id = st.selectbox("Alert", ids, index=index, format_func=lambda e: label_map.get(e, e))
    with top_r:
        hist_default = 1 if st.session_state.get("selected_event_historical") else 0
        kind = st.radio("Investigation type", ["Live investigation", "As of the event date"], index=hist_default,
                        horizontal=True, help="As-of mode uses only prices up to the event date and excludes news "
                                              "published after that day's close.")
    historical = kind == "As of the event date"
    if preselected and event_id == preselected:
        st.caption("Preselected: the most recent high-priority alert of the last 10 sessions. Choose any other "
                   "alert above.")
    st.session_state.selected_event = event_id
    st.session_state.selected_event_historical = historical

    backend = get_backend()
    settings = get_settings()
    if backend:
        st.caption(f"Reasoning engine: {backend.label}. The model chooses tools and judges headline relevance; "
                   "every number comes from Python tools.")
    else:
        st.caption("Reasoning engine: rule-based protocol (no LLM in use). The same tools run in a fixed order and "
                   "the narrative is written from templates. It is not presented as AI reasoning.")

    b1, b2 = st.columns([1, 3], vertical_alignment="center")
    with b1:
        run = st.button("Run investigation", type="primary")
    with b2:
        pacing = st.toggle("Presentation pacing", value=False,
                           help="Adds a short pause after each completed step so an audience can follow the live "
                                "activity. The steps and results are identical.")
    if run:
        col_a, col_b = st.columns([2, 3], gap="large")
        with col_a:
            c.section("Workflow")
            stage_ph = st.empty()
        with col_b:
            c.section("Live activity", "Each line is a step that has actually completed.")
            log_ph = st.empty()
        entries, lines = [], []
        stage_ph.html(_stages_html({}))

        def on_entry(entry):
            if pacing:
                time.sleep(0.35)
            entries.append(entry)
            stage_ph.html(_stages_html(stage_progress(entries)))
            lines.append(_log_line(entry))
            log_ph.html('<div class="ms-log">' + "<br>".join(lines[-28:]) + "</div>")

        try:
            record = run_investigation(event_id, ds, settings, backend=backend, scan=mon.scan, historical=historical,
                                       progress=on_entry)
            st.session_state.current_record = record.as_dict()
            st.toast("Investigation completed and saved to history." if record.saved_to else
                     "Investigation completed, but it could not be saved to history (see the warning below).")
        except InvestigationError as exc:
            c.banner(str(exc), "bad")
        except Exception as exc:  # noqa: BLE001 - shown honestly instead of a fake result
            c.banner(f"The investigation stopped with an error: {type(exc).__name__}: {exc}", "bad")

    rec = st.session_state.get("current_record")
    if rec:
        render_record(rec, mon)

    with st.expander("Investigation history"):
        rows = list_records()
        if not rows:
            st.caption("No saved investigations yet. Each completed run is saved under data/investigations.")
        else:
            hist = pd.DataFrame(rows)
            st.dataframe(hist[["created_at", "event_id", "leading", "confidence", "engine", "data_mode", "historical"]],
                         hide_index=True, width="stretch")
            pick = st.selectbox("Open a saved report", [r["path"] for r in rows],
                                format_func=lambda p: next((f"{r['event_id']}  ({r['created_at']})" for r in rows
                                                            if r["path"] == p), p))
            if st.button("Open saved report"):
                st.session_state.current_record = load_record(pick)
                st.rerun()


def render_record(rec: dict, mon) -> None:
    ev = rec.get("event", {})
    rub = rec.get("rubric", {})
    eng = rec.get("engine", {})
    inv = rec.get("investigator", {})
    strat = rec.get("strategist", {})
    evid = rec.get("evidence", {})
    st.divider()
    st.html(
        '<div class="ms-verdict">'
        f'<div class="k">{c.esc(ev.get("name"))} ({c.esc(c.short_symbol(ev.get("ticker")))}), {c.esc(str(ev.get("date"))[:10])}. '
        f'Leading assessment, {c.esc(str(rub.get("confidence")).lower())} confidence</div>'
        f'<div class="h">{c.esc(rub.get("leading_label"))}</div>'
        f'<div class="c">{c.esc(rub.get("conclusion"))}</div></div>'
    )
    data = rec.get("data", {})
    meta = (f"Engine: investigator {eng.get('investigator')}, strategist {eng.get('strategist')}. "
            f"Data: {data.get('mode')} mode, {data.get('market') or 'market n/a'}, benchmark "
            f"{data.get('benchmark_name') or data.get('benchmark') or 'n/a'}, currency "
            f"{data.get('symbol_currency') or data.get('currency') or 'n/a'}, prices up to {data.get('prices_used_up_to')}. "
            f"{'As-of investigation: news after the event-day close excluded. ' if rec.get('historical') else ''}"
            f"Run time {rec.get('duration_s')} s.")
    st.caption(meta)
    st.html(_engine_strip(rec))
    for err in eng.get("llm_errors") or []:
        c.banner(err, "bad")
    other = [w for w in rec.get("warnings", []) if w not in (eng.get("llm_errors") or [])]
    for w in other:
        if not w.startswith("Demonstration mode"):
            c.banner(w, "info")

    tabs = st.tabs(["Summary", "Evidence", "Hypotheses", "Risk", "Audit trail", "Export"])
    with tabs[0]:
        left, right = st.columns([3, 2], gap="large")
        with left:
            c.section("Executive summary")
            st.write(strat.get("executive_summary") or "n/a")
            c.section("Investigator findings")
            st.write(inv.get("summary") or "n/a")
            for f in inv.get("key_findings") or []:
                st.markdown(f"- {f}")
        with right:
            c.section("What remains unknown")
            for u in inv.get("unknowns") or []:
                st.markdown(f"- {u}")
            c.section("Recommended follow-up checks")
            for f in (inv.get("follow_up_checks") or []) + (strat.get("next_steps") or []):
                st.markdown(f"- {f}")
        uv = rec.get("unverified_figures") or {}
        if uv:
            figs = sorted({x for who in uv.values() for v in who.values() for x in v})
            c.banner("Figures written by the LLM that matched no tool output (treat as unverified): " + ", ".join(figs), "warn")

    with tabs[1]:
        scan = mon.scan
        same_data = ev.get("ticker") in scan.features and pd.Timestamp(ev.get("date")) in scan.features[ev["ticker"]].index
        left, right = st.columns([3, 2], gap="large")
        with left:
            if same_data:
                st.plotly_chart(c.event_chart(scan, ev["ticker"], ev["date"], before=120,
                                              title="Price and volume up to the event date",
                                              price_label="Price (synthetic ₹)" if rec.get("data", {}).get("mode") == "demo"
                                              else "Price (₹)"),
                                width="stretch", config=c.PLOT_CONFIG)
            else:
                st.caption("The price chart is unavailable because the current data source differs from the one used.")
        with right:
            c.section("Event-day returns compared")
            st.plotly_chart(c.comparison_chart(ev, evid, rec.get("data", {}).get("benchmark_name") or "Benchmark"),
                            width="stretch", config=c.PLOT_CONFIG)
        rv = evid.get("calculate_returns_and_volatility") or {}
        vol = evid.get("calculate_abnormal_volume") or {}
        bm = evid.get("compare_with_benchmark") or {}
        pc = evid.get("compare_with_peers") or {}
        measures = pd.DataFrame([
            ("Simple return", c.fmt_pct(rv.get("simple_return")), "Adjusted close, event day"),
            ("Robust z of return", c.fmt_z(rv.get("robust_z_return")),
             f"Median and MAD of the previous {rec.get('config', {}).get('lookback')} sessions"),
            ("Volume / median", f"{c.fmt_num(vol.get('volume_ratio'), 2)}x", f"Median {c.fmt_big(vol.get('baseline_median_volume'))} shares"),
            ("Robust z of log volume", c.fmt_z(vol.get("robust_z_log_volume")), "Threshold " + str(vol.get("threshold"))),
            ("Beta and R-squared", f"{c.fmt_num(bm.get('beta'))} and {c.fmt_num(bm.get('r_squared'))}",
             f"{bm.get('estimation_window_start')} to {bm.get('estimation_window_end')}"),
            ("Abnormal return (z)", f"{c.fmt_pct(bm.get('abnormal_return'))} ({c.fmt_z(bm.get('abnormal_z'))})",
             "Return minus alpha + beta x benchmark"),
            ("Return vs peer median (z)", f"{c.fmt_pct(pc.get('relative_return'))} ({c.fmt_z(pc.get('relative_z'))})",
             f"{pc.get('n_peers')} peers, {pc.get('peers_source')}" if pc.get("n_peers") else "No peers in this group"),
            ("Sector index return (z)",
             f"{c.fmt_pct(pc.get('sector_index_return'))} ({c.fmt_z(pc.get('sector_index_z'))})"
             if pc.get("sector_index_name") else "n/a",
             pc.get("sector_index_name") or "No sector index configured for this group"),
            ("Recent vs earlier volatility", f"{c.fmt_pct(rv.get('vol_recent_10d_annualised'), False)} vs "
             f"{c.fmt_pct(rv.get('vol_prior_60d_annualised'), False)}", "Annualised, historical"),
        ], columns=["Measure", "Value", "Basis"])
        st.dataframe(measures, hide_index=True, width="stretch")
        notes = (bm.get("notes") or []) + (pc.get("notes") or [])
        for n in notes:
            st.caption(n)

        c.section("Public news and announcements",
                  "Relevance shows the final judgement and its basis (LLM judgement or keyword heuristic). "
                  "'in_window' means published between the previous session's 15:30 IST close and the event-day "
                  "close. Published is the source's publication time; the event it reports may be earlier.")
        statuses = rec.get("news_statuses", [])
        attempted = [s for s in statuses if s.get("status") not in ("skipped", "link_only")]
        news = rec.get("news", [])
        if not attempted or all(s.get("status") == "failed" for s in attempted):
            c.banner("News evidence unavailable. No news source could be searched, so the investigation relies on "
                     "price, volume, benchmark and peer data only.", "warn")
        elif not news:
            st.info("Sources were searched but returned nothing inside the window. No public explanation was found "
                    "in the sources searched.")
        else:
            nd = pd.DataFrame([{
                "Relevance": n.get("final_relevance"),
                "Basis": n.get("final_basis"),
                "Timing": n.get("timing"),
                "Published (IST)": c.fmt_ist(n.get("published_at")),
                "Event date stated": n.get("event_date"),
                "Source": n.get("publisher") or n.get("provider"),
                "Headline": n.get("headline"),
                "Link": n.get("url"),
                "Why": n.get("final_rationale"),
            } for n in news])
            if nd["Event date stated"].isna().all():
                nd = nd.drop(columns=["Event date stated"])
            st.dataframe(nd, hide_index=True, width="stretch", column_config={
                "Link": st.column_config.LinkColumn(display_text="Open source"),
                "Headline": st.column_config.TextColumn(width="large"),
            })
        st.dataframe(pd.DataFrame([{"Source": s.get("provider"), "Status": s.get("status"),
                                    "Detail": s.get("message"),
                                    "Retrieved (IST)": c.fmt_ist(s.get("retrieved_at")) if s.get("retrieved_at") else None}
                                   for s in statuses]),
                     hide_index=True, width="stretch")
        links = rec.get("official_links") or []
        if links:
            c.section("Official disclosures: check manually (link-only)", DISCLOSURE_TERMS_NOTE)
            for link in links:
                st.markdown(f"- [{link.get('label')}]({link.get('url')}) ({link.get('publisher')}): "
                            f"{link.get('how')} Search for {link.get('search_for')}.")

    with tabs[2]:
        st.plotly_chart(c.hypothesis_chart(rub), width="stretch", config=c.PLOT_CONFIG)
        st.caption(rub.get("confidence_explanation", "") + " " + rub.get("news_basis", ""))
        notes = inv.get("hypothesis_notes") or {}
        for r in rub.get("results", []):
            with st.expander(f"{r['id']}  {r['label']}: score {r['score']:.0f}, {r['verdict'].lower()}"):
                crit = pd.DataFrame([{"Criterion": x["name"], "Effect": x["effect"], "Points": x["points"],
                                      "Evidence": x["evidence"]} for x in r.get("criteria", [])])
                st.dataframe(crit, hide_index=True, width="stretch",
                             column_config={"Points": st.column_config.NumberColumn(format="%+.0f"),
                                            "Evidence": st.column_config.TextColumn(width="large")})
                if r.get("cap_note"):
                    st.caption(r["cap_note"])
                if notes.get(r["id"]):
                    st.markdown(f"Investigator note: {notes[r['id']]}")

    with tabs[3]:
        risk = evid.get("get_risk_metrics") or {}
        expo = evid.get("get_portfolio_exposure") or {}
        conf = risk.get("confidence") or 0.95
        c.kpi_strip([
            {"label": f"1-day {conf:.0%} VaR before the event", "value": c.fmt_pct(risk.get("hist_var_1d_before_event"), False),
             "sub": f"historical, up to {risk.get('lookback_window_days') or 250} sessions to the event"},
            {"label": "Event move vs that VaR", "value": f"{c.fmt_num(risk.get('event_move_as_multiple_of_prior_var'), 1)}x"},
            {"label": "Volatility regime ratio", "value": c.fmt_num(risk.get("vol_regime_ratio")),
             "sub": "10-day vs earlier 60-day"},
            {"label": "Weight in illustrative portfolio",
             "value": c.fmt_pct(expo.get("holding_weight"), False) if expo.get("holding_weight") else "Not held",
             "sub": f"sector weight {c.fmt_pct(expo.get('sector_weight'), False)} (hypothetical)"},
        ])
        left, right = st.columns(2, gap="large")
        with left:
            c.section("Risk implications")
            for x in strat.get("risk_implications") or []:
                st.markdown(f"- {x}")
            c.section("Monitoring suggestions")
            for x in strat.get("monitoring_suggestions") or []:
                st.markdown(f"- {x}")
        with right:
            c.section("What would change the conclusion")
            for x in strat.get("what_would_change_conclusion") or []:
                st.markdown(f"- {x}")
            stresses = evid.get("run_stress_scenario") or []
            if stresses:
                value = expo.get("illustrative_portfolio_value")
                c.section("Hypothetical stress tests",
                          f"Illustrative portfolio of {c.fmt_inr_short(value)}. Assumptions, not observations.")
                for s in stresses:
                    o = s.get("outputs") or {}
                    st.html(f'<div class="ms-box assumed"><div class="t">{c.esc(s.get("scenario"))}</div>'
                            f'<div class="b">Portfolio return {c.fmt_pct(o.get("portfolio_return"))}, '
                            f'change in value {c.esc(c.fmt_inr_short(o.get("pnl"), signed=True))}</div>'
                            f'<div class="ms-formula">{c.esc(s.get("formula"))}</div></div>')

    with tabs[4]:
        audit = rec.get("audit", [])
        st.html(_stages_html(stage_progress(audit)))
        c.section("Model decisions", "Each model turn: the tools the LLM asked for, then what those tools returned. "
                                     "Taken from the audit trail, never reconstructed.")
        traces = [(who, decision_trace(audit, who)) for who in ("Market Investigator", "Risk Strategist")]
        if not any(t for _, t in traces):
            st.caption("No model decisions to show: this run used the rule-based protocol, which calls the same tools "
                       "in a fixed order without an LLM.")
        for who, turns in traces:
            for t in turns:
                with st.expander(f"{who}, turn {t['turn']}: asked for {', '.join(t['tools_requested']) or 'no tools'}"):
                    if t["model_note"]:
                        st.markdown(f"Model note: {t['model_note']}")
                    if t["steps"]:
                        st.dataframe(pd.DataFrame([{"Step": x["step"], "Status": x["status"],
                                                    "Arguments": json.dumps(x["arguments"])[:160],
                                                    "Result": x["result"]} for x in t["steps"]]),
                                     hide_index=True, width="stretch",
                                     column_config={"Result": st.column_config.TextColumn(width="large")})
        c.section("Full audit trail")
        tbl = pd.DataFrame([{"#": a.get("seq"), "Time (IST)": c.fmt_ist_clock(a.get("timestamp")), "Actor": a.get("actor"),
                             "Kind": a.get("kind"), "Step": a.get("name"), "Status": a.get("status"),
                             "Result": a.get("summary"), "ms": a.get("duration_ms")} for a in audit])
        st.dataframe(tbl, hide_index=True, width="stretch", height=420,
                     column_config={"Result": st.column_config.TextColumn(width="large")})
        tool_calls = [a for a in audit if a.get("kind") == "tool_call"]
        if tool_calls:
            pick = st.selectbox("Inspect a tool call", range(len(tool_calls)),
                                format_func=lambda i: f"#{tool_calls[i]['seq']} {tool_calls[i]['actor']}: {tool_calls[i]['name']}")
            a = tool_calls[pick]
            st.markdown("Arguments")
            st.code(json.dumps(a.get("arguments") or {}, indent=2), language="json")
            st.markdown("Output returned to the agent")
            st.code(json.dumps(a.get("output"), indent=2, default=str)[:12000], language="json")

    with tabs[5]:
        md = build_markdown(rec)
        base = rec.get("record_id", "report")
        b1, b2, b3 = st.columns(3)
        with b1:
            st.download_button("Download report (Markdown)", md, file_name=f"{base}.md", mime="text/markdown",
                               width="stretch")
        with b2:
            st.download_button("Download report (HTML, printable)", build_html(rec), file_name=f"{base}.html",
                               mime="text/html", width="stretch")
        with b3:
            st.download_button("Download full record (JSON)", json.dumps(rec, indent=2, default=str),
                               file_name=f"{base}.json", mime="application/json", width="stretch")
        with st.expander("Preview the Markdown report"):
            st.markdown(md)
