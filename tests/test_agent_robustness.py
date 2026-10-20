"""Regression tests for defects found in the October 2026 audit of the agent path (no real API is called)."""
import json
import pytest

from agents.context import InvestigationContext
from agents.grounding import collect_numbers, ungrounded_numbers
from agents.investigation_tools import build_investigator_tools
from agents.orchestrator import run_investigation
from agents.tools import MAX_RESULT_CHARS, AuditLog, ToolRegistry, ToolSpec, fit_for_llm
from agents.trace import decision_trace, engine_facts
from config.settings import LLMConfig
from providers import llm as llm_mod
from providers.llm import LLMTurn, OpenAICompatibleConversation, ToolCall
from providers.news_data import NewsItem, NewsSearchResult, ProviderStatus
from tests.test_llm_validation import ScriptedBackend, failing_model, good_investigator, good_strategist


# --- Tool results reach the model as valid JSON ------------------------------------------------------

def test_long_tool_results_are_shortened_without_breaking_json():
    data = {"ticker": "X", "rows": [{"date": f"2026-01-{i:02d}", "v": "x" * 80} for i in range(1, 61)],
            "items": [{"id": i, "t": "y" * 80} for i in range(60)]}
    text = fit_for_llm(data, limit=3000)
    out = json.loads(text)                               # valid JSON, never cut mid-way
    assert len(text) <= 3000 and "_truncated" in out
    assert out["rows"][-1]["date"] == "2026-01-60"       # chronological rows keep the most recent entries
    assert out["items"][0]["id"] == 0                    # other lists keep their first entries
    assert "of 60" in json.dumps(out["_truncated"])


def test_a_failing_display_summary_does_not_stop_the_tool():
    spec = ToolSpec("t", "d", {"type": "object", "properties": {}}, lambda: {"a": None}, "Test",
                    summarize=lambda d: f"{d['a']:.2f}")
    r = ToolRegistry([spec], AuditLog(), "Tester").execute("t", {})
    assert r.ok and r.data == {"a": None}


# --- The model sees every kind of news item, not just one ----------------------------------------------

def _items():
    groups = [("in_window", "direct", 30), ("in_window", "uncertain", 8), ("in_window", "unrelated", 6),
              ("after_close", "uncertain", 20), ("after_close", "unrelated", 4), ("before_window", "indirect", 3)]
    out = []
    for timing, rel, n in groups:
        for i in range(n):
            out.append(NewsItem(source_id=f"GN-{timing}-{rel}-{i}", headline=f"Example Co headline {i} " + "z" * 90,
                                provider="Test feed", source_type="news_headline", publisher=f"Pub {i % 5}",
                                published_at=f"2026-09-30T{10 + i % 9:02d}:00:00+00:00", timing=timing, relevance=rel,
                                relevance_rationale="test label " + "r" * 80))
    out.append(NewsItem(source_id="DEMO-1", headline="Example Co (fictional) announces quarterly results",
                        provider="Synthetic company announcements (fictional)", publisher="Synthetic feed",
                        source_type="synthetic_demo", published_at="2026-09-29T12:35:00+00:00",
                        timing="in_window", relevance="direct", event_date="2026-09-29"))
    return out


class _ManyNews:
    def search(self, *a, **k):
        return NewsSearchResult(ticker="SAFFRON.DEMO", event_date="2026-09-30",
                                window_start="2026-09-25T10:00:00+00:00", window_end="2026-10-01T10:00:00+00:00",
                                cutoff=None, items=_items(), statuses=[ProviderStatus("Test feed", "ok", "")])


def _registry_with_news(demo_ds, demo_monitor, settings):
    ev = demo_monitor.scan.event("SAFFRON.DEMO:2026-09-30")
    ctx = InvestigationContext(event=ev, scan=demo_monitor.scan, dataset=demo_ds, settings=settings,
                               news_service=_ManyNews())
    return ToolRegistry(build_investigator_tools(ctx), AuditLog(), "Tester", budget=20)


def test_news_search_shows_every_group_and_points_to_the_rest(demo_ds, demo_monitor, settings):
    reg = _registry_with_news(demo_ds, demo_monitor, settings)
    r = reg.execute("search_public_news", {})
    view = json.loads(r.llm_content)
    assert len(r.llm_content) <= MAX_RESULT_CHARS and "_truncated" not in view
    assert view["n_items"] == 72 and view["counts_by_timing_and_heuristic_relevance"]["after_close"]["uncertain"] == 20
    shown = {(i["timing"], i["heuristic_relevance"]) for i in view["items"]}
    assert {("in_window", "direct"), ("in_window", "uncertain"), ("in_window", "unrelated"),
            ("after_close", "uncertain"), ("after_close", "unrelated")} <= shown
    assert view["items"][0]["source_type"] == "synthetic_demo"             # company announcements come first
    assert view["items"][0]["event_date_stated_by_source"] == "2026-09-29"
    assert view["items"][0]["published_ist"] == "29 Sep 2026, 18:05 IST"  # times reach the model in IST
    assert view["window_start_ist"].endswith("IST") and "list_news_items" in view["more_items"]


def test_list_news_items_pages_through_retrieved_items(demo_ds, demo_monitor, settings):
    reg = _registry_with_news(demo_ds, demo_monitor, settings)
    assert not reg.execute("list_news_items", {}).ok                        # nothing retrieved yet
    reg.execute("search_public_news", {})
    first = reg.execute("list_news_items", {"timing": "after_close", "limit": 15}).data
    assert first["n_matching"] == 24 and len(first["items"]) == 15 and first["next_offset"] == 15
    rest = reg.execute("list_news_items", {"timing": "after_close", "offset": 15, "limit": 15}).data
    assert len(rest["items"]) == 9 and rest["next_offset"] is None
    assert not reg.execute("list_news_items", {"timing": "tomorrow"}).ok    # schema enforced


# --- Grounding accepts figures quoted correctly from sources -------------------------------------------

def test_grounding_accepts_scaled_figures_quoted_from_headlines():
    allowed = collect_numbers(["Example Infra wins ₹4,200 crore metro order", "Bank fined $1.2 billion"])
    assert ungrounded_numbers("Headlines reported a ₹4,200 crore order (Rs 4,200 cr).", allowed) == []
    assert ungrounded_numbers("That is ₹42,000,000,000.", allowed) == []
    assert ungrounded_numbers("Headlines reported a ₹5,000 crore order.", allowed) == ["₹5,000 crore"]
    assert ungrounded_numbers("Headlines reported a $1.2 billion fine.", allowed) == []


def test_grounding_reads_indian_digit_grouping_and_written_dates():
    """Indian grouping (12,34,567) was split into two unrelated numbers before the India conversion."""
    allowed = collect_numbers({"volume": 1234567.0, "value": 10_000_000.0})
    assert ungrounded_numbers("Volume was 12,34,567 shares on a ₹1,00,00,000 portfolio.", allowed) == []
    assert ungrounded_numbers("Volume was 12,34,568 shares.", allowed) == ["12,34,568"]
    assert ungrounded_numbers("Results came on 29 Sep 2026 at 18:05 IST and again on Sep 30, 2026.", allowed) == []


# --- Provider problems end in a labelled fallback, never a crash ----------------------------------------

def malformed_model(conv):
    raise KeyError("content")                              # e.g. a response without the expected fields


def test_malformed_provider_response_falls_back_to_rules(demo_ds, demo_monitor, settings):
    rec = run_investigation("CURELINE.DEMO:2026-08-28", demo_ds, settings,
                            backend=ScriptedBackend(malformed_model, good_strategist), scan=demo_monitor.scan, save=False)
    assert rec.engine["investigator"] == "rules (fallback after LLM failure)"
    assert any("Unusable response" in e for e in rec.engine["llm_errors"])
    assert rec.investigator["summary"] and rec.rubric["results"]


def test_partial_fallback_is_named_in_the_engine_summary(demo_ds, demo_monitor, settings):
    rec = run_investigation("IRONBRG.DEMO:2026-09-17", demo_ds, settings,
                            backend=ScriptedBackend(good_investigator, failing_model), scan=demo_monitor.scan, save=False)
    assert rec.engine["investigator"] == "llm" and rec.engine["strategist"].startswith("rules")
    assert rec.engine["summary"].startswith("Mixed") and "strategist rule-based fallback" in rec.engine["summary"]


def test_openai_compatible_calls_without_ids_still_match_their_results(monkeypatch):
    def fake_post(url, headers, payload, timeout, retries=1, **kwargs):
        return {"choices": [{"finish_reason": "tool_calls", "message": {"content": "", "tool_calls": [
            {"type": "function", "function": {"name": "get_market_context", "arguments": "{}"},
             "extra_content": {"google": {"thought_signature": "sig"}}}]}}]}

    monkeypatch.setattr(llm_mod, "_post", fake_post)
    conv = OpenAICompatibleConversation(LLMConfig(provider="openai_compatible", model="m", api_key="k",
                                                  base_url="https://example.com/v1"), "sys", [])
    turn = conv.step()
    stored = conv.messages[-1]["tool_calls"][0]
    assert turn.tool_calls[0].id == stored["id"] and stored["id"]
    assert stored["extra_content"] == {"google": {"thought_signature": "sig"}}   # provider fields kept verbatim
    conv.add_tool_results([(turn.tool_calls[0].id, "{}", False)])
    assert conv.messages[-1]["tool_call_id"] == stored["id"]


# --- What the model decided is visible, and only when a model ran ----------------------------------------

def adaptive_investigator(conv):
    """Chooses its next step from what the previous tools returned."""
    if conv.turn == 1:
        return LLMTurn(text="Start with the news and the price evidence.", tool_calls=[
            ToolCall("n1", "search_public_news", {}), ToolCall("p1", "calculate_returns_and_volatility", {})])
    if conv.turn == 2:
        news = conv.last_json("n1")
        in_window = [i for i in news["items"] if i["timing"] == "in_window"]
        if in_window:     # a timely item exists: read its details before judging it
            return LLMTurn(text="Read the timely item.", tool_calls=[
                ToolCall("d1", "retrieve_source_details", {"source_id": in_window[0]["source_id"]})])
        return LLMTurn(text="No timely item; check the peers.", tool_calls=[ToolCall("x1", "compare_with_peers", {})])
    if conv.turn == 3:
        return LLMTurn(text="", tool_calls=[ToolCall(f"r{i}", n, {}) for i, n in enumerate(
            ["calculate_abnormal_volume", "compare_with_benchmark", "compare_with_peers"])])
    if conv.turn == 4:
        return LLMTurn(text="", tool_calls=[ToolCall("e1", "evaluate_hypotheses", {})])
    return LLMTurn(text="", tool_calls=[ToolCall("s1", "submit_investigation", {
        "summary": "A company announcement inside the information window is consistent with the move.",
        "key_findings": ["Announcement inside the window."], "unknowns": ["Article text not read."],
        "follow_up_checks": ["Read the announcement."]})])


def test_decision_trace_shows_the_models_own_choices(demo_ds, demo_monitor, settings):
    rec = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings,
                            backend=ScriptedBackend(adaptive_investigator, good_strategist), scan=demo_monitor.scan,
                            save=False).as_dict()
    turns = decision_trace(rec["audit"], "Market Investigator")
    assert [t["tools_requested"] for t in turns][:2] == [["search_public_news", "calculate_returns_and_volatility"],
                                                         ["retrieve_source_details"]]
    detail = turns[1]["steps"][0]
    assert detail["step"] == "retrieve_source_details" and detail["arguments"]["source_id"].startswith("DEMO-")
    facts = engine_facts(rec)
    assert facts["any_llm"] and facts["investigator_model_turns"] == 5
    assert facts["tool_calls_enforced_by_orchestrator"] == 0
    rules = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings, scan=demo_monitor.scan, save=False).as_dict()
    assert decision_trace(rules["audit"]) == [] and not engine_facts(rules)["any_llm"]


# --- Honest save status and time labels ------------------------------------------------------------------------

def test_record_says_whether_it_was_saved(demo_ds, demo_monitor, settings, monkeypatch, tmp_path):
    from agents import orchestrator
    rec = run_investigation("MONSOON.DEMO:2026-09-25", demo_ds, settings, scan=demo_monitor.scan, save=True)
    assert rec.saved_to and rec.saved_to.endswith(".json") and "/" not in rec.saved_to and "\\" not in rec.saved_to
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("x")
    monkeypatch.setattr(orchestrator, "HISTORY_DIR", blocker / "inside")
    failed = run_investigation("MONSOON.DEMO:2026-09-25", demo_ds, settings, scan=demo_monitor.scan, save=True)
    assert failed.saved_to is None and any("Could not save" in w for w in failed.warnings)


def test_bar_final_time_is_shown_in_ist_on_any_server():
    """NSE's day is final at 16:15 IST whatever the server clock; the text never depends on the host's zone."""
    from ui.components import bar_final_text, fmt_ist, fmt_ist_clock
    assert bar_final_text("2026-10-21") == "16:15 IST on 21 Oct 2026"
    assert fmt_ist("2026-10-21T10:45:00+00:00") == "21 Oct 2026, 16:15 IST"
    assert fmt_ist_clock("2026-10-21T10:45:09+00:00") == "16:15:09"


# --- The real-LLM check script ------------------------------------------------------------------------------

def _llm_check_module():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts" / "llm_check.py"
    spec = importlib.util.spec_from_file_location("llm_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_llm_check_refuses_to_run_without_a_key(monkeypatch, capsys):
    module = _llm_check_module()
    monkeypatch.setattr("sys.argv", ["llm_check.py"])
    assert module.main() == 2
    assert "No LLM credentials are configured" in capsys.readouterr().out


def test_llm_check_prints_the_models_turns(demo_ds, demo_monitor, settings):
    module = _llm_check_module()
    rec = run_investigation("SAFFRON.DEMO:2026-09-30", demo_ds, settings,
                            backend=ScriptedBackend(adaptive_investigator, good_strategist), scan=demo_monitor.scan,
                            save=False).as_dict()
    lines = module.trace_lines(rec)
    assert lines[0] == "Market Investigator: 5 model turn(s)"
    assert "turn 2: model asked for retrieve_source_details" in "\n".join(lines)
    assert module.pick_event(demo_monitor) == "SAFFRON.DEMO:2026-09-30"


def test_grounding_ignores_clock_times():
    """Found in the first real Gemini run: '11:00 UTC' was flagged as an unverified figure."""
    allowed = collect_numbers({"ret": -0.0902})
    assert ungrounded_numbers("The announcement came at 11:00 UTC, before the open; the stock fell 9.02%.", allowed) == []
    assert ungrounded_numbers("It came at 18:05 IST and the stock fell 9.02%.", allowed) == []
    assert ungrounded_numbers("It came at 07:00 am and the stock fell 14.5%.", allowed) == ["14.5%"]


# --- Free-tier rate limits: wait as asked, then fall back honestly -------------------------------------------

class _Resp:
    def __init__(self, status, text="", headers=None, data=None):
        self.status_code, self.text, self.headers, self._data = status, text, headers or {}, data

    def json(self):
        return self._data


GEMINI_429 = ('[{"error": {"code": 429, "message": "You exceeded your current quota.", "status": "RESOURCE_EXHAUSTED", '
              '"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure", "violations": [{"quotaId": '
              '"GenerateRequestsPerMinutePerProjectPerModel-FreeTier"}]}, {"@type": '
              '"type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "36s"}]}}]')


def _fake_requests(monkeypatch, responses):
    import types
    calls = []

    def post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return responses.pop(0)
    monkeypatch.setitem(__import__("sys").modules, "requests", types.SimpleNamespace(post=post))
    return calls


def test_rate_limit_waits_as_the_provider_asks_then_succeeds(monkeypatch):
    """The real gemini-3.5-flash run on 20 Oct 2026 lost its risk step to an HTTP 429 that asked for a short wait."""
    calls = _fake_requests(monkeypatch, [_Resp(429, GEMINI_429), _Resp(200, data={"ok": True})])
    slept, waits = [], []
    out = llm_mod._post("https://x/chat", {}, {}, 10, rate_limit_retries=2, max_wait=65, waits=waits, sleep=slept.append)
    assert out == {"ok": True} and len(calls) == 2
    assert slept == [37.0] and "waited 36 s" in waits[0]


def test_daily_quota_fails_at_once_with_a_clear_message(monkeypatch):
    body = GEMINI_429.replace("PerMinute", "PerDay")
    _fake_requests(monkeypatch, [_Resp(429, body)])
    slept = []
    with pytest.raises(llm_mod.LLMError, match="daily request quota"):
        llm_mod._post("https://x/chat", {}, {}, 10, sleep=slept.append)
    assert slept == []


def test_a_wait_longer_than_the_limit_is_not_attempted(monkeypatch):
    _fake_requests(monkeypatch, [_Resp(429, GEMINI_429.replace('"36s"', '"300s"'))])
    slept = []
    with pytest.raises(llm_mod.LLMError, match="HTTP 429"):
        llm_mod._post("https://x/chat", {}, {}, 10, max_wait=65, sleep=slept.append)
    assert slept == []


def test_retry_after_header_is_respected(monkeypatch):
    _fake_requests(monkeypatch, [_Resp(429, "slow down", {"Retry-After": "4"}), _Resp(200, data={"ok": 1})])
    slept = []
    assert llm_mod._post("https://x/chat", {}, {}, 10, sleep=slept.append) == {"ok": 1}
    assert slept == [5.0]


# --- The agent receives Indian market context ---------------------------------------------------------------

def test_prompts_and_tools_carry_indian_market_facts(demo_ds, demo_monitor, settings):
    from agents.prompts import INVESTIGATOR_SYSTEM, STRATEGIST_SYSTEM, investigator_user_prompt
    for text in (INVESTIGATOR_SYSTEM, STRATEGIST_SYSTEM):
        assert "National Stock Exchange of India" in text and "IST" in text and "rupees" in text
        for us in ("SEC", "8-K", "S&P", "New York", "USD", "dollar", "Wall Street"):
            assert us not in text, us
    assert "Asia/Kolkata" in investigator_user_prompt({"ticker": "X"}, "live", 14)
    ev = demo_monitor.scan.event("SAFFRON.DEMO:2026-09-30")
    ctx = InvestigationContext(event=ev, scan=demo_monitor.scan, dataset=demo_ds, settings=settings,
                               news_service=_ManyNews())
    reg = ToolRegistry(build_investigator_tools(ctx), AuditLog(), "Tester", budget=20)
    price = reg.execute("get_price_history", {}).data
    assert price["currency"] == "INR (synthetic)" and "Saffron Bank" in price["name"]
    bench = reg.execute("compare_with_benchmark", {}).data
    assert bench["benchmark_name"] == "Synthetic broad-market index"
    descriptions = " ".join(t.description for t in build_investigator_tools(ctx))
    assert "NIFTY 50" in descriptions and "SEC" not in descriptions and "ETF" not in descriptions


def test_busy_provider_wait_is_labelled_honestly(monkeypatch):
    """Real gemini-3.5-flash run, 20 Oct 2026: a 503 with no wait time was logged as "rate limit ... as the provider asked"."""
    _fake_requests(monkeypatch, [_Resp(503, '{"error": {"message": "The model is overloaded."}}'),
                                 _Resp(200, data={"ok": True})])
    slept, waits = [], []
    out = llm_mod._post("https://x/chat", {}, {}, 10, rate_limit_retries=2, max_wait=65, waits=waits, sleep=slept.append)
    assert out == {"ok": True} and slept == [6.0]
    assert waits == ["HTTP 503 provider busy: waited 5 s (the provider gave no wait time) (retry 1 of 2)."]
