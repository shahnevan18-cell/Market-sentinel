"""Schemas for the structured outputs the LLM must return.

The LLM submits its findings by calling a `submit_*` tool whose input schema
is given below. The orchestrator then validates the submission with Pydantic.
An invalid submission is sent back once with the validation errors; if it is
still invalid, the LLM step is recorded as failed.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

Relevance = Literal["direct", "indirect", "uncertain", "unrelated"]
HYPOTHESIS_IDS = ("H1", "H2", "H3", "H4", "H5")


def _trim_list(values, limit=8, length=500):
    out = []
    for v in values or []:
        s = str(v).strip()
        if s:
            out.append(s[:length])
    return out[:limit]


class NewsAssessment(BaseModel):
    source_id: str = Field(max_length=80)
    relevance: Relevance
    rationale: str = Field(max_length=400)


class InvestigatorSubmission(BaseModel):
    summary: str = Field(min_length=20, max_length=1500)
    key_findings: list[str] = Field(default_factory=list)
    hypothesis_notes: dict[str, str] = Field(default_factory=dict)
    unknowns: list[str] = Field(default_factory=list)
    follow_up_checks: list[str] = Field(default_factory=list)
    news_assessments: list[NewsAssessment] = Field(default_factory=list)

    @field_validator("key_findings", "unknowns", "follow_up_checks", mode="before")
    @classmethod
    def _lists(cls, v):
        return _trim_list(v)

    @field_validator("hypothesis_notes")
    @classmethod
    def _notes(cls, v):
        bad = [k for k in v if k not in HYPOTHESIS_IDS]
        if bad:
            raise ValueError(f"hypothesis_notes keys must be among {HYPOTHESIS_IDS}; got {bad}")
        return {k: str(t)[:600] for k, t in v.items()}


class StrategistSubmission(BaseModel):
    executive_summary: str = Field(min_length=20, max_length=2000)
    risk_implications: list[str] = Field(default_factory=list)
    monitoring_suggestions: list[str] = Field(default_factory=list)
    what_would_change_conclusion: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    @field_validator("risk_implications", "monitoring_suggestions", "what_would_change_conclusion", "next_steps",
                     mode="before")
    @classmethod
    def _lists(cls, v):
        return _trim_list(v)


_STR_LIST = {"type": "array", "items": {"type": "string", "maxLength": 500}, "maxItems": 8}

SUBMIT_INVESTIGATION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 1500,
                    "description": "Plain-language summary of what the evidence shows. Numbers only if copied from tools."},
        "key_findings": {**_STR_LIST, "description": "Up to 8 short findings, each tied to a tool result."},
        "hypothesis_notes": {"type": "object", "description": "Short note per hypothesis id (H1..H5).",
                             "properties": {h: {"type": "string", "maxLength": 600} for h in HYPOTHESIS_IDS},
                             "additionalProperties": False},
        "unknowns": {**_STR_LIST, "description": "What remains unknown or could not be checked."},
        "follow_up_checks": {**_STR_LIST, "description": "Concrete checks an analyst should run next."},
        "news_assessments": {"type": "array", "maxItems": 30, "items": {
            "type": "object", "properties": {
                "source_id": {"type": "string", "maxLength": 80},
                "relevance": {"type": "string", "enum": ["direct", "indirect", "uncertain", "unrelated"]},
                "rationale": {"type": "string", "maxLength": 400}},
            "required": ["source_id", "relevance", "rationale"], "additionalProperties": False}},
    },
    "required": ["summary", "key_findings", "unknowns", "follow_up_checks"],
    "additionalProperties": False,
}

SUBMIT_RISK_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string", "maxLength": 2000},
        "risk_implications": {**_STR_LIST, "description": "Implications for volatility, concentration or sector exposure."},
        "monitoring_suggestions": {**_STR_LIST, "description": "Thresholds or checks to monitor, using tool values."},
        "what_would_change_conclusion": {**_STR_LIST, "description": "Evidence that would change the conclusion."},
        "next_steps": {**_STR_LIST, "description": "What a market analyst should investigate next."},
    },
    "required": ["executive_summary", "risk_implications", "monitoring_suggestions",
                 "what_would_change_conclusion", "next_steps"],
    "additionalProperties": False,
}
