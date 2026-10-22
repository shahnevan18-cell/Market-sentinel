"""Readable views of what an investigation actually did, built only from its saved audit trail.

`decision_trace` lists each model turn of an LLM-driven agent with the tools the model asked for and what
those tools returned, which is the evidence that the model chose its own next steps. `engine_facts`
summarises which engine ran and how much of the work the model did. Rule-based runs have no model turns,
so their trace is empty rather than imitated.

`analyst_reading` collects the model's own written reading of the evidence (its notes on the leading explanations,
the checks it suggests and what would change its view), and `model_activity` describes what the model did
differently from the fixed protocol. Both read only what the record already holds; nothing is generated here.
"""
from __future__ import annotations

import re


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


# ---------------------------------------------------------------------------
# What the model contributed, for the Summary tab and the report
# ---------------------------------------------------------------------------

TOOL_LABELS = {
    "get_price_history": "price history",
    "calculate_returns_and_volatility": "returns and volatility",
    "calculate_abnormal_volume": "abnormal volume",
    "compare_with_benchmark": "benchmark comparison",
    "compare_with_peers": "peer comparison",
    "get_market_context": "market context",
    "search_public_news": "news search",
    "list_news_items": "news listing",
    "retrieve_source_details": "source details",
    "evaluate_hypotheses": "the rubric",
    "get_investigation_summary": "investigation summary",
    "get_risk_metrics": "risk metrics",
    "get_portfolio_exposure": "portfolio exposure",
    "run_stress_scenario": "stress scenario",
}
SUBMIT_TOOLS = {"submit_investigation", "submit_risk_assessment"}
# The rule-based protocol's fixed investigator plan (agents/market_investigator.py RULE_PLAN, then the rubric).
# Source lookups are optional in the protocol (only for up to three direct or uncertain items).
PROTOCOL_TOOLS = ("get_price_history", "calculate_returns_and_volatility", "calculate_abnormal_volume",
                  "compare_with_benchmark", "compare_with_peers", "get_market_context", "search_public_news",
                  "evaluate_hypotheses")
OPTIONAL_PROTOCOL_TOOLS = {"retrieve_source_details"}
NEWS_DEFAULTS = {"days_before": 3, "days_after": 1}
_GROUNDING_RE = re.compile(r"do not match any tool output: (.*?)\. Use only")

RUBRIC_NOTE = ("The verdict above comes from the fixed rubric alone. The rubric counts timely headlines but cannot "
               "weigh what they say, such as a profit beat or a guidance change; the model's reading can. When the two "
               "differ, the recommended next action names the check that would settle it.")
NO_MODEL_NOTE = ("No model analysis in this run. The rule-based protocol ran the same tools in a fixed order and "
                 "wrote the findings from templates. Choose Gemini (model-directed) in the sidebar for the model's "
                 "own reading.")


def tool_label(name: str) -> str:
    return TOOL_LABELS.get(name, str(name).replace("_", " "))


def _join(items: list[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def model_name(rec: dict) -> str:
    eng = rec.get("engine") or {}
    if eng.get("model"):
        return str(eng["model"])
    text = str(eng.get("requested") or eng.get("summary") or "").replace("LLM:", "").strip()
    return text.split(" via ")[0].strip() or "the model"


def _grounding_rejections(audit: list[dict], actor: str) -> list[str]:
    figures: list[str] = []
    for e in audit:
        if (e.get("actor") == actor and e.get("kind") == "validation" and e.get("name") == "numeric grounding check"
                and e.get("status") == "warning"):
            m = _GROUNDING_RE.search(str(e.get("summary") or ""))
            if m:
                figures += [f.strip() for f in m.group(1).split(", ") if f.strip()]
    return figures


def model_activity(rec: dict) -> dict:
    """What the model did in this run, taken only from the saved audit trail and record.

    For each role: whether the model completed it, its turns, the tools it asked for in each turn, the tools that
    ran and the figures the grounding check rejected. For the investigator also the difference from the fixed
    protocol and the news window it chose. For headlines: how many the model judged itself and how many of those
    it changed from the keyword label."""
    eng = rec.get("engine") or {}
    audit = rec.get("audit") or []
    roles: dict[str, dict] = {}
    for actor, key in (("Market Investigator", "investigator"), ("Risk Strategist", "strategist")):
        turns = decision_trace(audit, actor)
        calls = [e for e in audit if e.get("actor") == actor and e.get("kind") == "tool_call"]
        roles[key] = {
            "completed_by_model": eng.get(key) == "llm",
            "turns": len(turns),
            "turn_tools": [[t for t in turn["tools_requested"] if t not in SUBMIT_TOOLS] for turn in turns],
            "submissions": sum(1 for turn in turns if any(t in SUBMIT_TOOLS for t in turn["tools_requested"])),
            "tools_used": [e.get("name") for e in calls if e.get("status") == "ok"],
            "grounding_rejected": _grounding_rejections(audit, actor),
        }
    inv = roles["investigator"]
    used = set(inv["tools_used"])
    inv["skipped_vs_protocol"] = [t for t in PROTOCOL_TOOLS if t not in used] if inv["turns"] else []
    inv["added_vs_protocol"] = sorted(t for t in used if t not in PROTOCOL_TOOLS and t not in OPTIONAL_PROTOCOL_TOOLS
                                      and t not in SUBMIT_TOOLS) if inv["turns"] else []
    news_calls = [e for e in audit if e.get("actor") == "Market Investigator" and e.get("kind") == "tool_call"
                  and e.get("name") == "search_public_news"]
    args = (news_calls[0].get("arguments") or {}) if news_calls else {}
    inv["news_window"] = {k: args[k] for k in ("days_before", "days_after", "query") if args.get(k) not in (None, "")}
    strat = roles["strategist"]
    strat["stress"] = [str(e.get("summary") or "") for e in audit if e.get("actor") == "Risk Strategist"
                       and e.get("kind") == "tool_call" and e.get("name") == "run_stress_scenario"
                       and e.get("status") == "ok"]
    news = rec.get("news") or []
    judged = [n for n in news if n.get("final_basis") == "LLM judgement"]
    changed = [n for n in judged if n.get("relevance") and n.get("relevance") != n.get("final_relevance")]
    examples = (changed + [n for n in judged if n not in changed and n.get("final_relevance") == "direct"])[:2]
    return {
        "any_model": inv["completed_by_model"] or strat["completed_by_model"],
        "model": model_name(rec),
        "investigator": inv,
        "strategist": strat,
        "headlines": {"total": len(news), "judged": len(judged), "changed": len(changed),
                      "examples": [{"headline": n.get("headline"), "publisher": n.get("publisher") or n.get("provider"),
                                    "from": n.get("relevance"), "to": n.get("final_relevance"),
                                    "why": n.get("final_rationale")} for n in examples]},
        "forced_checks": sum(1 for e in audit if e.get("actor") == "Orchestrator" and e.get("kind") == "tool_call"),
    }


def _turn_tools_text(tools: list[str]) -> str:
    counts: dict[str, int] = {}
    for t in tools:
        counts[t] = counts.get(t, 0) + 1
    return _join([tool_label(t) + (f" ({n} times)" if n > 1 else "") for t, n in counts.items()])


def _turns_text(role: dict) -> str:
    parts = [f"turn {i}: {_turn_tools_text(tools)}"
             for i, tools in enumerate(role["turn_tools"], start=1) if tools]
    text = "; ".join(parts)
    n = role["submissions"]
    if n == 1:
        text += "; then it submitted"
    elif n > 1:
        text += f"; then it submitted {n} times"
    return text


def model_activity_lines(act: dict) -> list[str]:
    """Plain sentences describing what the model did, for the interface and the report."""
    lines: list[str] = []
    inv, strat = act["investigator"], act["strategist"]
    if inv["completed_by_model"]:
        lines.append(f"Investigator, {inv['turns']} model turn(s): {_turns_text(inv)}.")
        diff = []
        if inv["skipped_vs_protocol"]:
            diff.append("skipped " + _join([tool_label(t) for t in inv["skipped_vs_protocol"]]))
        if inv["added_vs_protocol"]:
            diff.append("added " + _join([tool_label(t) for t in inv["added_vs_protocol"]]))
        w = inv["news_window"]
        before = w.get("days_before", NEWS_DEFAULTS["days_before"])
        after = w.get("days_after", NEWS_DEFAULTS["days_after"])
        if (before, after) != (NEWS_DEFAULTS["days_before"], NEWS_DEFAULTS["days_after"]):
            diff.append(f"chose a news window of {before} session(s) before and {after} after (the protocol uses "
                        f"{NEWS_DEFAULTS['days_before']} and {NEWS_DEFAULTS['days_after']})")
        if w.get("query"):
            diff.append(f"searched with its own query \"{w['query']}\"")
        lines.append("Compared with the fixed protocol it " + (_join(diff) if diff else
                     "used the same tools, in its own order") + ".")
    elif inv["turns"]:
        lines.append("Investigator: the model started but did not finish; the fixed protocol completed the step.")
    h = act["headlines"]
    if h["judged"]:
        line = (f"Headlines: the model judged {h['judged']} of {h['total']} itself"
                + (f" and changed the keyword label of {h['changed']}" if h["changed"] else "") + ".")
        for ex in h["examples"]:
            change = (f"{ex['from']} to {ex['to']}" if ex["from"] and ex["from"] != ex["to"] else f"kept {ex['to']}")
            line += f" \"{str(ex['headline'])[:110]}\" ({ex['publisher']}): {change}"
            if ex.get("why"):
                why = str(ex["why"]).strip().rstrip(".")
                line += ", because " + why[:1].lower() + why[1:]
            line += "."
        lines.append(line)
    if strat["completed_by_model"]:
        line = f"Risk strategist, {strat['turns']} model turn(s): {_turns_text(strat)}."
        if strat["stress"]:
            line += " Stress scenarios it chose: " + "; ".join(s.rstrip(".") for s in strat["stress"]) + "."
        lines.append(line)
    elif strat["turns"]:
        lines.append("Risk strategist: the model started but did not finish; the fixed protocol completed the step.")
    rejected = [(who, f) for who, role in (("investigator", inv), ("strategist", strat))
                for f in role["grounding_rejected"]]
    if rejected:
        lines.append("Grounding check: rejected " + _join([f"{f} ({who})" for who, f in rejected])
                     + ", a figure no tool had returned; the model then corrected its submission.")
    elif act["any_model"]:
        lines.append("Grounding check: every figure the model wrote matched a tool output at the first attempt.")
    forced = act["forced_checks"]
    lines.append("Required checks the orchestrator had to add: " + ("none." if not forced else f"{forced}."))
    return lines


def model_activity_summary(act: dict) -> str:
    """One sentence for under the analyst reading."""
    inv, strat = act["investigator"], act["strategist"]
    calls = sum(1 for t in inv["tools_used"] + strat["tools_used"] if t not in SUBMIT_TOOLS)
    turns = inv["turns"] + strat["turns"]
    h = act["headlines"]
    rejected = len(inv["grounding_rejected"]) + len(strat["grounding_rejected"])
    text = f"{act['model']} chose {calls} tool call(s) in {turns} model turn(s)"
    if h["judged"]:
        text += f", judged {h['judged']} of {h['total']} headlines itself"
    if rejected:
        text += f" and had {rejected} figure(s) rejected by the grounding check, which it then corrected"
    return text + "."


def analyst_reading(rec: dict) -> dict | None:
    """The model's own reading of the evidence, or None when no model completed either role."""
    eng = rec.get("engine") or {}
    inv_llm, strat_llm = eng.get("investigator") == "llm", eng.get("strategist") == "llm"
    if not (inv_llm or strat_llm):
        return None
    inv = rec.get("investigator") or {}
    strat = rec.get("strategist") or {}
    rub = rec.get("rubric") or {}
    notes = (inv.get("hypothesis_notes") or {}) if inv_llm else {}
    ranked = [r for r in (rub.get("results") or []) if r.get("id") != "H5"]
    ranked.sort(key=lambda r: -(r.get("score") or 0))
    explanations = [{"id": r.get("id"), "label": r.get("label"), "score": r.get("score") or 0,
                     "note": notes[r.get("id")]} for r in ranked[:2] if notes.get(r.get("id"))]
    return {
        "model": model_name(rec),
        "investigator_by_model": inv_llm,
        "strategist_by_model": strat_llm,
        "explanations": explanations,
        "why_unresolved": notes.get("H5") if rub.get("leading") == "H5" else None,
        "checks": list(inv.get("follow_up_checks") or [])[:3] if inv_llm else [],
        "open_questions": list(inv.get("unknowns") or [])[:2] if inv_llm else [],
        "would_change": list(strat.get("what_would_change_conclusion") or [])[:3] if strat_llm else [],
        "summary": inv.get("summary") if inv_llm else None,
        "strategist_summary": strat.get("executive_summary") if strat_llm else None,
    }
