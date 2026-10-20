"""End-to-end workflow on the deterministic demonstration dataset (rule-based engine)."""
import pandas as pd
import pytest

from agents.orchestrator import STAGES, list_records, run_investigation, stage_progress
from reports.report_builder import build_html, build_markdown

SECTIONS = ["## 1. Executive summary", "## 2. Security, event date and data timestamps", "## 3. What was observed",
            "## 4. Why the event triggered an alert", "## 5. Price and volume evidence",
            "## 6. Benchmark and peer comparison", "## 7. Relevant public news and announcements",
            "## 8. Competing hypotheses", "## 9. Evidence for and against each hypothesis",
            "## 10. Confidence assessment", "## 11. Potential risk implications", "## 12. What remains unknown",
            "## 13. Recommended next action", "## 14. Investigation timeline and tool calls"]


def test_full_report_has_all_fourteen_sections(demo_ds, demo_monitor, settings):
    rec = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings, scan=demo_monitor.scan, save=False)
    md = build_markdown(rec.as_dict())
    for s in SECTIONS:
        assert s in md, s
    assert "SYNTHETIC DEMONSTRATION DATA" in md
    assert "IST" in md                                                  # times are shown in India time
    assert "(UTC)" not in md and "USD" not in md and "SEC" not in md
    html = build_html(rec.as_dict())
    assert html.startswith("<!doctype html>") and "<table>" in html
    assert set(stage_progress(rec.audit).values()) == {"done"}
    assert rec.engine["investigator"] == "rules" and "Rule-based" in rec.engine["summary"]


@pytest.mark.parametrize("which,expected", [
    ("market", "H1"),                          # broad market fall (63 sessions before the end)
    ("energy", "H2"),                          # oil, gas and power stocks rise together
    ("SAFFRON.DEMO:2026-09-30", "H3"),         # bank falls after results declared the previous evening
    ("IRONBRG.DEMO:2026-09-17", "H3"),         # engineering company wins a large order
    ("CURELINE.DEMO:2026-08-28", "H4"),        # isolated fall with no supporting news
    ("MONSOON.DEMO:2026-09-25", "H4"),         # IT company volume spike with no announcement
])
def test_designed_scenarios_reach_the_intended_explanation(which, expected, demo_ds, demo_monitor, settings):
    cal = demo_monitor.scan.panel.calendar
    ev = demo_monitor.events
    if which == "market":
        event_id = ev[ev["date"] == cal[-1 - 63]].sort_values("priority_score").iloc[-1]["event_id"]
    elif which == "energy":
        event_id = ev[(ev["date"] == cal[-1 - 41]) & (ev["sector"] == "Oil, gas & power")].iloc[0]["event_id"]
    else:
        event_id = which
    rec = run_investigation(event_id, demo_ds, settings, scan=demo_monitor.scan, save=False)
    assert rec.rubric["leading"] == expected, (event_id, rec.rubric["results"])
    assert not rec.rubric["inconclusive"]


def test_news_unavailable_is_stated_and_limits_conclusions(demo_ds, demo_monitor, settings, monkeypatch):
    from providers.news_data import NewsSearchResult, ProviderStatus, NewsService

    def broken(self, ticker, event_date, **kwargs):
        r = NewsSearchResult(ticker=ticker, event_date=str(event_date), window_start="", window_end="", cutoff=None)
        # Regression: the link-only entry for the official NSE/BSE pages is not a search, so it must not hide
        # the failure of both news providers (it did before the fix in agents/context.py).
        r.statuses = [ProviderStatus("Google News RSS (India edition)", "failed", "ConnectionError"),
                      ProviderStatus("Yahoo Finance headlines (yfinance)", "failed", "ConnectionError"),
                      ProviderStatus("NSE/BSE official disclosures (link-only)", "link_only", "manual check")]
        return r

    monkeypatch.setattr(NewsService, "search", broken)
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings, scan=demo_monitor.scan, save=False)
    md = build_markdown(rec.as_dict())
    assert "News evidence unavailable" in md
    scores = {r["id"]: r for r in rec.rubric["results"]}
    assert scores["H4"]["score"] <= 40 and scores["H3"]["score"] <= 50
    assert rec.rubric["confidence"] in ("Low", "Moderate")


def test_investigation_is_saved_to_history(demo_ds, demo_monitor, settings):
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings, scan=demo_monitor.scan, save=True)
    rows = list_records()
    assert any(r["record_id"] == rec.record_id for r in rows)


def test_history_hides_records_from_the_us_version(demo_ds, demo_monitor, settings):
    """Old US-market records stay on disk but are not listed in the India app."""
    import json
    from agents import orchestrator
    old = orchestrator.HISTORY_DIR / "BAC_2026-10-14_old.json"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text(json.dumps({"record_id": "BAC_old", "event": {"event_id": "BAC:2026-10-14"},
                               "data": {"mode": "live"}}), encoding="utf-8")
    run_investigation("MONSOON.DEMO:2026-09-25", demo_ds, settings, scan=demo_monitor.scan, save=True)
    ids = [r["record_id"] for r in list_records()]
    assert "BAC_old" not in ids and old.exists()


def test_reports_differ_between_events(demo_ds, demo_monitor, settings):
    a = run_investigation("IRONBRG.DEMO:2026-09-17", demo_ds, settings, scan=demo_monitor.scan, save=False)
    b = run_investigation("MONSOON.DEMO:2026-09-25", demo_ds, settings, scan=demo_monitor.scan, save=False)
    assert a.investigator["summary"] != b.investigator["summary"]
    assert a.rubric["leading"] != b.rubric["leading"]


def test_unknown_event_raises_clear_error(demo_ds, demo_monitor, settings):
    from agents.orchestrator import InvestigationError
    with pytest.raises(InvestigationError):
        run_investigation("NOPE.DEMO:2020-01-01", demo_ds, settings, scan=demo_monitor.scan, save=False)


def _crafted_news(publishers):
    from providers.news_data import NewsItem, NewsSearchResult, ProviderStatus

    def search(self, ticker, event_date, **kwargs):
        r = NewsSearchResult(ticker=ticker, event_date=str(event_date), window_start="", window_end="", cutoff=None)
        r.items = [NewsItem(source_id=f"T-{i}", headline=f"{ticker} shares fall after profit warning", publisher=p,
                            provider="Google News RSS", source_type="news_headline", timing="in_window",
                            relevance="direct", relevance_rationale="test", mentions_company=True)
                   for i, p in enumerate(publishers)]
        r.statuses = [ProviderStatus("Google News RSS (India edition)", "ok", f"{len(r.items)} headline(s)")]
        return r
    return search


@pytest.mark.parametrize("publishers,leading,h3_points", [
    ([], "H4", -15),                                   # searched, nothing direct
    (["Example Business Daily"], "H3", 20),            # one headline, one source: weaker evidence
    (["Example Business Daily", "Sample Markets"], "H3", 40),   # independent sources
])
def test_single_headline_counts_less_than_independent_sources(publishers, leading, h3_points, demo_ds, demo_monitor,
                                                              settings, monkeypatch):
    from providers.news_data import NewsService
    monkeypatch.setattr(NewsService, "search", _crafted_news(publishers))
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings, scan=demo_monitor.scan, save=False)
    h3 = next(r for r in rec.rubric["results"] if r["id"] == "H3")
    crit = next(c for c in h3["criteria"] if c["name"] == "Direct company evidence in the information window")
    assert crit["points"] == h3_points
    top = max((r for r in rec.rubric["results"] if r["id"] != "H5"), key=lambda r: r["score"])
    assert top["id"] == leading


def test_stock_outside_the_illustrative_portfolio_is_handled(demo_ds, demo_monitor, settings):
    rec = run_investigation("MONSOON.DEMO:2026-09-25", demo_ds, settings, scan=demo_monitor.scan, save=False)
    assert rec.evidence["get_portfolio_exposure"]["holding_weight"] == 0
    scenarios = [s["scenario"] for s in rec.evidence["run_stress_scenario"]]
    assert scenarios and not any(s.startswith("MONSOON.DEMO moves") for s in scenarios)   # sector shock instead
    assert "not held in the illustrative portfolio" in rec.strategist["executive_summary"]
    md = build_markdown(rec.as_dict())
    assert "-0.00%" not in md and "not held" in md
    lines = {a["name"]: a["summary"] for a in rec.as_dict()["audit"] if a["kind"] == "tool_call"}
    assert lines["get_portfolio_exposure"].startswith("Not held; sector weight")
    assert "before the event" in lines["get_risk_metrics"] and "including it" in lines["get_risk_metrics"]


def test_held_stock_activity_lines_show_weight(demo_ds, demo_monitor, settings):
    rec = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings, scan=demo_monitor.scan, save=False)
    weight = rec.evidence["get_portfolio_exposure"]["holding_weight"]
    lines = {a["name"]: a["summary"] for a in rec.as_dict()["audit"] if a["kind"] == "tool_call"}
    assert weight > 0 and lines["get_portfolio_exposure"].startswith(f"Weight {weight:.1%}")
    risk = rec.evidence["get_risk_metrics"]
    assert f"{risk['hist_var_1d_before_event']:.2%} before the event" in lines["get_risk_metrics"]


def test_demo_announcement_keeps_publication_and_event_dates_apart(demo_ds, demo_monitor, settings):
    """The fictional results were approved at a board meeting and published after market hours the evening
    before the move: the record keeps the publication time and the stated event date separately."""
    rec = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings, scan=demo_monitor.scan, save=False)
    item = next(n for n in rec.news if n["source_type"] == "synthetic_demo")
    assert item["published_at"] == "2026-09-29T12:35:00+00:00"          # 18:05 IST on 29 Sep
    assert item["event_date"] == "2026-09-29" and item["timing"] == "in_window"
    assert "fictional" in item["headline"].lower()
    md = build_markdown(rec.as_dict())
    assert "29 Sep 2026, 18:05 IST" in md and "event date stated by the source" in md


def test_record_carries_indian_market_facts(demo_ds, demo_monitor, settings):
    rec = run_investigation("IRONBRG.DEMO:2026-09-17", demo_ds, settings, scan=demo_monitor.scan, save=False)
    assert rec.data["timezone"] == "Asia/Kolkata" and rec.data["currency"] == "INR"
    assert "15:30" in rec.data["session"]
    assert rec.official_links == []                                     # fictional companies have no NSE filings
    peers = rec.evidence["compare_with_peers"]
    assert peers["sector_index"] is None                                # capital goods has no sector index
    assert any("no separate sector-index comparison" in n for n in peers["notes"])
    # Regression: a group without a sector index is a design limit, not missing data, so it must not cap the
    # confidence of every stock in that group at Moderate (it did before the India conversion).
    assert "z_sector" not in rec.rubric["confidence_explanation"] and rec.rubric["confidence"] == "High"


def test_news_switched_off_counts_as_not_searched(demo_ds, demo_monitor, monkeypatch):
    """With news disabled nothing is searched, so 'no public explanation found' must not earn points."""
    from dataclasses import replace

    from config.settings import AnalysisConfig, DataConfig, LLMConfig, Settings
    from providers.market_data import MarketDataset
    off = Settings(analysis=AnalysisConfig(), data=DataConfig(news_enabled=False), llm=LLMConfig(provider="none"))
    live_like: MarketDataset = replace(demo_ds, mode="live")             # live path, news switched off
    rec = run_investigation("CURELINE.DEMO:2026-08-28", live_like, off, scan=demo_monitor.scan, save=False)
    h4 = next(r for r in rec.rubric["results"] if r["id"] == "H4")
    crit = next(c for c in h4["criteria"] if c["name"] == "No public explanation found despite searching")
    assert crit["effect"] == "missing" and h4["score"] <= 40
