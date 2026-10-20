"""Evidence levels, business summary and the next-action engine (agents/guidance.py).

The live cases are controlled fixtures modelled on the two investigations reported from the deployed app on
20 Oct 2026 (a stock tied between a sector move and company news; a stock led by company news on the strength of an
earnings headline). They use fictional companies and headlines, so no announcement is attributed to a real company,
and the production code contains no case-specific logic.
"""
import copy
import re

import pytest

from agents.guidance import LEVELS, build_guidance, classify_catalyst, headline_category
from config.market import OFFICIAL_DISCLOSURE_LINKS

ADVICE = re.compile(r"\b(buy|sell|hold|target price|entry|exit|stop loss)\b", re.I)


def _links(name):
    return [{**link, "search_for": f"{name} (NSE symbol TESTCO)", "access": "link-only (manual verification)"}
            for link in OFFICIAL_DISCLOSURE_LINKS]


def _record(*, leading, inconclusive, scores, confidence, inputs, news, statuses=None, validation=None,
            name="Testco Industries (fictional)", ret=0.0842, mode="live"):
    labels = {"H1": "Broad-market movement", "H2": "Sector-wide movement",
              "H3": "Company-specific news or announcement",
              "H4": "Unusual trading activity without an identified public explanation",
              "H5": "Insufficient evidence to classify the event"}
    verdict = lambda v: ("Strongly supported" if v >= 70 else "Supported" if v >= 50 else "Weakly supported"  # noqa: E731
                         if v >= 25 else "Not supported")
    results = sorted(({"id": h, "label": labels[h], "score": s, "verdict": verdict(s), "criteria": []}
                      for h, s in scores.items()),
                     key=lambda r: -r["score"])
    base_inputs = {"ret": ret, "benchmark": "NIFTY 50", "beta": 0.9, "data_quality_warnings": [],
                   "sector_index_configured": True, "peers_configured": True}
    base_inputs.update(inputs)
    return {
        "event": {"event_id": "TESTCO.NS:2026-10-13", "ticker": "TESTCO.NS", "name": name, "date": "2026-10-13",
                  "sector": "IT services", "ret": ret},
        "rubric": {"leading": leading, "leading_label": labels[leading], "inconclusive": inconclusive,
                   "confidence": confidence, "results": results, "inputs": base_inputs},
        "news": news,
        "news_statuses": statuses if statuses is not None else [
            {"provider": "Google News RSS (India edition)", "status": "ok", "message": ""},
            {"provider": "Yahoo Finance headlines (yfinance)", "status": "empty", "message": ""},
            {"provider": "NSE/BSE official disclosures (link-only)", "status": "link_only", "message": ""}],
        "official_links": _links(name),
        "validation": validation or {"lookahead_check_passed": True, "baseline_observations": 60.0,
                                     "min_required": 40, "partial_session": False},
        "evidence": {"compare_with_benchmark": {}, "compare_with_peers": {}, "calculate_abnormal_volume": {}},
        "data": {"mode": mode, "benchmark_name": "NIFTY 50"},
    }


SECTOR_TIE_INPUTS = {"mkt_ret": 0.016, "z_mkt": 3.1, "abnormal_ret": 0.0699, "z_abn": 3.4, "rel_ret": 0.0296,
                     "z_rel": 2.2, "n_peers": 2, "sector_ret": 0.0522, "z_sector": 5.1, "sector_index": "NIFTY IT",
                     "volume_ratio": 8.9, "z_volume": 4.3, "z_ret": 5.2, "breadth_same": 0.92,
                     "sector_wide_move": True, "market_wide_move": True}
COMPANY_HEADLINE = {"source_id": "GN-abc123", "headline": "Testco Industries shares surge 7% as strong Q1 FY27 earnings "
                    "beat estimates", "provider": "Google News RSS (India edition)", "source_type": "news_headline",
                    "publisher": "Example Business Daily", "published_at": "2026-10-13T08:35:00+00:00",
                    "url": "https://news.example.com/testco-q1", "timing": "in_window",
                    "final_relevance": "direct", "mentions_company": True, "retrieved_at": "2026-10-20T11:08:30+00:00",
                    "event_date": None, "event_note": ""}


@pytest.fixture
def sector_tie():
    """Sector move (75) and company news (70) almost tied, one direct headline: the reported unresolved case."""
    return _record(leading="H5", inconclusive=True, confidence="Low",
                   scores={"H2": 75, "H3": 70, "H1": 40, "H4": 10, "H5": 30},
                   inputs=SECTOR_TIE_INPUTS, news=[COMPANY_HEADLINE])


@pytest.fixture
def earnings_headline():
    """Company news leads on an earnings headline whose article was not read: the reported provisional case."""
    inputs = {"mkt_ret": 0.004, "z_mkt": 0.6, "abnormal_ret": 0.0771, "z_abn": 6.0, "rel_ret": 0.071, "z_rel": 5.5,
              "n_peers": 5, "sector_ret": 0.006, "z_sector": 0.7, "sector_index": "NIFTY Bank", "volume_ratio": 5.2,
              "z_volume": 4.8, "z_ret": 4.8, "breadth_same": 0.6, "sector_wide_move": False, "market_wide_move": False}
    return _record(leading="H3", inconclusive=False, confidence="High",
                   scores={"H3": 85, "H4": 30, "H2": 0, "H1": 0, "H5": 0}, inputs=inputs, news=[COMPANY_HEADLINE])


def _all_text(g: dict) -> str:
    a = g["action"]
    parts = [g["what_happened"], a["primary"], a["why"], a["reassess_if"], a["expected_outcome"], a["escalate_if"],
             *a["steps"], *g["unknowns"], g["catalyst"].get("statement", "")]
    return " ".join(parts)


def test_unresolved_case_still_gives_one_meaningful_next_action(sector_tie):
    g = build_guidance(sector_tie)
    assert g["explanation"]["status"] == "unresolved"
    u = g["unresolved"]
    assert {p["id"] for p in u["plausible"]} == {"H2", "H3"}
    assert "statistically unusual move" in u["established"] and "+8.4%" in u["established"]
    assert "peer group moved strongly" in u["why_undistinguished"] and "cannot separate" in u["why_undistinguished"]
    checks = u["discriminating_checks"]
    assert checks and all(c["check"] and c["if_yes"] and c["if_no"] for c in checks)   # how each check moves the case
    a = g["action"]
    assert a["kind"] == "separate_explanations"
    assert a["primary"].startswith("Check Testco Industries (fictional)'s exchange filings for the results filing")
    assert 1 <= len(a["steps"]) <= 3
    assert any(e["ref"] == "compare_with_peers" for e in a["evidence"])
    assert any(e["ref"] == "GN-abc123" for e in a["evidence"])                          # the actual source
    assert any(link["url"].startswith("https://www.nseindia.com/") for link in a["links"])
    assert "Which of sector-wide movement and company-specific news" in g["unknowns"][0]


def test_unresolved_action_does_not_repeat_completed_checks(sector_tie):
    steps = " ".join(build_guidance(sector_tie)["action"]["steps"]).lower()
    assert "search the news" not in steps and "run the news search" not in steps     # news search already succeeded
    assert "compare the stock with the nifty 50" not in steps                          # benchmark comparison done


def test_company_classification_names_the_candidate_catalyst_as_provisional(earnings_headline):
    g = build_guidance(earnings_headline)
    cat = g["catalyst"]
    assert cat["level"] == "B" and cat["label"] == LEVELS["B"] == "Potential catalyst - not yet verified"
    assert cat["category"] == "quarterly results or earnings"
    assert cat["headline"] == COMPANY_HEADLINE["headline"] and cat["url"] == COMPANY_HEADLINE["url"]
    assert cat["publisher"] == "Example Business Daily" and cat["published_ist"] == "13 Oct 2026, 14:05 IST"
    assert cat["source_id"] == "GN-abc123" and cat["retrieved_at"] == COMPANY_HEADLINE["retrieved_at"]
    s = cat["statement"]
    assert s.startswith("Potential catalyst: a news headline from Example Business Daily (13 Oct 2026, 14:05 IST) "
                        "reports quarterly results or earnings")
    assert "does not establish the full content" in s and "Check the results filing" in s
    assert "article text was not read" in cat["access_note"].lower()
    e = g["explanation"]
    assert e["status"] == "provisional" and e["status"] != "verified"        # a headline never verifies a cause
    assert e["headline"] == "Potential catalyst: quarterly results or earnings reported in a headline"
    a = g["action"]
    assert a["kind"] == "verify_catalyst" and a["primary"].startswith("Verify the reported quarterly results")
    assert "no filing exists" in a["reassess_if"] and "peers moved by a similar amount" in a["reassess_if"]


def test_headline_with_no_cause_category_is_not_given_one():
    assert headline_category("Testco Industries shares surge 7% in heavy trade") is None
    assert headline_category("Testco wins Rs 900 crore order from state utility") == "an order or contract win"
    assert headline_category("Testco Q2 net profit rises 12%") == "quarterly results or earnings"


def test_no_catalyst_gives_a_verification_action_not_an_explanation():
    rec = _record(leading="H4", inconclusive=False, confidence="Moderate",
                  scores={"H4": 70, "H3": 40, "H2": 0, "H1": 0, "H5": 0},
                  inputs={"mkt_ret": -0.002, "z_mkt": -0.2, "abnormal_ret": -0.06, "z_abn": -4.0, "rel_ret": -0.05,
                          "z_rel": -3.5, "n_peers": 2, "sector_ret": 0.001, "z_sector": 0.1, "sector_index": "NIFTY IT",
                          "volume_ratio": 6.0, "z_volume": 5.0, "z_ret": -4.1, "breadth_same": 0.4},
                  news=[dict(COMPANY_HEADLINE, final_relevance="uncertain", timing="after_close",
                             headline="Testco Industries shares slide 6%")], ret=-0.061)
    g = build_guidance(rec)
    assert g["catalyst"]["level"] == "C" and g["catalyst"]["label"] == "No identified catalyst"
    assert "after the event-day close" in g["catalyst"]["statement"]
    a = g["action"]
    assert a["kind"] == "investigate_volume"
    assert "not evidence of misconduct" in a["escalate_if"]
    assert "manipulation" not in _all_text(g).lower()


def test_failed_news_search_is_the_action_and_nothing_is_called_unexplained(sector_tie):
    rec = copy.deepcopy(sector_tie)
    rec["news"] = []
    rec["news_statuses"] = [{"provider": "Google News RSS (India edition)", "status": "failed", "message": "timeout"},
                            {"provider": "NSE/BSE official disclosures (link-only)", "status": "link_only"}]
    g = build_guidance(rec)
    assert g["catalyst"]["reason"] == "news_unavailable" and g["catalyst"]["level"] == "C"
    assert g["action"]["kind"] == "restore_news"
    assert "Do not describe the move as unexplained" in g["action"]["escalate_if"]


def test_unreliable_data_makes_validation_the_primary_action(earnings_headline):
    rec = copy.deepcopy(earnings_headline)
    rec["validation"].update(baseline_observations=22.0, lookahead_check_passed=False)
    g = build_guidance(rec)
    assert g["action"]["kind"] == "validate_data"
    assert "only 22 sessions of baseline history" in g["action"]["why"]
    assert "Do not report a cause" in g["action"]["escalate_if"]


def test_action_figures_come_from_the_record(sector_tie, earnings_headline):
    """No invented thresholds or deadlines: every number in the guidance text appears in the record's inputs."""
    for rec in (sector_tie, earnings_headline):
        g = build_guidance(rec)
        text = _all_text(g)
        x = rec["rubric"]["inputs"]
        allowed = {f"{abs(v):.1%}" for v in x.values() if isinstance(v, float)} | \
                  {f"{v:+.1%}" for v in x.values() if isinstance(v, float)} | \
                  {f"{x['volume_ratio']:.1f}", f"{rec['event']['ret']:+.1%}", f"{abs(rec['event']['ret']):.1%}"}
        if x.get("rel_ret") is not None and x.get("ret") is not None:
            pm = x["ret"] - x["rel_ret"]
            allowed |= {f"{abs(pm):.1%}", f"{pm:+.1%}"}
        for num in re.findall(r"[+-]?\d+\.\d%?", text):
            assert num in allowed or num.lstrip("+-") in allowed, (num, text)


def test_guidance_never_gives_trading_advice(sector_tie, earnings_headline):
    for rec in (sector_tie, earnings_headline):
        g = build_guidance(rec)
        text = _all_text(g).replace("not a recommendation to buy, sell or hold", "")
        assert not ADVICE.search(text), ADVICE.search(text)
        assert "not a recommendation to buy, sell or hold" in g["action"]["advice_note"]


def test_verified_level_only_for_a_retrieved_announcement(demo_ds, demo_monitor, settings):
    from agents.orchestrator import run_investigation
    rec = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings, scan=demo_monitor.scan, save=False).as_dict()
    g = rec["guidance"]
    assert g["catalyst"]["level"] == "A" and g["catalyst"]["source_type"] == "synthetic_demo"
    assert g["explanation"]["status"] == "verified" and "synthetic demonstration" in g["explanation"]["status_text"]
    assert g["action"]["kind"] == "align_timing" and "before the session opened" in g["action"]["why"]
    entry = [a for a in rec["audit"] if a["name"] == "Action guidance"][0]          # the decision is audited
    assert entry["output"]["catalyst_source_id"] == g["catalyst"]["source_id"]
    assert rec["audit"][-1]["name"] == "Final report"


def test_designed_demo_cases_get_different_actions(demo_ds, demo_monitor, settings):
    from agents.orchestrator import run_investigation
    kinds = {}
    for eid in ("GHATMTR.DEMO:2026-07-02", "GRIDSTAR.DEMO:2026-08-03", "MONSOON.DEMO:2026-09-25"):
        rec = run_investigation(eid, demo_ds, settings, scan=demo_monitor.scan, save=False).as_dict()
        kinds[eid] = rec["guidance"]["action"]["kind"]
        steps = " ".join(rec["guidance"]["action"]["steps"])
        assert "nseindia" not in steps and ("NSE" not in steps or "not possible here" in steps)   # fictional firms
    assert kinds == {"GHATMTR.DEMO:2026-07-02": "confirm_market_move",
                     "GRIDSTAR.DEMO:2026-08-03": "confirm_sector_move",
                     "MONSOON.DEMO:2026-09-25": "investigate_volume"}


def test_saved_records_without_guidance_can_be_rebuilt(sector_tie):
    """Reports saved before this change have no guidance field; the same function rebuilds it from the record."""
    assert build_guidance(sector_tie) == build_guidance(copy.deepcopy(sector_tie))


def test_summary_tab_renders_an_unresolved_live_case_in_business_order():
    """The Summary tab for the reported unresolved case: A to E in order, the tie explained, numbers collapsed."""
    from streamlit.testing.v1 import AppTest

    def page():
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path.cwd() / "tests"))
        import test_guidance as t
        from agents.guidance import build_guidance
        from ui.pages.investigate import _render_summary
        rec = t._record(leading="H5", inconclusive=True, confidence="Low",
                        scores={"H2": 75, "H3": 70, "H1": 40, "H4": 10, "H5": 30},
                        inputs=t.SECTOR_TIE_INPUTS, news=[t.COMPANY_HEADLINE])
        _render_summary(rec, build_guidance(rec))

    at = AppTest.from_function(page, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    order = [html.index(q) for q in ("A. What happened?", "B. What is the most plausible explanation?",
                                     "C. Recommended next action", "D. What remains unknown?")]
    assert order == sorted(order)
    assert "ms-status unresolved" in html and "Potential catalyst - not yet verified" in html
    assert "Example Business Daily" in html and "https://news.example.com/testco-q1" in html
    md = " ".join(str(m.value) for m in at.markdown)
    assert "Two explanations remain plausible" in md and "sector-wide movement" in md
    assert "If found: a company disclosure inside the window strengthens the company explanation" in md
    assert [e.label for e in at.expander][-1] == "E. Quantitative evidence and methodology"
    assert at.expander[-1].proto.expanded is False                     # technical detail is collapsed by default
    assert "robust z" not in html.split("D. What remains unknown?")[0].lower()    # no jargon in A to C


def _headline(sid, publisher, hour, text, **kw):
    return dict(COMPANY_HEADLINE, source_id=sid, publisher=publisher, headline=text,
                published_at=f"2026-10-13T0{hour}:00:00+00:00", url=f"https://news.example.com/{sid}", **kw)


def test_routine_data_note_does_not_hide_the_real_next_action(sector_tie):
    """Real HCL record, 20 Oct: a zero-volume day elsewhere in the history made data validation the 'next action'."""
    rec = copy.deepcopy(sector_tie)
    note = "Volume missing on 0 day(s) and zero on 2 day(s); abnormal-volume tests skip those days."
    rec["rubric"]["inputs"]["data_quality_warnings"] = [note]
    rec["validation"]["data_quality_issues"] = [note]
    g = build_guidance(rec)
    assert g["action"]["kind"] == "separate_explanations"
    assert any(note in lim for lim in g["action"]["limitations"])          # still disclosed, as a limitation
    rec["validation"]["data_quality_issues"] = [
        "Single-day moves of 25% or more on: 2026-10-13. For a large Indian company this usually means a corporate "
        "action the provider did not adjust (bonus issue, split, demerger) or a data error."]
    assert build_guidance(rec)["action"]["kind"] == "validate_data"        # a gap on the event day is material


def test_best_corroborated_subject_beats_an_earlier_single_mismatch(earnings_headline):
    """Real ITC record, 20 Oct: the earliest 'direct' headline was about another firm's tax 'ITC demand'."""
    rec = copy.deepcopy(earnings_headline)
    rec["news"] = [
        _headline("n1", "Example Wire", 1, "Peerco gets favourable order setting aside ₹1.79 crore Testco demand"),
        _headline("n2", "Example Daily", 3, "Testco takes full control of Snackco in Rs 645 crore deal"),
        _headline("n3", "Example Business", 4, "Testco acquires remaining stake in Snackco"),
        _headline("n4", "Facebook", 2, "Testco deal news!! stake buy"),
        _headline("n5", "Instagram", 2, "Testco acquired Snackco stake"),
        _headline("n6", "Example Markets", 5, "Testco shares rise after Snackco acquisition"),
    ]
    cat = build_guidance(rec)["catalyst"]
    assert cat["category"] == "a deal, stake sale or merger" and cat["source_id"] == "n2"
    assert cat["independent_publishers"] == ["Example Business", "Example Daily", "Example Markets"]   # no social posts
    assert "2 other publisher(s)" in cat["statement"]


def test_forecast_pages_and_tips_never_lead(earnings_headline):
    rec = copy.deepcopy(earnings_headline)
    rec["news"] = [_headline("t1", "Share Price Target", 1, "Testco Share Price Target 2026, 2027, 2030, 2040"),
                   _headline("t2", "Example Business", 4, "Testco jumps 5% as broker upgrades rating, target")]
    g = build_guidance(rec)
    assert g["catalyst"]["source_id"] == "t2" and g["catalyst"]["category"] == "a broker rating change"
    a = g["action"]
    assert a["kind"] == "verify_rating_change" and "analyst's opinion" in a["why"]
    assert "Open the article (Example Business)" in a["steps"][0]


def test_action_wording_reads_correctly_for_every_category(earnings_headline):
    from agents.guidance import CATEGORY_NOUN, CATEGORY_WORDS
    assert set(CATEGORY_NOUN) == {label for label, _ in CATEGORY_WORDS}
    for text in ("Testco wins Rs 900 crore contract from state utility", "Testco Q2 net profit rises 12%",
                 "Testco CEO resigns with immediate effect", "SEBI issues show cause notice to Testco"):
        rec = copy.deepcopy(earnings_headline)
        rec["news"] = [_headline("w1", "Example Daily", 3, text)]
        primary = build_guidance(rec)["action"]["primary"]
        assert not re.search(r"\b(the reported|the) (a|an)\b", primary), primary
        assert primary.startswith("Verify the reported ")
