"""Tool registry and audit trail shared by all agents.

A tool is an ordinary Python function with a name, a description and a JSON
schema for its arguments. Agents (LLM-driven or rule-based) can only act by
calling registered tools through `ToolRegistry.execute`, which:

1. rejects unknown tool names,
2. validates arguments against the schema,
3. runs the function and catches errors,
4. writes an audit entry with arguments, status, duration and a summary.

The audit trail is what the interface shows as the investigation timeline,
so it only ever contains steps that really ran.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

MAX_RESULT_CHARS = 9000
KEEP_LAST = {"rows"}          # chronological lists: keep the most recent entries when shortening


@dataclass
class AuditEntry:
    seq: int
    timestamp: str
    actor: str
    kind: str                     # stage | tool_call | llm_turn | validation | warning | error | info
    name: str
    status: str                   # ok | error | warning | info | skipped
    summary: str
    stage: str | None = None
    arguments: dict | None = None
    output: Any = None
    duration_ms: float | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class AuditLog:
    def __init__(self):
        self.entries: list[AuditEntry] = []
        self.listeners: list[Callable[[AuditEntry], None]] = []

    def record(self, actor: str, kind: str, name: str, status: str, summary: str, *, stage: str | None = None,
               arguments: dict | None = None, output: Any = None, duration_ms: float | None = None) -> AuditEntry:
        entry = AuditEntry(
            seq=len(self.entries) + 1,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            actor=actor, kind=kind, name=name, status=status, summary=summary, stage=stage,
            arguments=arguments, output=output, duration_ms=duration_ms,
        )
        self.entries.append(entry)
        for listener in self.listeners:
            try:
                listener(entry)
            except Exception:  # a UI callback must never break the investigation
                pass
        return entry

    def tool_calls(self, actor: str | None = None) -> list[AuditEntry]:
        return [e for e in self.entries if e.kind == "tool_call" and (actor is None or e.actor == actor)]

    def successful_tools(self) -> set[str]:
        return {e.name for e in self.entries if e.kind == "tool_call" and e.status == "ok"}


def to_jsonable(obj: Any, digits: int = 6) -> Any:
    """Convert numpy/pandas values to plain JSON types and round floats."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        if math.isnan(f) or math.isinf(f):
            return None
        return float(f"{f:.{digits}g}")
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v, digits) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [to_jsonable(v, digits) for v in obj]
    if hasattr(obj, "as_dict"):
        return to_jsonable(obj.as_dict(), digits)
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj), digits)
    return str(obj)


def fit_for_llm(data: Any, limit: int = MAX_RESULT_CHARS) -> str:
    """Serialise a tool result for the model without ever cutting the JSON in the middle.

    When the result is too long, the longest top-level list is shortened step by step (chronological
    'rows' keep their most recent entries, other lists their first entries) and a '_truncated' entry
    tells the model what was left out, so it can ask for less or page through the rest.
    """
    text = json.dumps(data, default=str)
    if len(text) <= limit:
        return text
    if isinstance(data, dict):
        trimmed = dict(data)
        shown: dict[str, tuple[int, int]] = {}
        while True:
            lists = [k for k, v in trimmed.items() if isinstance(v, list) and len(v) > 1 and k != "_truncated"]
            if not lists:
                break
            key = max(lists, key=lambda k: len(json.dumps(trimmed[k], default=str)))
            values = trimmed[key]
            total = shown.get(key, (0, len(values)))[1]
            keep = max(1, (len(values) * 2) // 3)
            trimmed[key] = values[-keep:] if key in KEEP_LAST else values[:keep]
            shown[key] = (keep, total)
            trimmed["_truncated"] = {
                k: f"showing {n} of {t} entries ({'most recent' if k in KEEP_LAST else 'first'}); ask for fewer "
                   "or page through the rest" for k, (n, t) in shown.items()}
            text = json.dumps(trimmed, default=str)
            if len(text) <= limit:
                return text
    note = f"Result too long to show in full ({len(text)} characters); this is the beginning only."
    return json.dumps({"_truncated": note, "partial": text[: max(limit - 200, 100)]})


def validate_arguments(schema: dict, args: Any) -> list[str]:
    """Small JSON-schema subset validator: required, types, enums, ranges, lengths, unknown keys."""
    if not isinstance(args, dict):
        return ["Arguments must be a JSON object."]
    errors = []
    props = schema.get("properties", {})
    for req in schema.get("required", []):
        if req not in args:
            errors.append(f"Missing required argument '{req}'.")
    for key, value in args.items():
        spec = props.get(key)
        if spec is None:
            if not schema.get("additionalProperties", False):
                errors.append(f"Unknown argument '{key}'.")
            continue
        errors.extend(_check_value(key, spec, value))
    return errors


def _check_value(key: str, spec: dict, value: Any) -> list[str]:
    t = spec.get("type")
    errs = []
    if value is None:
        return [] if spec.get("nullable") else [f"'{key}' must not be null."]
    if t == "string":
        if not isinstance(value, str):
            return [f"'{key}' must be a string."]
        if "maxLength" in spec and len(value) > spec["maxLength"]:
            errs.append(f"'{key}' is longer than {spec['maxLength']} characters.")
    elif t == "integer":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) != int(value):
            return [f"'{key}' must be an integer."]
    elif t == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return [f"'{key}' must be a number."]
    elif t == "boolean":
        if not isinstance(value, bool):
            return [f"'{key}' must be true or false."]
    elif t == "array":
        if not isinstance(value, list):
            return [f"'{key}' must be an array."]
        if "maxItems" in spec and len(value) > spec["maxItems"]:
            errs.append(f"'{key}' has more than {spec['maxItems']} items.")
        item_spec = spec.get("items")
        if item_spec:
            for i, v in enumerate(value):
                errs.extend(_check_value(f"{key}[{i}]", item_spec, v))
    elif t == "object":
        if not isinstance(value, dict):
            return [f"'{key}' must be an object."]
        if "properties" in spec:
            errs.extend(validate_arguments(spec, value))
    if "enum" in spec and value not in spec["enum"]:
        errs.append(f"'{key}' must be one of {spec['enum']}.")
    if t in ("integer", "number") and isinstance(value, (int, float)):
        if "minimum" in spec and value < spec["minimum"]:
            errs.append(f"'{key}' must be >= {spec['minimum']}.")
        if "maximum" in spec and value > spec["maximum"]:
            errs.append(f"'{key}' must be <= {spec['maximum']}.")
    return errs


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., dict]
    stage: str
    summarize: Callable[[dict], str] | None = None

    def as_llm_tool(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


@dataclass
class ToolResult:
    ok: bool
    name: str
    data: dict = field(default_factory=dict)
    error: str | None = None
    llm_content: str = ""


class ToolRegistry:
    def __init__(self, tools: list[ToolSpec], audit: AuditLog, actor: str, budget: int = 20):
        self.tools = {t.name: t for t in tools}
        self.audit = audit
        self.actor = actor
        self.budget = budget
        self.calls_used = 0

    def specs_for_llm(self) -> list[dict]:
        return [t.as_llm_tool() for t in self.tools.values()]

    @property
    def remaining(self) -> int:
        return max(self.budget - self.calls_used, 0)

    def execute(self, name: str, arguments: dict | None) -> ToolResult:
        args = arguments or {}
        spec = self.tools.get(name)
        if spec is None:
            msg = f"Unknown tool '{name}'. Available tools: {', '.join(self.tools)}."
            self.audit.record(self.actor, "tool_call", name, "error", msg, arguments=to_jsonable(args))
            return ToolResult(False, name, error=msg, llm_content=msg)
        if self.calls_used >= self.budget:
            msg = f"Tool budget of {self.budget} calls is used up. Submit your findings now."
            self.audit.record(self.actor, "tool_call", name, "skipped", msg, stage=spec.stage, arguments=to_jsonable(args))
            return ToolResult(False, name, error=msg, llm_content=msg)
        errors = validate_arguments(spec.parameters, args)
        if errors:
            msg = "Invalid arguments: " + " ".join(errors)
            self.audit.record(self.actor, "tool_call", name, "error", msg, stage=spec.stage, arguments=to_jsonable(args))
            return ToolResult(False, name, error=msg, llm_content=msg)
        self.calls_used += 1
        started = time.perf_counter()
        try:
            data = spec.handler(**args)
            status = "ok"
            error = None
        except Exception as exc:  # noqa: BLE001 - reported to the agent and the audit trail
            data = {}
            status = "error"
            error = f"{type(exc).__name__}: {str(exc)[:300]}"
        duration = (time.perf_counter() - started) * 1000
        clean = to_jsonable(data)
        if status == "ok":
            try:
                summary = spec.summarize(clean) if spec.summarize else "Completed."
            except Exception as exc:  # noqa: BLE001 - a display summary must never stop an investigation
                summary = f"Completed (summary unavailable: {type(exc).__name__})."
        else:
            summary = f"Tool failed: {error}"
        self.audit.record(self.actor, "tool_call", name, status, summary, stage=spec.stage,
                          arguments=to_jsonable(args), output=clean, duration_ms=round(duration, 1))
        content = fit_for_llm(clean) if status == "ok" else f"Tool error: {error}"
        return ToolResult(status == "ok", name, data=clean, error=error, llm_content=content)
