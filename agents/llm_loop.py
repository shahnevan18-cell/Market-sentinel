"""Generic tool-calling loop used by the LLM-driven agents.

The loop is ordinary Python: it sends the conversation to the model, runs any
tool calls through the ToolRegistry (which validates and audits them), returns
the results, and stops when the model calls its `submit_*` tool with an output
that passes schema validation and the numeric grounding check. Limits on turns
and tool calls are enforced here, not left to the model.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import BaseModel, ValidationError

from agents.grounding import check_submission
from agents.tools import AuditLog, ToolRegistry
from providers.llm import LLMBackend, LLMError


@dataclass
class AgentOutcome:
    actor: str
    engine: str                     # llm | rules
    status: str                     # completed | failed
    submission: dict | None = None
    error: str | None = None
    turns: int = 0
    tool_calls: int = 0
    usage: dict = field(default_factory=dict)
    unverified_figures: dict = field(default_factory=dict)
    model: str | None = None


def _waits(conv) -> list[str]:
    pop = getattr(conv, "pop_waits", None)
    try:
        return pop() if callable(pop) else []
    except Exception:  # noqa: BLE001 - a test double without the attribute
        return []


def run_llm_agent(*, backend: LLMBackend, actor: str, system: str, user_prompt: str, registry: ToolRegistry,
                  submit_name: str, submit_description: str, submit_schema: dict, model_cls: type[BaseModel],
                  audit: AuditLog, allowed_numbers: Callable[[], list[float]], max_turns: int = 10,
                  stage: str | None = None) -> AgentOutcome:
    tools = registry.specs_for_llm() + [{"name": submit_name, "description": submit_description,
                                          "parameters": submit_schema}]
    outcome = AgentOutcome(actor=actor, engine="llm", status="failed", model=backend.cfg.model)
    usage = {"input_tokens": 0, "output_tokens": 0}
    try:
        conv = backend.start(system, tools)
    except Exception as exc:  # noqa: BLE001
        outcome.error = f"Could not start the LLM conversation: {exc}"
        audit.record(actor, "error", "llm_start", "error", outcome.error, stage=stage)
        return outcome
    conv.add_user_text(user_prompt)
    grounding_retry_used = False
    validation_retry_used = False
    give_up = False
    nudges = 0

    for turn in range(1, max_turns + 1):
        force = submit_name if (registry.remaining == 0 or turn == max_turns) else None
        try:
            try:
                result = conv.step(force_tool=force)
            except LLMError:
                if not force:
                    raise
                conv.add_user_text(f"Call {submit_name} now with your findings.")
                result = conv.step(force_tool=None)
        except LLMError as exc:
            for w in _waits(conv):
                audit.record(actor, "warning", "rate limit", "warning", w, stage=stage)
            outcome.error = str(exc)
            outcome.turns = turn
            audit.record(actor, "error", "llm_call", "error", f"LLM call failed: {exc}", stage=stage)
            break
        except Exception as exc:  # noqa: BLE001 - malformed provider response: fall back instead of crashing
            outcome.error = f"Unusable response from the LLM provider ({type(exc).__name__}: {str(exc)[:200]})"
            outcome.turns = turn
            audit.record(actor, "error", "llm_call", "error", outcome.error, stage=stage)
            break
        for w in _waits(conv):
            audit.record(actor, "warning", "rate limit", "warning", w, stage=stage)
        for k in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            if isinstance(result.usage.get(k), (int, float)):
                usage[k] = usage.get(k, 0) + result.usage[k]
        outcome.turns = turn
        names = ", ".join(c.name for c in result.tool_calls) or "no tool calls"
        note = (result.text or "").strip().replace("\n", " ")
        audit.record(actor, "llm_turn", f"model turn {turn}", "info",
                     f"Requested: {names}" + (f". Model note: {note[:240]}" if note else ""), stage=stage,
                     output={"tools_requested": [c.name for c in result.tool_calls], "model_note": note[:800],
                             "stop_reason": result.stop_reason})

        if not result.tool_calls:
            nudges += 1
            if nudges > 2:
                outcome.error = "The model stopped calling tools without submitting structured findings."
                audit.record(actor, "error", submit_name, "error", outcome.error, stage=stage)
                break
            conv.add_user_text(f"Continue using the tools if needed, then call {submit_name}. Do not answer in plain text.")
            continue

        tool_results = []
        accepted = None
        for call in result.tool_calls:
            if call.parse_error:
                tool_results.append((call.id, call.parse_error, True))
                audit.record(actor, "tool_call", call.name, "error", call.parse_error, stage=stage)
                continue
            if call.name == submit_name:
                try:
                    model = model_cls.model_validate(call.arguments)
                except ValidationError as exc:
                    msg = "Submission failed schema validation: " + "; ".join(
                        f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:6])
                    audit.record(actor, "validation", submit_name, "error", msg, stage=stage)
                    if validation_retry_used:
                        outcome.error = "Submission failed validation twice. " + msg
                        give_up = True
                    validation_retry_used = True
                    tool_results.append((call.id, msg + " Fix these fields and submit again.", True))
                    continue
                data = model.model_dump()
                flags = check_submission(data, allowed_numbers())
                if flags and not grounding_retry_used:
                    grounding_retry_used = True
                    figures = sorted({f for v in flags.values() for f in v})
                    msg = ("These figures do not match any tool output: " + ", ".join(figures[:12]) +
                           ". Use only numbers returned by tools (copy them) or remove them, then submit again.")
                    audit.record(actor, "validation", "numeric grounding check", "warning", msg, stage=stage)
                    tool_results.append((call.id, msg, True))
                    continue
                accepted = data
                outcome.unverified_figures = flags
                tool_results.append((call.id, "Submission accepted.", False))
            else:
                r = registry.execute(call.name, call.arguments)
                tool_results.append((call.id, r.llm_content, not r.ok))
        outcome.tool_calls = registry.calls_used
        if accepted is not None:
            outcome.status = "completed"
            outcome.submission = accepted
            outcome.error = None
            flag_note = ""
            if outcome.unverified_figures:
                n = sum(len(v) for v in outcome.unverified_figures.values())
                flag_note = f"; {n} figure(s) could not be matched to tool outputs and are flagged in the report"
            audit.record(actor, "validation", submit_name, "ok",
                         "Structured submission passed schema validation" + flag_note, stage=stage)
            break
        if give_up:
            break
        conv.add_tool_results(tool_results)
    else:
        outcome.error = outcome.error or f"No valid submission within {max_turns} model turns."
        audit.record(actor, "error", submit_name, "error", outcome.error, stage=stage)

    outcome.usage = usage
    outcome.tool_calls = registry.calls_used
    return outcome
