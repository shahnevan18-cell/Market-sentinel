"""Readable views of what an investigation actually did, built only from its saved audit trail.

`decision_trace` lists each model turn of an LLM-driven agent with the tools the model asked for and what
those tools returned, which is the evidence that the model chose its own next steps. `engine_facts`
summarises which engine ran and how much of the work the model did. Rule-based runs have no model turns,
so their trace is empty rather than imitated.
"""
from __future__ import annotations


def decision_trace(audit: list[dict], actor: str = "Market Investigator") -> list[dict]:
    """One row per model turn: tools requested, then every tool call and validation step that followed."""
    turns: list[dict] = []
    current: dict | None = None
    for e in audit:
        if e.get("actor") != actor:
            continue
        kind = e.get("kind")
        if kind == "llm_turn":
            out = e.get("output") or {}
            current = {"turn": len(turns) + 1, "timestamp": e.get("timestamp"),
                       "tools_requested": out.get("tools_requested") or [],
                       "model_note": out.get("model_note") or "", "steps": []}
            turns.append(current)
        elif kind in ("tool_call", "validation", "error", "warning") and current is not None:
            current["steps"].append({"step": e.get("name"), "kind": kind, "status": e.get("status"),
                                     "arguments": e.get("arguments") or {}, "result": e.get("summary")})
    return turns


def engine_facts(rec: dict) -> dict:
    """Which engine produced each part of the record, and what the model did."""
    eng = rec.get("engine") or {}
    audit = rec.get("audit") or []
    by_actor: dict[str, int] = {}
    for e in audit:
        if e.get("kind") == "tool_call" and e.get("status") == "ok":
            by_actor[e.get("actor")] = by_actor.get(e.get("actor"), 0) + 1
    usage = rec.get("usage") or {}
    tokens = 0
    for part in usage.values():
        for k in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            if isinstance((part or {}).get(k), (int, float)):
                tokens += part[k]
    inv_llm = eng.get("investigator") == "llm"
    strat_llm = eng.get("strategist") == "llm"
    return {
        "summary": eng.get("summary"),
        "investigator_engine": eng.get("investigator"),
        "strategist_engine": eng.get("strategist"),
        "any_llm": inv_llm or strat_llm,
        "investigator_model_turns": eng.get("investigator_turns") or 0,
        "strategist_model_turns": eng.get("strategist_turns") or 0,
        "tool_calls_by_actor": by_actor,
        "tool_calls_enforced_by_orchestrator": by_actor.get("Orchestrator", 0),
        "llm_errors": list(eng.get("llm_errors") or []),
        "tokens": int(tokens),
        "unverified_figures": sum(len(v) for who in (rec.get("unverified_figures") or {}).values()
                                  for v in who.values()),
    }
