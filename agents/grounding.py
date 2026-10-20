"""Numeric grounding check for LLM-written text.

Every figure in a narrative written by the LLM must match a number produced by
a tool (allowing for rounding and for decimals shown as percentages). Figures
that match nothing are flagged as unverified. Dates, clock times, small counts
and numbers that appear in source headlines are allowed.

Indian conventions are understood: rupee prefixes (₹, Rs, Rs., INR), Indian
digit grouping (12,34,567 and 1,00,00,000) and the units lakh and crore, so
"₹4,200 crore" in a headline also allows 42,000,000,000.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.])(?:Rs\.?\s?|INR\s?|₹\s?)?[-+]?[$₹]?"
                       r"(\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})+,\d{3}|\d+)(\.\d+)?\s?"
                       r"(%|x\b|bps?\b|million\b|mn\b|m\b|billion\b|bn\b|b\b|thousand\b|k\b|crores?\b|cr\b|"
                       r"lakhs?\b|lacs?\b)?",
                       re.IGNORECASE)
SCALE = {"million": 1e6, "mn": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9, "thousand": 1e3, "k": 1e3,
         "crore": 1e7, "crores": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5}
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)?\b")
_MONTHS = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
WRITTEN_DATE_RE = re.compile(r"\b\d{1,2}\s" + _MONTHS + r"(?:,?\s\d{4})?\b|\b" + _MONTHS + r"\s\d{1,2}(?:,\s?\d{4})?\b")
ITEM_RE = re.compile(r"\b(?:Item|H)\s?\d+(?:\.\d+)?\b", re.IGNORECASE)
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\s?(?:am|pm|AM|PM|UTC|GMT|IST|hrs))?\b")
DAY_WINDOW_RE = re.compile(r"\b\d+[- ](?:day|days|week|weeks|month|months|year|years|session|sessions|trading)\b",
                           re.IGNORECASE)


def collect_numbers(obj: Any, out: list[float] | None = None) -> list[float]:
    """All numeric values found anywhere in a nested structure (strings are scanned too)."""
    out = [] if out is None else out
    if obj is None or isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        if not (isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj))):
            out.append(float(obj))
        return out
    if isinstance(obj, str):
        for m in NUMBER_RE.finditer(obj):
            try:
                value = float((m.group(1) + (m.group(2) or "")).replace(",", ""))
            except ValueError:
                continue
            out.append(value)
            unit = (m.group(3) or "").lower()
            if unit in SCALE:                 # "₹4,200 crore" in a headline also allows 42,000,000,000
                out.append(value * SCALE[unit])
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
        return out
    if isinstance(obj, (list, tuple, set)):
        for v in obj:
            collect_numbers(v, out)
    return out


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _matches(value: float, decimals: int, allowed: Iterable[float], is_percent: bool, scale: float = 1.0) -> bool:
    tol = (0.5 * 10 ** (-decimals)) * scale + 1e-9
    v = abs(value) * scale
    for a in allowed:
        candidates = (abs(a), abs(a) * 100.0) if is_percent or abs(a) < 1.5 else (abs(a),)
        for c in candidates:
            if abs(c - v) <= tol:
                return True
    return False


def ungrounded_numbers(text: str, allowed: list[float]) -> list[str]:
    if not text:
        return []
    cleaned = DATE_RE.sub(" ", text)
    cleaned = WRITTEN_DATE_RE.sub(" ", cleaned)  # "30 Sep 2026" and "Sep 30, 2026" are dates, not figures
    cleaned = TIME_RE.sub(" ", cleaned)          # clock times such as "15:30 IST" are not figures
    cleaned = ITEM_RE.sub(" ", cleaned)
    cleaned = DAY_WINDOW_RE.sub(" ", cleaned)
    flagged = []
    for m in NUMBER_RE.finditer(cleaned):
        whole, frac, unit = m.group(1), m.group(2) or "", (m.group(3) or "").lower()
        token = whole + frac
        try:
            value = float(token.replace(",", ""))
        except ValueError:
            continue
        if not frac and value <= 10 and unit not in SCALE:
            continue                      # small counts such as "two peers" or "3 sources"
        if not frac and 1900 <= value <= 2100 and not unit:
            continue                      # years
        if _matches(value, _decimals(token), allowed, unit == "%", SCALE.get(unit, 1.0)):
            continue
        flagged.append(m.group(0).strip())
    return list(dict.fromkeys(flagged))


def check_submission(fields: dict[str, Any], allowed: list[float]) -> dict[str, list[str]]:
    """Return {field_name: [unverified figures]} for every text field in a submission."""
    problems: dict[str, list[str]] = {}

    def visit(name, value):
        if isinstance(value, str):
            bad = ungrounded_numbers(value, allowed)
            if bad:
                problems.setdefault(name, []).extend(bad)
        elif isinstance(value, dict):
            for k, v in value.items():
                visit(f"{name}.{k}", v)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                visit(f"{name}[{i}]", v)

    for key, val in fields.items():
        visit(key, val)
    return problems
