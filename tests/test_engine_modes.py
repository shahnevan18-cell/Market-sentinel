"""Engine selection, Gemini configuration, hosted secrets, the connection test and honest engine labels.

Added for the 20 Oct 2026 runtime fix. No real API is called: provider responses are scripted, and the key used here
is a fake string shaped like a Google key so the redaction checks are meaningful.
"""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from agents.orchestrator import run_investigation
from config.settings import GEMINI_BASE_URL, LLMConfig, load_llm_config
from providers import llm as llm_mod
from providers.llm import LLMError, LLMTurn, ToolCall, classify_error, describe_error, probe, quota_reset_ist, redact
from reports.report_builder import build_markdown
from tests.test_llm_validation import ScriptedBackend, good_investigator, good_strategist

FAKE_KEY = "AIza" + "Q7fakeKEYforTESTSonly0123456789ab"
HARNESS = str(Path(__file__).parent / "page_harness.py")


class GeminiScripted(ScriptedBackend):
    """Scripted conversation behind a Gemini-shaped configuration (model, endpoint and key source)."""

    def __init__(self, inv, strat):
        super().__init__(inv, strat)
        self.cfg = LLMConfig(provider="openai_compatible", model="gemini-3.5-flash", api_key=FAKE_KEY,
                             base_url=GEMINI_BASE_URL, vendor="Google Gemini", key_source="GEMINI_API_KEY")

    @property
    def label(self):
        return self.cfg.describe()


def raises(message):
    def model(conv):
        raise LLMError(message)
    return model


def invalid_submitter(conv):
    return LLMTurn(text="", tool_calls=[ToolCall(f"s{conv.turn}", "submit_investigation", {"summary": 7})])


def silent_model(conv):
    return LLMTurn(text="I think the move was news-driven.", tool_calls=[])


def bad_args_then_good(conv):
    """First asks for a tool with an argument the schema rejects, then behaves."""
    if conv.turn == 1:
        return LLMTurn(text="", tool_calls=[ToolCall("x1", "list_news_items", {"timing": "next week"})])
    return good_investigator(_Shifted(conv))


class _Shifted:
    """Presents turn n+1 as turn n so a scripted investigator can start one turn later."""

    def __init__(self, conv):
        self._conv = conv

    def __getattr__(self, name):
        return getattr(self._conv, name)

    @property
    def turn(self):
        return self._conv.turn - 1


class _BrokenNews:
    def search(self, *a, **k):
        raise RuntimeError("news provider exploded")


def _run(demo_ds, demo_monitor, settings, backend=None, event="CURELINE.DEMO:2026-08-28", **kw):
    return run_investigation(event, demo_ds, settings, backend=backend, scan=demo_monitor.scan, save=False, **kw)


def _engine_entry(rec):
    return [a for a in rec.audit if a["name"] == "Engine selection"][0]


# --- Configuration -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("env,model,source", [
    ({"GEMINI_API_KEY": FAKE_KEY}, "gemini-3.5-flash", "GEMINI_API_KEY"),
    ({"GOOGLE_API_KEY": FAKE_KEY}, "gemini-3.5-flash", "GOOGLE_API_KEY"),
    ({"LLM_API_KEY": FAKE_KEY}, "gemini-3.5-flash", "LLM_API_KEY"),
    ({"LLM_PROVIDER": "gemini", "GEMINI_API_KEY": FAKE_KEY, "LLM_MODEL": "gemini-3.5-pro"}, "gemini-3.5-pro",
     "GEMINI_API_KEY"),
    ({"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": FAKE_KEY, "LLM_MODEL": "gemini-3.5-flash",
      "LLM_BASE_URL": GEMINI_BASE_URL}, "gemini-3.5-flash", "LLM_API_KEY"),      # the laptop's .env style
])
def test_gemini_is_enabled_by_any_supported_setup(monkeypatch, env, model, source):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = load_llm_config()
    assert cfg.enabled and cfg.is_gemini and cfg.model == model and cfg.key_source == source
    assert cfg.base_url == GEMINI_BASE_URL and cfg.vendor == "Google Gemini"
    assert FAKE_KEY not in repr(cfg) and FAKE_KEY not in cfg.status_text()
    assert cfg.status_text().startswith("Configured: ")


@pytest.mark.parametrize("env,expect", [
    ({}, "No LLM credentials are configured"),
    ({"LLM_PROVIDER": "gemini"}, "no key was found"),
    ({"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": FAKE_KEY}, "LLM_MODEL is not set"),
    ({"LLM_PROVIDER": "mistral", "LLM_API_KEY": FAKE_KEY}, "not supported"),
    ({"LLM_PROVIDER": "none", "GEMINI_API_KEY": FAKE_KEY}, "switched off"),
    ({"GEMINI_API_KEY": FAKE_KEY, "LLM_MODEL": "claude-sonnet-5-5"}, "an Anthropic model"),
])
def test_unusable_settings_are_explained_not_silently_ignored(monkeypatch, env, expect):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    cfg = load_llm_config()
    assert not cfg.enabled
    assert expect in cfg.status_text() and FAKE_KEY not in cfg.status_text()


# --- Hosted secrets ----------------------------------------------------------------------------------------

def test_secrets_are_copied_lifted_and_updated(monkeypatch):
    from ui import state
    for k in ("GEMINI_API_KEY", "LLM_MODEL", "MS_LLM_PASSCODE", "MS_DEFAULT_MODE"):
        monkeypatch.setenv(k, "")       # recorded, so values set by the code under test are removed afterwards
        monkeypatch.delenv(k)
    monkeypatch.setattr(state, "_SECRET_COPIES", {})
    rep = state._secrets_to_env({"gemini_api_key": FAKE_KEY + " ", "MS_DEFAULT_MODE": "live",
                                 "llm": {"LLM_MODEL": "gemini-3.5-flash"}, "other_service_token": "abc"})
    import os
    assert os.environ["GEMINI_API_KEY"] == FAKE_KEY                          # lower case lifted, whitespace removed
    assert os.environ["LLM_MODEL"] == "gemini-3.5-flash"                     # found inside a table
    assert sorted(rep["names"]) == ["GEMINI_API_KEY", "LLM_MODEL", "MS_DEFAULT_MODE"]
    assert rep["other_count"] == 1 and "other_service_token" not in os.environ
    assert FAKE_KEY not in json.dumps(rep)                                   # names only, never values
    state._secrets_to_env({"GEMINI_API_KEY": "AIza" + "B" * 35})              # an edited secret replaces the old copy
    assert os.environ["GEMINI_API_KEY"] == "AIza" + "B" * 35
    monkeypatch.setenv("LLM_MODEL", "set-by-the-host")                       # set outside the secrets: left alone
    rep = state._secrets_to_env({"LLM_MODEL": "gemini-3.5-flash"})
    assert os.environ["LLM_MODEL"] == "set-by-the-host" and "also set outside" in " ".join(rep["notes"])


def test_unreadable_secrets_are_reported_without_their_content():
    from ui import state

    class Broken:
        def items(self):
            raise ValueError(f'Invalid value on line 1: GEMINI_API_KEY = {FAKE_KEY}')

    rep = state._secrets_to_env(Broken())
    assert rep["error"] and "ValueError" in rep["error"] and "needs quotes" in rep["error"]
    assert FAKE_KEY not in rep["error"]


# --- Connection test ---------------------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._data, self.text, self.headers = status, data, text or json.dumps(data or {}), {}

    def json(self):
        return self._data


def _gemini_cfg():
    return LLMConfig(provider="openai_compatible", model="gemini-3.5-flash", api_key=FAKE_KEY,
                     base_url=GEMINI_BASE_URL, vendor="Google Gemini", key_source="GEMINI_API_KEY")


def test_probe_reports_a_real_tool_call(monkeypatch):
    import requests
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append((url, json))
        return _Resp(200, {"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "report_ready", "arguments": '{"status": "ready"}'}}]}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 5}})

    monkeypatch.setattr(requests, "post", fake_post)
    out = probe(_gemini_cfg())
    assert out["ok"] and out["tool_called"] and out["requests"] == 1 and out["model"] == "gemini-3.5-flash"
    assert len(sent) == 1 and sent[0][0].startswith(GEMINI_BASE_URL)


@pytest.mark.parametrize("status,body,category", [
    (400, f"API key not valid. Please pass a valid API key. key={FAKE_KEY}", "invalid_credentials"),
    (401, "Unauthenticated", "invalid_credentials"),
    (429, "Quota exceeded for metric: GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quota_daily"),
    (503, "The model is overloaded. Please try again later.", "provider_busy"),
    (404, "models/gemini-9 is not found", "model_not_found"),
])
def test_probe_classifies_provider_errors_and_hides_the_key(monkeypatch, status, body, category):
    import requests
    monkeypatch.setattr(requests, "post", lambda *a, **k: _Resp(status, None, body))
    out = probe(_gemini_cfg())
    assert not out["ok"] and out["category"] == category
    assert FAKE_KEY not in json.dumps(out)


def test_probe_timeout_and_unconfigured(monkeypatch):
    import requests

    def slow(*a, **k):
        raise requests.exceptions.ReadTimeout("Read timed out. (read timeout=30)")

    monkeypatch.setattr(requests, "post", slow)
    out = probe(_gemini_cfg())
    assert not out["ok"] and out["category"] == "timeout"
    none = probe(LLMConfig())
    assert none["requests"] == 0 and none["category"] == "not_configured"


def test_quota_reset_is_midnight_pacific_shown_in_ist():
    from datetime import datetime, timezone
    before = quota_reset_ist(datetime(2026, 10, 20, 16, 51, tzinfo=timezone.utc))   # 22:21 IST, US on daylight time
    assert (before.year, before.month, before.day, before.hour, before.minute) == (2026, 10, 21, 12, 30)
    winter = quota_reset_ist(datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc))      # US on standard time
    assert (winter.hour, winter.minute) == (13, 30)
    assert "IST" in describe_error("quota_daily")


# --- Engine modes in the record ----------------------------------------------------------------------------

def test_model_directed_run_is_labelled_with_model_and_key_source(demo_ds, demo_monitor, settings):
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(good_investigator, good_strategist),
               event="IRONBRG.DEMO:2026-09-17")
    eng = rec.engine
    assert eng["mode"] == "llm" and eng["llm_attempted"] and eng["model"] == "gemini-3.5-flash"
    assert eng["key_source"] == "GEMINI_API_KEY" and "directed the investigation" in eng["mode_text"]
    sel = _engine_entry(rec)
    assert sel["output"]["engine"] == "llm" and sel["output"]["endpoint_host"] == "generativelanguage.googleapis.com"
    turns = [a for a in rec.audit if a["kind"] == "llm_turn"]
    assert turns and all(t["output"]["model"] == "gemini-3.5-flash" for t in turns)
    ran = [a for a in rec.audit if a["kind"] == "tool_call" and a["actor"] == "Market Investigator"]
    assert ran and all(a["status"] == "ok" for a in ran)            # tools the model requested actually ran


@pytest.mark.parametrize("message,category", [
    (f"LLM provider returned HTTP 400: API key not valid. key={FAKE_KEY}", "invalid_credentials"),
    ("LLM provider returned HTTP 429: the daily request quota is used up, so waiting would not help. Detail: "
     "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quota_daily"),
    ("Network error calling the LLM provider: ReadTimeout: Read timed out. (read timeout=240)", "timeout"),
    ("LLM provider returned HTTP 503: The model is overloaded.", "provider_busy"),
])
def test_provider_errors_fall_back_and_say_why(demo_ds, demo_monitor, settings, message, category):
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(raises(message), raises(message)))
    eng = rec.engine
    assert eng["mode"] == "llm_provider_fallback" and eng["llm_attempted"]
    assert eng["error_categories"][0] == category and "provider returned an error" in eng["mode_text"]
    assert rec.investigator["summary"]                                  # the rule-based protocol finished the run
    calls = [a for a in rec.audit if a["name"] == "llm_call"]
    assert calls and calls[0]["output"]["error_category"] == category
    everything = json.dumps(rec.as_dict()) + build_markdown(rec.as_dict())
    assert FAKE_KEY not in everything


def test_fallback_runs_each_required_check_once_and_forces_none(demo_ds, demo_monitor, settings):
    """When the first model call fails, the rule-based fallback does the checks; the orchestrator must not run them
    first as if the investigator had skipped them, and nothing is run twice."""
    from agents.market_investigator import REQUIRED_TOOLS
    message = "Network error calling the LLM provider: ConnectionError: unreachable"
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(raises(message), raises(message)))
    assert not [a for a in rec.audit if a["actor"] == "Orchestrator" and a["kind"] == "tool_call"]
    assert not any("skipped" in w for w in rec.warnings)
    for name in REQUIRED_TOOLS:
        runs = [a for a in rec.audit if a["kind"] == "tool_call" and a["name"] == name and a["status"] == "ok"]
        assert len(runs) == 1 and runs[0]["actor"] == "Market Investigator (rule-based fallback)", name


def test_invalid_model_output_is_a_model_failure_not_a_provider_error(demo_ds, demo_monitor, settings):
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(invalid_submitter, invalid_submitter))
    assert rec.engine["mode"] == "llm_failed" and rec.engine["error_categories"][0] == "invalid_output"
    assert "could not be used" in rec.engine["mode_text"]


def test_model_that_stops_using_tools_falls_back(demo_ds, demo_monitor, settings):
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(silent_model, silent_model))
    assert rec.engine["mode"] == "llm_failed" and rec.engine["error_categories"][0] == "no_tool_call"


def test_invalid_tool_arguments_go_back_to_the_model(demo_ds, demo_monitor, settings):
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(bad_args_then_good, good_strategist))
    bad = [a for a in rec.audit if a["name"] == "list_news_items"]
    assert bad and bad[0]["status"] == "error"                          # rejected by the schema, not executed
    assert rec.engine["mode"] == "llm"                                  # the model recovered and submitted


def test_a_failing_tool_is_reported_and_the_model_continues(demo_ds, demo_monitor, settings):
    rec = _run(demo_ds, demo_monitor, settings, GeminiScripted(good_investigator, good_strategist),
               event="IRONBRG.DEMO:2026-09-17", news_service=_BrokenNews())
    news = [a for a in rec.audit if a["name"] == "search_public_news"]
    assert news and news[0]["status"] == "error"
    assert rec.engine["investigator"] == "llm" and rec.engine["mode"] == "llm"


def test_mixed_run_is_named(demo_ds, demo_monitor, settings):
    rec = _run(demo_ds, demo_monitor, settings,
               GeminiScripted(good_investigator, raises("LLM provider returned HTTP 503: overloaded")),
               event="IRONBRG.DEMO:2026-09-17")
    assert rec.engine["mode"] == "mixed" and "risk step fell back" in rec.engine["mode_text"]


@pytest.mark.parametrize("reason,mode,phrase", [
    ("selected", "rules_selected", "selected by the user"),
    (None, "rules_no_credentials", "no LLM credentials"),
    ("locked", "rules_locked", "passcode"),
    ("config_problem", "rules_config_problem", "could not be used"),
])
def test_rule_based_runs_say_why_no_model_ran(demo_ds, demo_monitor, settings, reason, mode, phrase):
    rec = _run(demo_ds, demo_monitor, settings, None, rules_reason=reason)
    assert rec.engine["mode"] == mode and not rec.engine["llm_attempted"] and rec.engine["model"] is None
    sel = _engine_entry(rec)
    assert sel["output"]["engine"] == "rules" and phrase in sel["summary"]
    assert not [a for a in rec.audit if a["kind"] == "llm_turn"]        # no model turn is ever invented


def test_error_categories_cover_the_loop_messages():
    assert classify_error("Submission failed validation twice. summary: Input should be a valid string") == "invalid_output"
    assert classify_error("No valid submission within 10 model turns.") == "turn_limit"
    assert classify_error("The model stopped calling tools without submitting structured findings.") == "no_tool_call"
    assert classify_error("Unusable response from the LLM provider (KeyError: 'content')") == "invalid_response"


# --- What the pages show -------------------------------------------------------------------------------------

def test_engine_strip_names_each_mode(demo_ds, demo_monitor, settings):
    from ui.pages.investigate import ENGINE_MODES, _engine_strip, engine_mode
    ok = _run(demo_ds, demo_monitor, settings, GeminiScripted(good_investigator, good_strategist),
              event="IRONBRG.DEMO:2026-09-17").as_dict()
    assert "Model-directed" in _engine_strip(ok) and "gemini-3.5-flash" in _engine_strip(ok)
    failed = _run(demo_ds, demo_monitor, settings, GeminiScripted(raises("LLM provider returned HTTP 401: x"),
                                                                    raises("LLM provider returned HTTP 401: x"))).as_dict()
    assert "provider error" in _engine_strip(failed) and "model called: gemini-3.5-flash" in _engine_strip(failed)
    chosen = _run(demo_ds, demo_monitor, settings, None, rules_reason="selected").as_dict()
    assert "selected in the sidebar" in _engine_strip(chosen)
    legacy = {"engine": {"investigator": "rules (fallback after LLM failure)", "strategist": "rules",
                         "llm_errors": ["HTTP 429"]}}
    assert engine_mode(legacy) == "llm_failed" and set(ENGINE_MODES) >= {"llm", "mixed", "llm_failed",
                                                                         "llm_provider_fallback", "rules_selected"}


def _page_text(at):
    parts = []
    for kind in ("caption", "markdown", "error", "success", "info", "warning", "text"):
        parts += [str(getattr(e, "value", "")) for e in at.get(kind)]
    parts += [str(getattr(h.proto, "body", "")) for h in at.get("html")]
    return " ".join(parts)


def test_sidebar_engine_selector_lock_and_rules_choice(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "investigate")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setenv("MS_LLM_PASSCODE", "correct horse")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    radio = at.radio(key="engine_choice")
    assert radio.options == ["Gemini (model-directed)", "Rule-based protocol"]
    text = _page_text(at)
    assert "asks for a passcode" in text and "because the model is locked" in text
    assert [b for b in at.button if b.label == "Test connection"][0].disabled
    at.text_input(key="llm_passcode_input").input("wrong")          # form values are sent with the submit
    [b for b in at.button if b.label == "Unlock"][0].click().run()
    assert "not right" in _page_text(at) and at.session_state["engine_choice"] == "llm"
    at.text_input(key="llm_passcode_input").input("correct horse")
    [b for b in at.button if b.label == "Unlock"][0].click().run()
    text = _page_text(at)
    assert "Gemini (gemini-3.5-flash) will choose the tools" in text
    assert not [b for b in at.button if b.label == "Test connection"][0].disabled
    at.radio(key="engine_choice").set_value("rules").run()
    assert "rule-based protocol, because selected in the sidebar" in _page_text(at)
    assert FAKE_KEY not in _page_text(at) and "correct horse" not in _page_text(at)


def test_sidebar_connection_test_reports_a_quota_failure_plainly(monkeypatch):
    import ui.state as state
    monkeypatch.setenv("MS_TEST_PAGE", "investigate")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    calls = []

    def fake_probe(cfg):
        calls.append(cfg.model)
        detail = f"LLM provider returned HTTP 429: GenerateRequestsPerDayPerProjectPerModel-FreeTier key={FAKE_KEY}"
        return {"ok": False, "model": cfg.model, "category": "quota_daily", "summary": describe_error("quota_daily"),
                "detail": redact(detail, [FAKE_KEY]), "message": "", "latency_ms": 12, "requests": 1}

    monkeypatch.setattr(state, "probe", fake_probe)
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    [b for b in at.button if b.label == "Test connection"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    errors = " ".join(str(e.value) for e in at.error)
    assert calls == ["gemini-3.5-flash"] and "Connection test failed at" in errors
    assert "daily" in errors and "IST" in errors and "Detail" not in errors        # the short reason, with reset time
    assert any(e.label == "Provider message (key removed)" for e in at.expander)
    assert FAKE_KEY not in _page_text(at)


def test_sidebar_without_credentials_says_so(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "investigate")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception
    text = _page_text(at)
    assert "No LLM credentials are configured" in text and "set GEMINI_API_KEY" in text
    assert "because no LLM credentials are configured on this deployment" in text
    assert "ANTHROPIC_API_KEY (or LLM_API_KEY)" not in text           # the old, misleading instruction is gone


def test_llm_check_probe_option(monkeypatch, capsys):
    from tests.test_agent_robustness import _llm_check_module
    module = _llm_check_module()
    monkeypatch.setenv("GEMINI_API_KEY", FAKE_KEY)
    monkeypatch.setattr(module, "probe", lambda cfg: {"ok": False, "category": "quota_daily",
                                                      "message": describe_error("quota_daily"), "latency_ms": 5})
    monkeypatch.setattr("sys.argv", ["llm_check.py", "--probe"])
    assert module.main() == 1
    out = capsys.readouterr().out
    assert "PROBE FAILED (quota_daily)" in out and "GEMINI_API_KEY" in out and FAKE_KEY not in out
