"""Interface smoke tests: every page renders in demonstration mode and an investigation can be run from the UI."""
import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

HARNESS = str(Path(__file__).parent / "page_harness.py")
PAGES = ["overview", "monitor", "investigate", "replay", "risk_lab", "methodology"]


@pytest.mark.parametrize("page", PAGES)
def test_page_renders_without_errors(page, monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", page)
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]


def test_investigation_runs_from_the_workspace(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "investigate")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    [b for b in at.button if b.label == "Run investigation"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    rec = at.session_state["current_record"]
    assert rec["rubric"]["leading_label"] and len(rec["audit"]) > 10
    assert rec["event"]["event_id"] == "SAFFRON.DEMO:2026-09-30"    # most recent high-priority alert is preselected
    assert rec["saved_to"]
    assert [t.label for t in at.tabs][:6] == ["Summary", "Evidence", "Hypotheses", "Risk", "Audit trail", "Export"]
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert "Rule-based protocol" in html and "LLM-directed" not in html    # the engine is named, never overstated
    captions = " ".join(str(c.value) for c in at.caption)
    assert "No model decisions to show" in captions


def test_demo_mode_is_always_labelled(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "overview")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    def text_of(el):
        value = getattr(el, "value", "") or ""
        if not value and getattr(el, "proto", None) is not None:
            value = getattr(el.proto, "body", "") or ""
        return str(value)

    html = " ".join(text_of(h) for h in at.get("html"))
    assert "Demonstration mode" in html and "synthetic" in html


def test_hosted_secrets_configure_the_app_and_the_key_is_never_shown(monkeypatch):
    """Streamlit Community Cloud passes settings as secrets; the app copies them into its environment."""
    monkeypatch.setenv("MS_TEST_PAGE", "investigate")
    monkeypatch.delenv("MS_DEFAULT_MODE", raising=False)
    for name in ("ANTHROPIC_API_KEY", "LLM_MODEL"):
        monkeypatch.setenv(name, "placeholder")     # registers the variable so it is removed again after the test
        monkeypatch.delenv(name)
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.secrets["MS_DEFAULT_MODE"] = "demo"
    at.secrets["ANTHROPIC_API_KEY"] = "sk-test-not-a-real-key-123"
    at.secrets["LLM_MODEL"] = "claude-sonnet-5-5"
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    shown = " ".join(str(getattr(e, "value", "")) for e in list(at.caption) + list(at.markdown)) + " ".join(
        str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert "Demonstration mode" in shown                                  # mode taken from the secrets
    assert "claude-sonnet-5-5 via Anthropic API" in shown                 # LLM configured from the secrets
    assert "sk-test-not-a-real-key" not in shown                          # the key itself is never displayed


def test_replay_offers_the_designed_scenarios_immediately(monkeypatch):
    """The demo replay lists the planted scenarios and can open one as of its own day, without a live alert."""
    monkeypatch.setenv("MS_TEST_PAGE", "replay")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    pick = [s for s in at.selectbox if s.label == "Scenario to investigate"][0]
    assert len(pick.options) >= 6
    assert any("2026-09-30" in o or "30 Sep 2026" in o for o in pick.options)


def test_risk_lab_shows_rupees(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "risk_lab")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    labels = [n.label for n in at.number_input]
    assert any("₹" in label for label in labels) and not any("USD" in label for label in labels)
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    captions = " ".join(str(c.value) for c in at.caption)
    assert "₹1,00,00,000" in captions and "USD" not in html


@pytest.mark.parametrize("page", PAGES)
def test_pages_show_no_us_market_terms(page, monkeypatch):
    """What the audience sees in the default workflow: no US source, currency or benchmark anywhere."""
    monkeypatch.setenv("MS_TEST_PAGE", page)
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    parts = [str(getattr(e, "value", "")) for e in list(at.markdown) + list(at.caption) + list(at.info)]
    parts += [str(getattr(h.proto, "body", "")) for h in at.get("html")]
    parts += [e.value.to_string() for e in at.dataframe]
    parts += [str(t.label) for t in at.tabs] + [str(n.label) for n in at.number_input] + [str(s.label) for s in at.slider]
    text = " ".join(parts)
    for token in ("SEC EDGAR", "8-K", "SPDR", "S&P 500", "New York", "Wall Street", "USD", "sector fund", "ETF"):
        assert token not in text, (page, token)
