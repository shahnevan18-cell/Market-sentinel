"""LLM clients with tool calling.

Two wire formats are supported, both through plain HTTPS calls so the exact
requests are easy to inspect:

* Anthropic Messages API (tool_use / tool_result content blocks).
* Any OpenAI-compatible chat-completions endpoint (tool_calls / role "tool"),
  which covers OpenAI, Google Gemini's OpenAI-compatible endpoint, Groq,
  OpenRouter and local servers such as Ollama.

The LLM never computes numbers for the app. It chooses which tools to call
and writes qualitative judgements; every number comes back from Python tools.
A Claude chat subscription does not include API access: an API key with
credit (or a provider's free tier) is needed for live LLM mode.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from config.settings import LLMConfig

ANTHROPIC_VERSION = "2023-06-01"


SECRET_PATTERNS = [re.compile(r"AIza[0-9A-Za-z_\-]{20,}"), re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
                   re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), re.compile(r"(?i)(api[_-]?key[=:]\s*)[^\s&\"']+")]


def redact(text: str, secrets: list[str | None] | tuple = ()) -> str:
    """Remove API keys from text before it is shown, logged or saved: the configured key itself and anything shaped
    like a Google, OpenAI-style or bearer credential."""
    out = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 6:
            out = out.replace(secret, "[redacted]")
    for pat in SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[redacted]", out)
    return out


class LLMError(RuntimeError):
    """Raised when the model provider returns an error or an unusable response. Messages are redacted."""

    def __init__(self, message: str = ""):
        super().__init__(redact(message))


ERROR_CATEGORIES = {
    "invalid_credentials": "The provider rejected the key (HTTP 401 or 403). Check the key's value and that it belongs "
                           "to a project where the API is enabled.",
    "quota_daily": "The daily request quota for this model and Google project is used up. Google resets it at "
                   "midnight US Pacific time.",
    "rate_limited": "The provider rate-limited the requests (HTTP 429) beyond the waits the app allows.",
    "model_not_found": "The model name was not found for this key (HTTP 404). Check LLM_MODEL.",
    "provider_busy": "The provider was overloaded or unavailable (HTTP 503 or 529) after the allowed retries.",
    "timeout": "The provider did not answer within the time limit.",
    "network": "The provider could not be reached (network error).",
    "invalid_response": "The provider returned a response the app could not use.",
    "no_tool_call": "The model stopped calling tools without submitting its findings.",
    "invalid_output": "The model's findings failed validation twice, so they were not used.",
    "turn_limit": "The model did not submit valid findings within the allowed number of turns.",
    "provider_error": "The provider returned an error.",
}
# Errors raised by the provider or the network, as opposed to the model running but producing unusable output.
PROVIDER_ERROR_CATEGORIES = {"invalid_credentials", "quota_daily", "rate_limited", "model_not_found", "provider_busy",
                             "timeout", "network", "invalid_response", "provider_error"}


def quota_reset_ist(now: datetime | None = None) -> datetime:
    """Next midnight in US Pacific time (when Google resets daily Gemini quotas), expressed in IST."""
    pacific, ist = ZoneInfo("America/Los_Angeles"), ZoneInfo("Asia/Kolkata")
    now = (now or datetime.now(timezone.utc)).astimezone(pacific)
    nxt = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=pacific)
    return nxt.astimezone(ist)


def describe_error(category: str, now: datetime | None = None) -> str:
    """Plain explanation of an error category; for a daily quota it adds the reset time in IST."""
    text = ERROR_CATEGORIES.get(category, ERROR_CATEGORIES["provider_error"])
    if category == "quota_daily":
        reset = quota_reset_ist(now)
        text += f" That is {reset:%H:%M} IST on {reset:%a %d %b}."
    return text


def classify_error(message: str) -> str:
    """Map an LLM error message to a category in ERROR_CATEGORIES."""
    m = str(message or "")
    low = m.lower()
    if "http 401" in low or "http 403" in low or "api key not valid" in low or "permission_denied" in low \
            or "unauthenticated" in low or "invalid x-api-key" in low:
        return "invalid_credentials"
    if "daily request quota" in low or "perday" in low:
        return "quota_daily"
    if "http 429" in low:
        return "rate_limited"
    if "http 404" in low:
        return "model_not_found"
    if "http 503" in low or "http 529" in low or "overloaded" in low:
        return "provider_busy"
    if "timeout" in low or "timed out" in low:
        return "timeout"
    if "network error" in low or "connection" in low or "name resolution" in low:
        return "network"
    if "not json" in low or "unexpected response" in low or "unusable response" in low:
        return "invalid_response"
    if "without submitting" in low or "stopped calling tools" in low:
        return "no_tool_call"
    if "failed validation" in low:
        return "invalid_output"
    if "no valid submission within" in low:
        return "turn_limit"
    return "provider_error"


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict
    parse_error: str | None = None


@dataclass
class LLMTurn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    usage: dict = field(default_factory=dict)


RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def requested_wait(headers, body: str) -> float | None:
    """Seconds the provider asks the client to wait: the Retry-After header, or Google's RetryInfo ("36s")."""
    value = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
    if value:
        try:
            return float(value)
        except ValueError:
            pass
    m = RETRY_DELAY_RE.search(body or "")
    return float(m.group(1)) if m else None


def is_daily_quota(body: str) -> bool:
    """A per-day quota (for example Gemini's free-tier requests per day) does not reset within a run."""
    return "PerDay" in (body or "") or "per day" in (body or "").lower()


def _post(url: str, headers: dict, payload: dict, timeout: float, retries: int = 1, rate_limit_retries: int = 2,
          max_wait: float = 65.0, waits: list | None = None, sleep=time.sleep):
    """POST with two separate retry budgets: network errors and rate limits.

    On HTTP 429 or 503 the call waits as long as the provider asks (Retry-After or Google's retryDelay), up to
    `max_wait` seconds per wait and `rate_limit_retries` times. A per-day quota or a longer requested wait fails at
    once with a clear message, so the orchestrator can fall back honestly. Every wait is appended to `waits`.
    """
    import requests
    last = None
    net_attempts = rate_attempts = 0
    while True:
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            last = LLMError(f"Network error calling the LLM provider: {type(exc).__name__}: {str(exc)[:200]}")
            net_attempts += 1
            if net_attempts > retries:
                break
            sleep(1.5 * net_attempts)
            continue
        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as exc:
                raise LLMError("The LLM provider returned a response that is not JSON.") from exc
        body = resp.text or ""
        key = (headers.get("Authorization") or "").replace("Bearer ", "") or headers.get("x-api-key")
        detail = redact(body[:300], [key])
        last = LLMError(f"LLM provider returned HTTP {resp.status_code}: {detail}")
        if resp.status_code in (429, 503, 529):
            if resp.status_code == 429 and is_daily_quota(body):
                raise LLMError(f"LLM provider returned HTTP 429: the daily request quota is used up, so waiting would "
                               f"not help. Try again tomorrow or switch LLM_MODEL. Detail: {detail}")
            asked = requested_wait(getattr(resp, "headers", {}), body)
            wait = asked if asked is not None else 5.0 * (rate_attempts + 1)
            if rate_attempts >= rate_limit_retries or wait > max_wait:
                break
            rate_attempts += 1
            if waits is not None:
                reason = "rate limit" if resp.status_code == 429 else "provider busy"
                source = "as the provider asked" if asked is not None else "(the provider gave no wait time)"
                waits.append(f"HTTP {resp.status_code} {reason}: waited {wait:.0f} s {source} "
                             f"(retry {rate_attempts} of {rate_limit_retries}).")
            sleep(wait + 1.0)
            continue
        if resp.status_code in (500, 502) and net_attempts < retries:
            net_attempts += 1
            sleep(2.0 * net_attempts)
            continue
        break
    raise last or LLMError("Unknown LLM error.")


def _post_cfg(cfg: LLMConfig, url: str, headers: dict, payload: dict, waits: list | None):
    return _post(url, headers, payload, cfg.timeout, rate_limit_retries=cfg.rate_limit_retries,
                 max_wait=cfg.rate_limit_max_wait, waits=waits)


class Conversation:
    """Provider-neutral conversation used by the agent loop."""

    waits: list

    def pop_waits(self) -> list[str]:
        """Rate-limit waits since the last call, so the agent loop can record them in the audit trail."""
        out, self.waits[:] = list(self.waits), []
        return out

    def add_user_text(self, text: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def step(self, force_tool: str | None = None) -> LLMTurn:  # pragma: no cover
        raise NotImplementedError

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:  # pragma: no cover
        raise NotImplementedError


class AnthropicConversation(Conversation):
    def __init__(self, cfg: LLMConfig, system: str, tools: list[dict]):
        self.cfg = cfg
        self.system = system
        self.tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                      for t in tools]
        self.messages: list[dict] = []
        self.waits: list[str] = []

    def add_user_text(self, text: str) -> None:
        if self.messages and self.messages[-1]["role"] == "user" and isinstance(self.messages[-1]["content"], list):
            self.messages[-1]["content"].append({"type": "text", "text": text})
        else:
            self.messages.append({"role": "user", "content": [{"type": "text", "text": text}]})

    def step(self, force_tool: str | None = None) -> LLMTurn:
        payload = {
            "model": self.cfg.model,
            "max_tokens": self.cfg.max_tokens,
            "system": self.system,
            "messages": self.messages,
            "tools": self.tools,
        }
        if force_tool:
            payload["tool_choice"] = {"type": "tool", "name": force_tool}
        headers = {
            "x-api-key": self.cfg.api_key or "",
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        base = (self.cfg.base_url or "https://api.anthropic.com").rstrip("/")
        try:
            data = _post_cfg(self.cfg, f"{base}/v1/messages", headers, payload, self.waits)
        except LLMError as exc:
            if force_tool and "tool_choice" in str(exc):
                payload.pop("tool_choice", None)
                data = _post_cfg(self.cfg, f"{base}/v1/messages", headers, payload, self.waits)
            else:
                raise
        content = data.get("content") or []
        # Keep every block (including any thinking blocks) so the next request is well formed.
        self.messages.append({"role": "assistant", "content": content})
        texts = [b.get("text", "") for b in content if b.get("type") == "text"]
        calls = [ToolCall(id=b["id"], name=b["name"], arguments=b.get("input") or {})
                 for b in content if b.get("type") == "tool_use"]
        return LLMTurn(text="\n".join(t for t in texts if t), tool_calls=calls,
                       stop_reason=data.get("stop_reason"), usage=data.get("usage") or {})

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        blocks = [{"type": "tool_result", "tool_use_id": cid, "content": content, "is_error": bool(err)}
                  for cid, content, err in results]
        self.messages.append({"role": "user", "content": blocks})


SAFE_SCHEMA_KEYS = {"type", "properties", "items", "required", "enum", "description"}


def simplify_schema(schema):
    """Keep only widely supported JSON-schema keywords (some providers reject the rest).

    Removed constraints (lengths, ranges, additionalProperties) are still enforced
    locally by ToolRegistry and the Pydantic submission models.
    """
    if isinstance(schema, dict):
        out = {}
        for k, v in schema.items():
            if k not in SAFE_SCHEMA_KEYS:
                continue
            if k == "properties" and isinstance(v, dict):
                out[k] = {name: simplify_schema(sub) for name, sub in v.items()}
            else:
                out[k] = simplify_schema(v)
        return out
    if isinstance(schema, list):
        return [simplify_schema(x) for x in schema]
    return schema


class OpenAICompatibleConversation(Conversation):
    def __init__(self, cfg: LLMConfig, system: str, tools: list[dict]):
        self.cfg = cfg
        self._n_calls = 0
        self.waits: list[str] = []
        self.tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                        "parameters": simplify_schema(t["parameters"])}}
                      for t in tools]
        self.messages: list[dict] = [{"role": "system", "content": system}]

    def add_user_text(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def step(self, force_tool: str | None = None) -> LLMTurn:
        payload = {"model": self.cfg.model, "messages": self.messages, "tools": self.tools}
        payload["tool_choice"] = {"type": "function", "function": {"name": force_tool}} if force_tool else "auto"
        headers = {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}
        base = (self.cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        data = _post_cfg(self.cfg, f"{base}/chat/completions", headers, payload, self.waits)
        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from the OpenAI-compatible endpoint.") from exc
        calls, stored = [], []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw) if isinstance(raw, str) else dict(raw)
                err = None
            except (ValueError, TypeError) as exc:
                args, err = {}, f"Arguments were not valid JSON: {exc}"
            self._n_calls += 1
            call_id = tc.get("id") or f"call_ms_{self._n_calls}"
            calls.append(ToolCall(id=call_id, name=fn.get("name", ""), arguments=args, parse_error=err))
            stored.append({**tc, "id": call_id})     # provider fields kept verbatim; a missing id is filled in
        assistant = {"role": "assistant", "content": msg.get("content") or ""}
        if stored:
            assistant["tool_calls"] = stored
        if msg.get("extra_content") is not None:     # provider-specific data that must be sent back unchanged
            assistant["extra_content"] = msg["extra_content"]
        self.messages.append(assistant)
        return LLMTurn(text=msg.get("content") or "", tool_calls=calls,
                       stop_reason=choice.get("finish_reason"), usage=data.get("usage") or {})

    def add_tool_results(self, results: list[tuple[str, str, bool]]) -> None:
        for cid, content, err in results:
            self.messages.append({"role": "tool", "tool_call_id": cid,
                                  "content": ("ERROR: " + content) if err else content})


class LLMBackend:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    @property
    def label(self) -> str:
        return self.cfg.describe()

    def start(self, system: str, tools: list[dict]) -> Conversation:
        if self.cfg.provider == "anthropic":
            return AnthropicConversation(self.cfg, system, tools)
        return OpenAICompatibleConversation(self.cfg, system, tools)


def make_backend(cfg: LLMConfig) -> LLMBackend | None:
    return LLMBackend(cfg) if cfg.enabled else None


PROBE_TOOL = {"name": "report_ready", "description": "Confirm that tool calling works.",
              "parameters": {"type": "object", "properties": {"status": {"type": "string", "enum": ["ready"]}},
                             "required": ["status"]}}


def probe(cfg: LLMConfig, timeout: float = 30.0) -> dict:
    """One real request to the configured model, asking it to call a test tool.

    It checks the key, the endpoint, the model name and tool calling in a single call, and costs one request of the
    quota. No retries or long waits, so a quota problem shows at once. The result never contains the key.
    """
    out = {"ok": False, "model": cfg.model, "vendor": cfg.vendor, "tool_called": False, "category": None,
           "message": "", "summary": "", "detail": "", "latency_ms": None, "requests": 1}
    if not cfg.enabled:
        out.update(requests=0, category="not_configured", message=cfg.status_text(), summary=cfg.status_text())
        return out
    started = time.perf_counter()
    try:
        quick = LLMConfig(**{**cfg.__dict__, "timeout": timeout, "rate_limit_retries": 0, "max_tokens": 200})
        conv = LLMBackend(quick).start("You are a connection test. Call the tool you are given.", [PROBE_TOOL])
        conv.add_user_text("Call report_ready with status 'ready'.")
        turn = conv.step(force_tool="report_ready")
        called = any(c.name == "report_ready" for c in turn.tool_calls)
        text = "The model answered and called the test tool." if called else ERROR_CATEGORIES["no_tool_call"]
        out.update(ok=called, tool_called=called, category=None if called else "no_tool_call", message=text,
                   summary=text)
    except LLMError as exc:
        cat = classify_error(str(exc))
        detail = redact(str(exc), [cfg.api_key])[:240]
        out.update(category=cat, summary=describe_error(cat), detail=detail,
                   message=f"{describe_error(cat)} Detail: {detail}")
    except Exception as exc:  # noqa: BLE001 - reported, never raised into the page
        detail = redact(f"{type(exc).__name__}: {exc}"[:240], [cfg.api_key])
        out.update(category="invalid_response", summary=ERROR_CATEGORIES["invalid_response"], detail=detail,
                   message=f"{ERROR_CATEGORIES['invalid_response']} ({detail})")
    out["latency_ms"] = round((time.perf_counter() - started) * 1000)
    return out
