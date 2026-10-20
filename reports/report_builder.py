"""Builds the investigation report (Markdown and standalone HTML) from a saved record.

The report is generated only from the investigation record, so it reproduces
exactly what the agents and tools produced. It remains complete when news
retrieval failed: section 7 then says so explicitly.
"""
from __future__ import annotations

import html as html_lib

from agents.guidance import build_guidance

from config.market import DISCLOSURE_TERMS_NOTE, fmt_inr, fmt_market_clock, fmt_market_time
from config.settings import APP_NAME

DISCLAIMER = ("Educational analysis produced by a student prototype. It is not investment advice, does not "
              "recommend buying or selling any security and does not predict prices.")


def _pct(x, signed=True):
    if x is None:
        return "n/a"
    if abs(x) < 0.00005:          # avoid printing "-0.00%"
        x = 0.0
    return f"{x:+.2%}" if signed else f"{x:.2%}"


def _z(x):
    return "n/a" if x is None else f"{x:+.2f}"


def _num(x, fmt="{:,.2f}"):
    return "n/a" if x is None else fmt.format(x)


def _esc(text) -> str:
    """Escape characters that would break a Markdown table cell."""
    return str(text if text is not None else "").replace("|", "/").replace("\n", " ")


def _ist(value) -> str:
    """Stored UTC timestamp shown in India time (n/a when missing)."""
    return fmt_market_time(value) if value else "n/a"


def _inr(x, signed: bool = True) -> str:
    """Rupee amount with Indian digit grouping (whole rupees)."""
    return fmt_inr(x, signed=signed)


def _bullets(items) -> str:
    items = [i for i in (items or []) if i]
    return "\n".join(f"- {_esc(i)}" for i in items) if items else "- None recorded."


def build_markdown(rec: dict) -> str:
    ev = rec.get("event", {})
    data = rec.get("data", {})
    eng = rec.get("engine", {})
    inv = rec.get("investigator", {})
    strat = rec.get("strategist", {})
    rub = rec.get("rubric", {})
    evid = rec.get("evidence", {})
    rv = evid.get("calculate_returns_and_volatility") or {}
    vol = evid.get("calculate_abnormal_volume") or {}
    bm = evid.get("compare_with_benchmark") or {}
    pc = evid.get("compare_with_peers") or {}
    mc = evid.get("get_market_context") or {}
    risk = evid.get("get_risk_metrics") or {}
    expo = evid.get("get_portfolio_exposure") or {}
    ph = evid.get("get_price_history") or {}
    val = rec.get("validation", {})
    lines = []
    add = lines.append

    mode_banner = ""
    if data.get("mode") == "demo":
        mode_banner = ("> **SYNTHETIC DEMONSTRATION DATA.** All prices, volumes and announcements are synthetic and "
                       "refer to fictional securities.\n")
    add(f"# {APP_NAME} investigation report: {ev.get('name')} ({ev.get('ticker')})")
    add("")
    if mode_banner:
        add(mode_banner)
    add(f"Report ID `{rec.get('record_id')}` · created {_ist(rec.get('created_at'))} · reasoning engine: {eng.get('summary')}")
    add("")
    add(f"_{DISCLAIMER}_")
    add("")

    g = rec.get("guidance") or build_guidance(rec)
    expl, cat, act, unres = g["explanation"], g["catalyst"], g["action"], g.get("unresolved")
    add("## 1. Executive summary")
    add("**What happened?** " + g["what_happened"])
    add("")
    add(f"**What is the most plausible explanation?** {expl['headline']}.")
    add("")
    if unres:
        add(unres["established"])
        add("")
        add("Two explanations remain plausible: " + " and ".join(
            f"{p['label'].lower()} ({p['score']:.0f} points)" for p in unres["plausible"]) + ". "
            + unres["why_undistinguished"])
        add("")
        add("| Evidence to check | If found | If not found |\n|---|---|---|")
        for chk in unres["discriminating_checks"]:
            add(f"| {_esc(chk['check'])} | {_esc(chk['if_yes']) or '-'} | {_esc(chk['if_no']) or '-'} |")
    else:
        add(f"Status: {expl.get('status_text')}")
        if expl.get("supporting"):
            add("")
            add("Supporting evidence:")
            add(_bullets(expl["supporting"]))
        if expl.get("contradicting"):
            add("")
            add("Evidence against or limiting it:")
            add(_bullets(expl["contradicting"]))
    add("")
    add(f"**Catalyst evidence: level {cat['level']}, {cat['label']}.** {_esc(cat.get('statement', ''))}")
    if cat.get("url"):
        add(f"Source: [{_esc(cat.get('publisher'))}]({cat['url']}), published {cat.get('published_ist')}, retrieved "
            f"{_ist(cat.get('retrieved_at')) if cat.get('retrieved_at') else 'n/a'}; source ID `{cat.get('source_id')}`. "
            f"{_esc(cat.get('access_note', ''))}")
    elif cat.get("access_note"):
        add(_esc(cat["access_note"]))
    add("")
    add(f"**Recommended next action:** {act['primary']}. {act['why']} (Full action in section 13.)")
    add("")
    add("**What remains unknown?**")
    add(_bullets(g["unknowns"]) if g["unknowns"] else "No material question remains open beyond the limitations in "
        "section 13.")
    add("")
    add("Sections 3 to 10 hold the quantitative evidence and methodology behind this summary.")
    add("")

    add("## 2. Security, event date and data timestamps")
    add("| Field | Value |\n|---|---|")
    add(f"| Security | {_esc(ev.get('name'))} ({ev.get('ticker')}), peer group {ev.get('sector')} |")
    add(f"| Market | {_esc(data.get('market') or 'n/a')}, {_esc(data.get('session') or '')} |")
    add(f"| Benchmark | {_esc(data.get('benchmark_name') or data.get('benchmark') or 'n/a')} |")
    add(f"| Currency (as reported by the provider) | {_esc(data.get('symbol_currency') or data.get('currency') or 'n/a')} |")
    add(f"| Event date (NSE trading session) | {str(ev.get('date'))[:10]} |")
    add(f"| Prices used up to | {data.get('prices_used_up_to')} |")
    add(f"| Market data source | {_esc(data.get('provider'))} (mode: {data.get('mode')}) |")
    add(f"| Market data retrieved at | {_ist(data.get('data_retrieved_at')) if data.get('data_retrieved_at') else 'n/a (synthetic)'} |")
    add(f"| Investigation run at | {_ist(rec.get('created_at'))} |")
    add(f"| Investigation type | {'Historical as-of (news after the event-day close excluded)' if rec.get('historical') else 'Live investigation of a detected event'} |")
    add("")

    add("## 3. What was observed")
    sector_text = (f"the {pc.get('sector_index_name')} sector index returned {_pct(pc.get('sector_index_return'))}"
                   if pc.get("sector_index_name") else "no sector index is configured for this peer group")
    add(f"{ev.get('name')} returned **{_pct(ev.get('ret'))}** on {str(ev.get('date'))[:10]}. "
        f"Volume was {_num(ev.get('volume'), '{:,.0f}')} shares, {_num(ev.get('volume_ratio'), '{:.1f}')}x its 60-day median. "
        f"The benchmark ({bm.get('benchmark_name') or data.get('benchmark_name') or 'benchmark'}) returned "
        f"{_pct(bm.get('benchmark_return'))} and {sector_text}.")
    add("")

    add("## 4. Why the event triggered an alert")
    add(_bullets(ev.get("triggers")))
    add("")
    add(f"Priority score **{_num(ev.get('priority_score'), '{:.1f}')} / 100** ({ev.get('severity')}). "
        "The score ranks analyst attention; it is not a probability of cause or a forecast.")
    add("")
    add("| Component | Normalised (0-1) | Weight | Points |\n|---|---|---|---|")
    cfg = rec.get("config", {})
    comps = [("Abnormal price move", ev.get("s_price"), cfg.get("w_price")),
             ("Market-relative move", ev.get("s_abnormal"), cfg.get("w_abnormal")),
             ("Abnormal volume", ev.get("s_volume"), cfg.get("w_volume")),
             ("Volatility regime shift", ev.get("s_regime"), cfg.get("w_vol_regime"))]
    for label, s, w in comps:
        pts = None if s is None or w is None else 100 * s * w
        add(f"| {label} | {_num(s, '{:.2f}')} | {_num(w, '{:.2f}')} | {_num(pts, '{:.1f}')} |")
    add("")

    add("## 5. Price and volume evidence")
    add("| Measure | Value |\n|---|---|")
    add(f"| Simple return | {_pct(rv.get('simple_return'))} |")
    add(f"| Log return | {_num(rv.get('log_return'), '{:+.4f}')} |")
    add(f"| Baseline median return ({cfg.get('lookback')} sessions before the event) | {_pct(rv.get('baseline_median_return'))} |")
    add(f"| Robust z of return | {_z(rv.get('robust_z_return'))} |")
    add(f"| Volume / 60-day median | {_num(vol.get('volume_ratio'), '{:.2f}')}x |")
    add(f"| Robust z of log volume | {_z(vol.get('robust_z_log_volume'))} |")
    add(f"| Realised volatility, last 10 sessions (annualised, historical) | {_pct(rv.get('vol_recent_10d_annualised'), False)} |")
    add(f"| Realised volatility, earlier 60 sessions (annualised, historical) | {_pct(rv.get('vol_prior_60d_annualised'), False)} |")
    add(f"| Return over the 5 sessions before the event | {_pct(ph.get('return_5d_before_event'))} |")
    add("")

    add("## 6. Benchmark and peer comparison")
    if bm.get("available"):
        add(f"Market model estimated on {bm.get('estimation_window_start')} to {bm.get('estimation_window_end')} "
            f"({_num(bm.get('estimation_obs'), '{:.0f}')} paired observations) against "
            f"{bm.get('benchmark_name') or bm.get('benchmark')}.")
        add("")
        add("| Measure | Value |\n|---|---|")
        add(f"| Beta | {_num(bm.get('beta'))} |")
        add(f"| R-squared | {_num(bm.get('r_squared'))} |")
        add(f"| Benchmark return (robust z) | {_pct(bm.get('benchmark_return'))} ({_z(bm.get('benchmark_z'))}) |")
        add(f"| Expected return (alpha + beta x benchmark) | {_pct(bm.get('expected_return'))} |")
        add(f"| Abnormal return (z) | {_pct(bm.get('abnormal_return'))} ({_z(bm.get('abnormal_z'))}) |")
    else:
        add("Market model unavailable. " + " ".join(bm.get("notes") or []))
    add("")
    if pc.get("peers"):
        add(f"Peers ({pc.get('peers_source')}): median return {_pct(pc.get('peer_median_return'))}; return relative to "
            f"the peer median {_pct(pc.get('relative_return'))} (robust z {_z(pc.get('relative_z'))}).")
        add("")
        add("| Peer | Return | Robust z |\n|---|---|---|")
        for p in pc.get("peers", []):
            add(f"| {p.get('ticker')} | {_pct(p.get('return'))} | {_z(p.get('robust_z'))} |")
        if pc.get("sector_index_name"):
            add(f"| {pc.get('sector_index_name')} (sector index) | {_pct(pc.get('sector_index_return'))} | "
                f"{_z(pc.get('sector_index_z'))} |")
    elif pc:
        add("No peer comparison: no other watchlist stock belongs to this peer group.")
    for n in (bm.get("notes") or []) + (pc.get("notes") or []):
        add(f"\nNote: {n}")
    if mc.get("available"):
        add("")
        add(f"Market breadth that day: {_pct(mc.get('share_up'), False)} of the watchlist rose; "
            f"{mc.get('n_events')} alert(s) across the watchlist.")
    add("")

    add("## 7. Relevant public news and announcements")
    statuses = rec.get("news_statuses", [])
    news = rec.get("news", [])
    attempted = [s for s in statuses if s.get("status") not in ("skipped", "link_only")]
    if not attempted or all(s.get("status") == "failed" for s in attempted):
        add("**News evidence unavailable.** No news source could be searched, so no explanation from public "
            "sources is offered.")
    elif not news:
        add("Sources were searched successfully but returned no items inside the window. No public explanation was "
            "found in the sources searched.")
    else:
        add("| Relevance | Timing | Published (IST) | Source | Headline |\n|---|---|---|---|---|")
        for n in news[:20]:
            head = _esc(n.get("headline"))[:160]
            link = f"[{head}]({n['url']})" if n.get("url") else head
            if n.get("event_date"):
                link += f" (event date stated by the source: {n['event_date']})"
            add(f"| {n.get('final_relevance')} ({_esc(n.get('final_basis'))}) | {n.get('timing')} | "
                f"{_ist(n.get('published_at'))} | {_esc(n.get('publisher') or n.get('provider'))} | {link} |")
        add("")
        add("Timing: 'in_window' means published between the previous session's 15:30 IST close and the event-day "
            "close. Items published after the close cannot have caused the move. The publication time is not "
            "necessarily the date of the event a source reports.")
    add("")
    add("Sources queried: " + "; ".join(f"{s.get('provider')}: {s.get('status')} ({_esc(s.get('message'))[:160]})"
                                        for s in statuses))
    links = rec.get("official_links") or []
    if links:
        add("")
        add("Official disclosures, link-only (not searched automatically; check manually): "
            + "; ".join(f"[{_esc(link.get('label'))}]({link.get('url')})" for link in links) + ". "
            + DISCLOSURE_TERMS_NOTE)
    add("")

    add("## 8. Competing hypotheses")
    add("| Rank | Hypothesis | Evidence score (0-100) | Verdict |\n|---|---|---|---|")
    for i, r in enumerate(rub.get("results", []), start=1):
        add(f"| {i} | {r.get('id')} {r.get('label')} | {r.get('score'):.0f} | {r.get('verdict')} |")
    add("")

    add("## 9. Evidence for and against each hypothesis")
    notes = inv.get("hypothesis_notes") or {}
    for r in rub.get("results", []):
        add(f"### {r.get('id')} {r.get('label')} (score {r.get('score'):.0f})")
        add("| Criterion | Effect | Points | Evidence |\n|---|---|---|---|")
        for c in r.get("criteria", []):
            add(f"| {_esc(c.get('name'))} | {c.get('effect')} | {c.get('points'):+.0f} | {_esc(c.get('evidence'))} |")
        if r.get("cap_note"):
            add(f"\n{r['cap_note']}")
        if notes.get(r.get("id")):
            add(f"\nInvestigator note: {notes[r['id']]}")
        add("")

    add("## 10. Confidence assessment")
    add(f"Rubric assessment: {rub.get('conclusion', 'n/a')}")
    add("")
    add(f"Confidence: **{rub.get('confidence')}**. {rub.get('confidence_explanation')}")
    add("")
    tech = strat.get("executive_summary") or inv.get("summary")
    if tech:
        add(f"Technical summary written by the agents: {tech}")
        add("")
    add("The rubric adds or subtracts fixed points per criterion and clips each score to 0-100. A conclusion is only "
        "stated when the leading explanation scores at least 45 and leads by at least 10 points; otherwise the "
        f"outcome is 'insufficient evidence'. {rub.get('news_basis', '')}")
    add("")

    add("## 11. Potential risk implications")
    add(_bullets(strat.get("risk_implications")))
    add("")
    if risk.get("available"):
        add("| Risk measure (data up to the event date) | Value |\n|---|---|")
        conf = risk.get("confidence") or 0.95
        lookback = risk.get("lookback_window_days") or 250
        add(f"| One-day {conf:.0%} historical VaR before the event ({lookback}-session lookback) | "
            f"{_pct(risk.get('hist_var_1d_before_event'), False)} |")
        add(f"| Event move as a multiple of that VaR | {_num(risk.get('event_move_as_multiple_of_prior_var'), '{:.2f}')}x |")
        add(f"| One-day {conf:.0%} expected shortfall (including the event day) | {_pct(risk.get('hist_es_1d'), False)} |")
        add(f"| Volatility regime ratio (10-day / earlier 60-day) | {_num(risk.get('vol_regime_ratio'))} |")
        add(f"| Max drawdown, last 120 sessions | {_pct(risk.get('max_drawdown_120d'))} |")
    if expo:
        held = _pct(expo.get('holding_weight'), False) if expo.get("holding_weight") else "not held"
        add(f"| Weight in illustrative portfolio (hypothetical) | {held} |")
        add(f"| Sector weight in illustrative portfolio (hypothetical) | {_pct(expo.get('sector_weight'), False)} |")
    for st in (evid.get("run_stress_scenario") or []):
        o = st.get("outputs") or {}
        add(f"\nHypothetical stress test, {st.get('scenario')}: {st.get('formula')}. Illustrative portfolio return "
            f"{_pct(o.get('portfolio_return'))}, change in value {_inr(o.get('pnl'))} on an illustrative portfolio of "
            f"{_inr(expo.get('illustrative_portfolio_value'), signed=False)}.")
    add("")
    add("Monitoring suggestions:")
    add(_bullets(strat.get("monitoring_suggestions")))
    add("")
    add("What would change this conclusion:")
    add(_bullets(strat.get("what_would_change_conclusion")))
    add("")

    add("## 12. What remains unknown")
    add(_bullets(g["unknowns"]) if g["unknowns"] else "No material question remains open.")
    other = [u for u in (inv.get("unknowns") or []) if u not in g["unknowns"]]
    if other:
        add("")
        add("Standing limitations of the method:")
        add(_bullets(other))
    add("")

    add("## 13. Recommended next action")
    add(f"**{act['primary']}.**")
    add("")
    add(f"Why this action: {act['why']}")
    add("")
    add("Steps, in order:")
    for i, step in enumerate(act["steps"], start=1):
        add(f"{i}. {_esc(step)}")
    add("")
    add(f"What would change the assessment: {act['reassess_if']}")
    add("")
    add(f"Expected outcome: {act['expected_outcome']}")
    add("")
    add(f"When to withhold a stronger conclusion: {act['escalate_if']}")
    add("")
    if act.get("evidence"):
        add("Evidence behind this action:")
        add(_bullets([f"{e.get('ref')}: {e.get('text')}" for e in act["evidence"]]))
        add("")
    if act.get("links"):
        add("Official pages for manual verification (link-only): " + "; ".join(
            f"[{_esc(link.get('label'))}]({link.get('url')})" for link in act["links"]) + ".")
        add("")
    add("Limitations:")
    add(_bullets(act.get("limitations")))
    add("")
    add(f"_{act.get('advice_note', '')}_")
    add("")

    add("## 14. Investigation timeline and tool calls")
    add(f"Engine: investigator = {eng.get('investigator')}, strategist = {eng.get('strategist')}. "
        f"Run time {rec.get('duration_s')} s.")
    if eng.get("llm_errors"):
        add("")
        for e in eng["llm_errors"]:
            add(f"> {e}")
    add("")
    add("| # | Time (IST) | Actor | Step | Status | Result |\n|---|---|---|---|---|---|")
    for a in rec.get("audit", []):
        add(f"| {a.get('seq')} | {fmt_market_clock(a.get('timestamp')) or 'n/a'} | "
            f"{_esc(a.get('actor'))} | {_esc(a.get('name'))} | "
            f"{a.get('status')} | {_esc(a.get('summary'))[:220]} |")
    add("")

    add("## Validation and warnings")
    add(f"- Look-ahead check: event re-detected using only data up to the event date: "
        f"{'passed' if val.get('lookahead_check_passed') else 'not reproduced'}.")
    add(f"- Baseline observations: {val.get('baseline_observations')} (minimum {val.get('min_required')}).")
    add(f"- Data-quality status for the security: {val.get('data_quality_status')}.")
    for w in rec.get("warnings", []):
        add(f"- {_esc(w)}")
    uv = rec.get("unverified_figures") or {}
    if uv:
        for who, fields in uv.items():
            figs = sorted({f for v in fields.values() for f in v})
            add(f"- Unverified figures in {who} text (no matching tool output): {', '.join(figs)}")
    add("")
    add(f"_{DISCLAIMER}_")
    return "\n".join(lines)


HTML_CSS = """
body{font-family:-apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;color:#0f172a;background:#f8fafc;margin:0}
main{max-width:980px;margin:0 auto;padding:32px 28px 64px;background:#fff}
h1{font-size:1.6rem;border-bottom:3px solid #0e7490;padding-bottom:10px}
h2{font-size:1.15rem;color:#0e7490;margin-top:32px;border-bottom:1px solid #e2e8f0;padding-bottom:4px}
h3{font-size:1rem;margin-top:20px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:.86rem}
th,td{border:1px solid #e2e8f0;padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f1f5f9}
blockquote{border-left:4px solid #d97706;background:#fffbeb;margin:12px 0;padding:8px 14px}
code{background:#f1f5f9;padding:1px 4px;border-radius:3px}
a{color:#0e7490}
@media print{body{background:#fff}main{padding:0}}
"""


def build_html(rec: dict) -> str:
    md_text = build_markdown(rec)
    try:
        import markdown
        body = markdown.markdown(md_text, extensions=["tables"])
    except ImportError:  # pragma: no cover - fallback keeps the download working
        body = "<pre>" + html_lib.escape(md_text) + "</pre>"
    title = html_lib.escape(f"{APP_NAME} report {rec.get('record_id', '')}")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>{title}</title>"
            f"<meta name='viewport' content='width=device-width, initial-scale=1'><style>{HTML_CSS}</style></head>"
            f"<body><main>{body}</main></body></html>")
