"""The analyst reading, the 'what the model did' lines and the rule-based 'what would change' text."""
from __future__ import annotations

from agents.hypotheses import Criterion, HypothesisEvaluation, HypothesisResult
from agents.risk_strategist import _h5_change
from agents.trace import (NO_MODEL_NOTE, analyst_reading, model_activity, model_activity_lines,
                          model_activity_summary)


def _llm_record() -> dict:
    audit = [
        {"actor": "Market Investigator", "kind": "llm_turn", "output": {"tools_requested": [
            "calculate_returns_and_volatility", "search_public_news"]}},
        {"actor": "Market Investigator", "kind": "tool_call", "name": "calculate_returns_and_volatility", "status": "ok",
         "arguments": {}, "summary": "ok"},
        {"actor": "Market Investigator", "kind": "tool_call", "name": "search_public_news", "status": "ok",
         "arguments": {"days_before": 2, "days_after": 1}, "summary": "71 items"},
        {"actor": "Market Investigator", "kind": "llm_turn", "output": {"tools_requested": ["list_news_items"]}},
        {"actor": "Market Investigator", "kind": "tool_call", "name": "list_news_items", "status": "ok", "summary": "10"},
        {"actor": "Market Investigator", "kind": "llm_turn", "output": {"tools_requested": ["submit_investigation"]}},
        {"actor": "Risk Strategist", "kind": "llm_turn", "output": {"tools_requested": ["run_stress_scenario"]}},
        {"actor": "Risk Strategist", "kind": "tool_call", "name": "run_stress_scenario", "status": "ok",
         "summary": "IT services holdings move -10%: portfolio return -1.70%"},
        {"actor": "Risk Strategist", "kind": "llm_turn", "output": {"tools_requested": ["submit_risk_assessment"]}},
        {"actor": "Risk Strategist", "kind": "validation", "name": "numeric grounding check", "status": "warning",
         "summary": "These figures do not match any tool output: 7,317,480. Use only numbers returned by tools "
                    "(copy them) or remove them, then submit again."},
        {"actor": "Risk Strategist", "kind": "llm_turn", "output": {"tools_requested": ["submit_risk_assessment"]}},
    ]
    return {
        "engine": {"investigator": "llm", "strategist": "llm", "model": "gemini-3.5-flash"},
        "audit": audit,
        "rubric": {"leading": "H5", "results": [
            {"id": "H2", "label": "Sector-wide movement", "score": 75.0},
            {"id": "H3", "label": "Company-specific news or announcement", "score": 70.0},
            {"id": "H5", "label": "Insufficient evidence", "score": 45.0},
            {"id": "H1", "label": "Broad market movement", "score": 10.0}]},
        "investigator": {"summary": "Model summary.", "hypothesis_notes": {
            "H2": "The sector index rose sharply.", "H3": "Results were published after the close.",
            "H5": "Both drivers coincided."}, "follow_up_checks": ["Compare the profit with consensus."],
            "unknowns": ["Order flow."]},
        "strategist": {"executive_summary": "Risk summary.", "what_would_change_conclusion": ["A filing revision."]},
        "news": [{"headline": "Top gainers today", "publisher": "X", "relevance": "uncertain",
                  "final_relevance": "unrelated", "final_basis": "LLM judgement", "final_rationale": "Published after the close."},
                 {"headline": "Other", "relevance": "direct", "final_relevance": "direct", "final_basis": "keyword heuristic"}],
    }


def test_analyst_reading_uses_only_the_models_own_text():
    r = analyst_reading(_llm_record())
    assert r["model"] == "gemini-3.5-flash"
    assert [e["id"] for e in r["explanations"]] == ["H2", "H3"]
    assert r["explanations"][1]["note"] == "Results were published after the close."
    assert r["why_unresolved"] == "Both drivers coincided."
    assert r["checks"] == ["Compare the profit with consensus."]
    assert r["would_change"] == ["A filing revision."]


def test_no_reading_for_rule_based_runs():
    rec = _llm_record()
    rec["engine"] = {"investigator": "rules (no LLM configured)", "strategist": "rules (no LLM configured)"}
    assert analyst_reading(rec) is None
    assert "No model analysis" in NO_MODEL_NOTE


def test_model_activity_describes_choices_from_the_audit():
    act = model_activity(_llm_record())
    lines = " ".join(model_activity_lines(act))
    assert "Investigator, 3 model turn(s)" in lines
    assert "news window of 2 session(s) before and 1 after" in lines
    assert "added news listing" in lines
    assert "judged 1 of 2 itself and changed the keyword label of 1" in lines
    assert "uncertain to unrelated" in lines
    assert "rejected 7,317,480 (strategist)" in lines
    assert "Required checks the orchestrator had to add: none." in lines
    assert model_activity_summary(act).startswith("gemini-3.5-flash chose")


def _rubric(top, second, h5_criteria):
    results = [HypothesisResult(top[0], top[1], top[2], ""), HypothesisResult(second[0], second[1], second[2], ""),
               HypothesisResult("H5", "Insufficient evidence", 45.0, "", h5_criteria)]
    return HypothesisEvaluation(results=results, leading="H5", leading_label="Insufficient evidence", conclusion="",
                                confidence="Low", margin=top[2] - second[2], confidence_explanation="",
                                inconclusive=True, inputs={}, news_basis="")


def test_h5_change_names_the_pair_when_news_and_beta_worked():
    rub = _rubric(("H2", "Sector-wide movement", 75.0), ("H3", "Company-specific news or announcement", 70.0),
                  [Criterion("H5", "Leading explanations are close", "supports", 30, "close"),
                   Criterion("H5", "Data-quality warnings", "supports", 15, "1 warning")])
    text = " ".join(_h5_change(rub))
    assert "company disclosure" in text and "sector-wide move (H2)" in text
    assert "5 points apart" in text
    assert "news retrieval" not in text and "beta" not in text


def test_h5_change_mentions_news_and_missing_measures_only_when_they_failed():
    rub = _rubric(("H4", "Unexplained trading", 40.0), ("H3", "Company-specific news or announcement", 20.0),
                  [Criterion("H5", "News sources unavailable", "supports", 25, "No news source could be searched."),
                   Criterion("H5", "Core measures missing", "supports", 20, "Missing: beta"),
                   Criterion("H5", "No explanation reaches the evidence threshold", "supports", 10, "below")])
    text = " ".join(_h5_change(rub))
    assert "news search" in text and "(beta)" in text and "below 45" in text


def test_summary_tab_shows_the_reading_only_for_model_runs(monkeypatch):
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv("MS_TEST_PAGE", "investigate")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(str(Path(__file__).parent / "page_harness.py"), default_timeout=180)
    at.run()
    [b for b in at.button if b.label == "Run investigation"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert "No model analysis in this run" in html and "Analyst reading by" not in html

    rec = dict(at.session_state["current_record"])
    llm = _llm_record()
    rec.update({k: llm[k] for k in ("engine", "investigator", "strategist", "news")})
    start = len(rec["audit"])
    rec["audit"] = list(rec["audit"]) + [dict(e, seq=start + i + 1, timestamp=rec["audit"][-1].get("timestamp"),
                                              arguments=e.get("arguments") or {}, output=e.get("output") or {})
                                         for i, e in enumerate(llm["audit"])]
    rec["rubric"] = dict(rec["rubric"], leading="H5", results=[dict(r, criteria=[], verdict="") for r in llm["rubric"]["results"]])
    rec.pop("guidance", None)
    at.session_state["current_record"] = rec
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert "Analyst reading by gemini-3.5-flash" in html
    assert "Results were published after the close." in html and "fixed rubric alone" in html
    assert any("gemini-3.5-flash chose" in str(c.value) for c in at.caption)


def test_rule_based_report_states_no_model_analysis(demo_ds, demo_monitor, settings):
    from agents.orchestrator import run_investigation
    from reports.report_builder import build_markdown
    rec = run_investigation("IRONBRG.DEMO:2026-09-17", demo_ds, settings, scan=demo_monitor.scan, save=False).as_dict()
    md = build_markdown(rec)
    assert NO_MODEL_NOTE in md
    assert "Successful news retrieval, longer price history or estimable beta" not in " ".join(
        rec["strategist"]["what_would_change_conclusion"]) or rec["rubric"]["leading"] != "H5"
