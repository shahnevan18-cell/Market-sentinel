"""LLM integration logic tested with scripted (fake) models. No real API is called."""
import json

import pytest

from agents.grounding import check_submission, collect_numbers, ungrounded_numbers
from agents.orchestrator import run_investigation
from agents.schemas import InvestigatorSubmission, StrategistSubmission
from agents.tools import AuditLog, ToolRegistry, ToolSpec, validate_arguments
from config.settings import LLMConfig
from providers import llm as llm_mod
from providers.llm import AnthropicConversation, LLMError, LLMTurn, OpenAICompatibleConversation, ToolCall


# --- Tool registry and schemas ----------------------------------------------------------------

def _registry(budget=3):
    spec = ToolSpec("double", "Doubles x", {"type": "object", "properties": {
        "x": {"type": "number", "minimum": 0, "maximum": 100},
        "mode": {"type": "string", "enum": ["a", "b"]}}, "required": ["x"], "additionalProperties": False},
        lambda x, mode="a": {"value": 2 * x}, "Test")
    audit = AuditLog()
    return ToolRegistry([spec], audit, "Tester", budget=budget), audit


def test_unknown_tool_is_rejected_and_audited():
    reg, audit = _registry()
    r = reg.execute("delete_everything", {})
    assert not r.ok and "Unknown tool" in r.error
    assert audit.entries[-1].status == "error" and audit.entries[-1].name == "delete_everything"


def test_invalid_arguments_are_rejected():
    reg, _ = _registry()
    assert "must be a number" in reg.execute("double", {"x": "ten"}).error
    assert "one of" in reg.execute("double", {"x": 1, "mode": "z"}).error
    assert "<= 100" in reg.execute("double", {"x": 1000}).error
    assert "Unknown argument" in reg.execute("double", {"x": 1, "hack": True}).error
    assert "Missing required" in reg.execute("double", {}).error
    assert reg.calls_used == 0                     # invalid calls do not run the function


def test_tool_budget_is_enforced():
    reg, audit = _registry(budget=2)
    assert reg.execute("double", {"x": 1}).data == {"value": 2}
    assert reg.execute("double", {"x": 2}).ok
    third = reg.execute("double", {"x": 3})
    assert not third.ok and "budget" in third.error
    assert audit.entries[-1].status == "skipped"


def test_schema_validator_nested_arrays():
    schema = {"type": "object", "properties": {"items": {"type": "array", "maxItems": 2, "items": {"type": "string"}}},
              "additionalProperties": False}
    assert validate_arguments(schema, {"items": ["a", "b"]}) == []
    assert validate_arguments(schema, {"items": ["a", 1, "c"]})


def test_submission_models_validate():
    ok = InvestigatorSubmission.model_validate({"summary": "A sufficiently long summary of findings.",
                                                "key_findings": ["one"], "unknowns": [], "follow_up_checks": []})
    assert ok.summary
    with pytest.raises(Exception):
        InvestigatorSubmission.model_validate({"summary": "short"})
    with pytest.raises(Exception):
        InvestigatorSubmission.model_validate({"summary": "A sufficiently long summary.", "hypothesis_notes": {"H9": "x"}})
    with pytest.raises(Exception):
        StrategistSubmission.model_validate({"executive_summary": "x"})


def test_grounding_check():
    allowed = collect_numbers({"ret": -0.0902, "z": -6.2, "volume": 36_816_034, "beta": 1.1312})
    assert ungrounded_numbers("Shares fell 9.02% (z -6.2) on 36.8 million shares; beta 1.13; H3 leads.", allowed) == []
    assert ungrounded_numbers("Volume was 3.68 crore shares.", allowed) == []
    assert ungrounded_numbers("Analysts now expect 14.5% upside.", allowed) == ["14.5%"]
    flags = check_submission({"summary": "fell 9.0%", "key_findings": ["a 77.7% jump"]}, allowed)
    assert list(flags) == ["key_findings[0]"]


# --- Scripted model --------------------------------------------------------------------------------

class ScriptedConversation:
    def __init__(self, script, tools):
        self.script = script
        self.tools = [t["name"] for t in tools]
        self.results = []          # list of lists of (id, content, is_error)
        self.turn = 0

    def add_user_text(self, text):
        pass

    def step(self, force_tool=None):
        self.turn += 1
        return self.script(self)

    def add_tool_results(self, results):
        self.results.append(results)

    def last_json(self, call_id):
        for batch in reversed(self.results):
            for cid, content, err in batch:
                if cid == call_id and not err:
                    return json.loads(content)
        return None


class ScriptedBackend:
    def __init__(self, investigator_script, strategist_script):
        self.cfg = LLMConfig(provider="anthropic", model="scripted-test-model", api_key="test")
        self.inv = investigator_script
        self.strat = strategist_script
        self.conversations = []

    @property
    def label(self):
        return "scripted-test-model via test harness"

    def start(self, system, tools):
        names = {t["name"] for t in tools}
        conv = ScriptedConversation(self.inv if "submit_investigation" in names else self.strat, tools)
        self.conversations.append(conv)
        return conv


def good_investigator(conv):
    if conv.turn == 1:
        names = ["get_price_history", "calculate_returns_and_volatility", "calculate_abnormal_volume",
                 "compare_with_benchmark", "compare_with_peers", "get_market_context", "search_public_news"]
        return LLMTurn(text="Gathering evidence.", tool_calls=[ToolCall(f"c{i}", n, {}) for i, n in enumerate(names)])
    if conv.turn == 2:
        news = conv.last_json("c6") or {"items": []}
        assessments = [{"source_id": it["source_id"], "relevance": "direct",
                        "rationale": "Company announcement published before the open on the event day."}
                       for it in news["items"]]
        return LLMTurn(text="", tool_calls=[ToolCall("e1", "evaluate_hypotheses", {"news_assessments": assessments})])
    rv = conv.last_json("c1")
    return LLMTurn(text="", tool_calls=[ToolCall("s1", "submit_investigation", {
        "summary": f"The stock returned {rv['simple_return'] * 100:.2f}% with a robust z of {rv['robust_z_return']:.1f}, "
                   "and a company announcement inside the window is consistent with the move.",
        "key_findings": ["Company-specific announcement found inside the information window."],
        "hypothesis_notes": {"H3": "Direct announcement plus extreme stock-specific measures."},
        "unknowns": ["Article text not read."], "follow_up_checks": ["Read the announcement."],
    })])


def good_strategist(conv):
    if conv.turn == 1:
        return LLMTurn(text="", tool_calls=[ToolCall("r1", "get_investigation_summary", {}),
                                            ToolCall("r2", "get_risk_metrics", {}),
                                            ToolCall("r3", "get_portfolio_exposure", {})])
    risk = conv.last_json("r2")
    return LLMTurn(text="", tool_calls=[ToolCall("rs", "submit_risk_assessment", {
        "executive_summary": f"Before the event the one-day historical VaR was {risk['hist_var_1d_before_event'] * 100:.2f}%; "
                             "the leading explanation is a company announcement, which is an assessment, not proof.",
        "risk_implications": ["Volatility regime has shifted upward."],
        "monitoring_suggestions": ["Flag returns beyond the pre-event VaR."],
        "what_would_change_conclusion": ["Evidence the announcement was unrelated."],
        "next_steps": ["Review the next session."],
    })])


def test_llm_investigation_runs_tools_and_validates(demo_ds, demo_monitor, settings):
    backend = ScriptedBackend(good_investigator, good_strategist)
    rec = run_investigation("IRONBRG.DEMO:2026-09-17", demo_ds, settings, backend=backend, scan=demo_monitor.scan,
                            save=False)
    assert rec.engine["investigator"] == "llm" and rec.engine["strategist"] == "llm"
    assert rec.engine["llm_errors"] == []
    actors = {a["actor"] for a in rec.audit if a["kind"] == "tool_call"}
    assert {"Market Investigator", "Risk Strategist"} <= actors
    assert "Orchestrator" not in actors                    # nothing was skipped
    assert any(n["final_basis"] == "LLM judgement" for n in rec.news)
    assert rec.rubric["leading"] == "H3"
    assert rec.unverified_figures == {}
    assert "scripted-test-model" in rec.engine["summary"]


def lazy_investigator(conv):
    return LLMTurn(text="", tool_calls=[ToolCall("s1", "submit_investigation", {
        "summary": "Submitting without investigating anything at all.", "key_findings": [],
        "unknowns": [], "follow_up_checks": []})])


def test_orchestrator_runs_checks_the_agent_skipped(demo_ds, demo_monitor, settings):
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings,
                            backend=ScriptedBackend(lazy_investigator, good_strategist), scan=demo_monitor.scan,
                            save=False)
    forced = [a for a in rec.audit if a["actor"] == "Orchestrator" and a["kind"] == "tool_call"]
    assert {a["name"] for a in forced} >= {"calculate_returns_and_volatility", "calculate_abnormal_volume",
                                           "compare_with_benchmark", "compare_with_peers", "search_public_news"}
    assert any("skipped" in w for w in rec.warnings)
    assert rec.rubric["results"]                            # rubric still scored on complete evidence


def inventing_investigator(conv):
    if conv.turn == 1:
        return LLMTurn(text="", tool_calls=[ToolCall("c1", "calculate_returns_and_volatility", {})])
    text = ("The stock fell 37.5% after analysts cut targets by 22.4%." if conv.turn == 2
            else "The stock fell sharply; no figures beyond the tool outputs are stated here.")
    return LLMTurn(text="", tool_calls=[ToolCall(f"s{conv.turn}", "submit_investigation", {
        "summary": text, "key_findings": [], "unknowns": [], "follow_up_checks": []})])


def test_invented_numbers_trigger_a_revision(demo_ds, demo_monitor, settings):
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings,
                            backend=ScriptedBackend(inventing_investigator, good_strategist), scan=demo_monitor.scan,
                            save=False)
    grounding = [a for a in rec.audit if a["name"] == "numeric grounding check"]
    assert grounding and "37.5%" in grounding[0]["summary"]
    assert "37.5" not in rec.investigator["summary"]
    assert rec.engine["investigator"] == "llm"


def failing_model(conv):
    raise LLMError("LLM provider returned HTTP 401: invalid x-api-key")


def test_llm_failure_is_reported_and_labelled(demo_ds, demo_monitor, settings):
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings,
                            backend=ScriptedBackend(failing_model, failing_model), scan=demo_monitor.scan, save=False)
    assert rec.engine["investigator"] == "rules (fallback after LLM failure)"
    assert rec.engine["strategist"] == "rules (fallback after LLM failure)"
    assert any("did not complete" in e for e in rec.engine["llm_errors"])
    assert rec.engine["summary"].startswith("Rule-based fallback")
    assert rec.investigator["summary"]


def unknown_tool_model(conv):
    if conv.turn == 1:
        return LLMTurn(text="", tool_calls=[ToolCall("x1", "place_trade", {"ticker": "CURELINE.DEMO"})])
    return lazy_investigator(conv)


def test_model_cannot_call_tools_that_do_not_exist(demo_ds, demo_monitor, settings):
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings,
                            backend=ScriptedBackend(unknown_tool_model, good_strategist), scan=demo_monitor.scan,
                            save=False)
    bad = [a for a in rec.audit if a["name"] == "place_trade"]
    assert bad and bad[0]["status"] == "error" and "Unknown tool" in bad[0]["summary"]


# --- Wire formats ------------------------------------------------------------------------------------------

def test_anthropic_wire_format(monkeypatch):
    sent = []

    def fake_post(url, headers, payload, timeout, retries=1, **kwargs):
        sent.append((url, headers, json.loads(json.dumps(payload))))
        return {"stop_reason": "tool_use", "usage": {"input_tokens": 10, "output_tokens": 5},
                "content": [{"type": "text", "text": "Checking."},
                            {"type": "tool_use", "id": "toolu_1", "name": "get_market_context", "input": {}}]}

    monkeypatch.setattr(llm_mod, "_post", fake_post)
    cfg = LLMConfig(provider="anthropic", model="claude-sonnet-5-5", api_key="sk-test", base_url="https://api.anthropic.com")
    conv = AnthropicConversation(cfg, "system text", [{"name": "get_market_context", "description": "d",
                                                        "parameters": {"type": "object", "properties": {}}}])
    conv.add_user_text("hello")
    turn = conv.step()
    assert turn.tool_calls[0].name == "get_market_context" and turn.stop_reason == "tool_use"
    url, headers, payload = sent[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["anthropic-version"] == "2023-06-01" and headers["x-api-key"] == "sk-test"
    assert payload["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    conv.add_tool_results([("toolu_1", '{"ok": true}', False)])
    last = conv.messages[-1]
    assert last["role"] == "user" and last["content"][0]["type"] == "tool_result"
    assert last["content"][0]["tool_use_id"] == "toolu_1"
    assert conv.messages[-2]["role"] == "assistant"        # assistant blocks kept verbatim


def test_openai_compatible_wire_format(monkeypatch):
    def fake_post(url, headers, payload, timeout, retries=1, **kwargs):
        assert url.endswith("/chat/completions") and headers["Authorization"] == "Bearer key"
        assert payload["tools"][0]["type"] == "function"
        assert "additionalProperties" not in json.dumps(payload["tools"])   # simplified for wider compatibility
        assert "maxItems" not in json.dumps(payload["tools"])
        return {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
            {"id": "call_1", "type": "function", "function": {"name": "compare_with_peers", "arguments": "{\"peers\": [\"TCS.NS\"]}"}},
            {"id": "call_2", "type": "function", "function": {"name": "get_market_context", "arguments": "{bad json"}}]}}]}

    monkeypatch.setattr(llm_mod, "_post", fake_post)
    cfg = LLMConfig(provider="openai_compatible", model="m", api_key="key", base_url="https://example.com/v1")
    conv = OpenAICompatibleConversation(cfg, "sys", [{"name": "compare_with_peers", "description": "d",
                                                      "parameters": {"type": "object", "additionalProperties": False,
                                                                     "properties": {"peers": {"type": "array", "maxItems": 10,
                                                                                              "items": {"type": "string"}}}}}])
    turn = conv.step()
    assert turn.tool_calls[0].arguments == {"peers": ["TCS.NS"]}
    assert turn.tool_calls[1].parse_error is not None
    conv.add_tool_results([("call_1", "{}", False), ("call_2", "bad", True)])
    assert conv.messages[-1]["role"] == "tool" and conv.messages[-1]["content"].startswith("ERROR")
