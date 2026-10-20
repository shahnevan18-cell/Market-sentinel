"""Orchestrator: plain Python that runs the three roles in order and enforces the rules.

Responsibilities
* Validate the event and re-detect it on data truncated at the event date
  (a live check that detection used no later information).
* Run the Market Investigator (LLM or rule-based) with a tool budget.
* Run any required check the investigator skipped, and record that it did so.
* Re-score the hypotheses on the complete evidence.
* Run the Risk Strategist.
* If an LLM step fails, record that the AI step did not complete, then
  produce clearly labelled rule-based output instead.
* Assemble the investigation record, with the full audit trail, and save it.
"""
from __future__ import annotations

from urllib.parse import urlparse

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

from agents.context import InvestigationContext
from agents.guidance import build_guidance
from agents.hypotheses import evaluate
from agents.investigation_tools import build_investigator_tools, build_strategist_tools
from agents.market_investigator import ACTOR as INVESTIGATOR, REQUIRED_TOOLS, MarketInvestigator
from agents.risk_strategist import ACTOR as STRATEGIST, RiskStrategist
from agents.sentinel_monitor import SentinelMonitor
from agents.tools import AuditEntry, AuditLog, ToolRegistry, to_jsonable
from providers.llm import PROVIDER_ERROR_CATEGORIES, classify_error, describe_error
from analytics.anomaly_detection import ScanResult, scan_universe
from config.settings import APP_VERSION, HISTORY_DIR, Settings
from providers.llm import LLMBackend
from providers.market_data import MarketDataset
from config.market import MARKET_FACTS, MARKET_ID, session_close_utc
from providers.news_data import NewsService

ORCHESTRATOR = "Orchestrator"
RULES_REASONS = {
    "selected": "selected by the user for this investigation.",
    "no_credentials": "no LLM credentials are configured on this deployment.",
    "config_problem": "the LLM settings could not be used (see the sidebar for the problem).",
    "switched_off": "the LLM is switched off in the settings (LLM_PROVIDER).",
    "locked": "the LLM is locked on this deployment until the passcode is entered.",
}
STAGES = [
    "Event validation",
    "Price and volume analysis",
    "Benchmark and peer comparison",
    "Public news retrieval",
    "Hypothesis evaluation",
    "Risk interpretation",
    "Final report",
]
STAGE_TOOLS = {
    "Price and volume analysis": {"calculate_returns_and_volatility", "calculate_abnormal_volume"},
    "Benchmark and peer comparison": {"compare_with_benchmark", "compare_with_peers"},
    "Public news retrieval": {"search_public_news"},
}
STRATEGIST_REQUIRED = ["get_risk_metrics", "get_portfolio_exposure"]


class InvestigationError(RuntimeError):
    pass


@dataclass
class InvestigationRecord:
    record_id: str
    created_at: str
    app_version: str
    event: dict
    historical: bool
    data: dict
    engine: dict
    validation: dict
    investigator: dict
    strategist: dict
    rubric: dict
    evidence: dict
    news: list
    news_statuses: list
    news_queries: list
    warnings: list
    unverified_figures: dict
    audit: list
    config: dict
    duration_s: float
    usage: dict = field(default_factory=dict)
    saved_to: str | None = None
    official_links: list = field(default_factory=list)   # NSE/BSE pages for manual verification (link-only)
    guidance: dict = field(default_factory=dict)         # evidence level, business summary and next action

    def as_dict(self) -> dict:
        return to_jsonable(asdict(self))


def _attr(entry, key):
    return entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)


def stage_progress(entries) -> dict[str, str]:
    """Derive the status of each workflow stage from steps that actually ran.

    Accepts AuditEntry objects (live run) or their dict form (saved record).
    """
    ok_tools = {_attr(e, "name") for e in entries if _attr(e, "kind") == "tool_call" and _attr(e, "status") == "ok"}
    status = {s: "pending" for s in STAGES}
    for e in entries:
        name, kind, st_ = _attr(e, "name"), _attr(e, "kind"), _attr(e, "status")
        if kind == "stage" and name in status:
            status[name] = "done" if st_ in ("ok", "info") else st_
    for stg, needed in STAGE_TOOLS.items():
        if needed <= ok_tools:
            status[stg] = "done"
        elif needed & ok_tools and status[stg] == "pending":
            status[stg] = "running"
    return status


def enforce_required_checks(ctx: InvestigationContext, audit: AuditLog) -> list[str]:
    """Run any required tool the investigator did not complete successfully."""
    done = audit.successful_tools()
    missing = [t for t in REQUIRED_TOOLS if t not in done]
    if not missing:
        audit.record(ORCHESTRATOR, "validation", "Required checks", "ok",
                     "All required checks were completed by the investigator.")
        return []
    registry = ToolRegistry(build_investigator_tools(ctx), audit, ORCHESTRATOR, budget=len(missing) + 2)
    for name in missing:
        audit.record(ORCHESTRATOR, "warning", "Required check skipped by agent", "warning",
                     f"The investigator did not complete '{name}'. The orchestrator is running it now.")
        registry.execute(name, {})
    return missing


def _history_path(record_id: str) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{record_id}.json"


def save_record(record: InvestigationRecord) -> Path:
    path = _history_path(record.record_id)
    record.saved_to = path.name               # file name only: no local folder names in shared records
    try:
        path.write_text(json.dumps(record.as_dict(), indent=2, default=str), encoding="utf-8")
    except OSError:
        record.saved_to = None
        raise
    return path


def list_records(limit: int = 50) -> list[dict]:
    """Saved investigations of this market (India, NSE), newest first.

    Records saved by the earlier US version of the app have no market id and are not listed; the files stay on
    disk untouched.
    """
    if not HISTORY_DIR.exists():
        return []
    rows = []
    for p in sorted(HISTORY_DIR.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        if len(rows) >= limit:
            break
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if (d.get("data") or {}).get("market_id") != MARKET_ID:
            continue
        rows.append({
            "path": str(p),
            "record_id": d.get("record_id"),
            "created_at": d.get("created_at"),
            "event_id": (d.get("event") or {}).get("event_id"),
            "ticker": (d.get("event") or {}).get("ticker"),
            "leading": (d.get("rubric") or {}).get("leading_label"),
            "confidence": (d.get("rubric") or {}).get("confidence"),
            "engine": (d.get("engine") or {}).get("summary"),
            "data_mode": (d.get("data") or {}).get("mode"),
            "historical": d.get("historical"),
        })
    return rows


def load_record(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_investigation(event_id: str, dataset: MarketDataset, settings: Settings, *,
                      backend: LLMBackend | None = None, scan: ScanResult | None = None,
                      historical: bool = False, news_service: NewsService | None = None,
                      progress: Callable[[AuditEntry], None] | None = None,
                      save: bool = True, rules_reason: str | None = None) -> InvestigationRecord:
    """Run one investigation. `backend` None means the rule-based protocol; `rules_reason` says why (selected,
    no_credentials, config_problem, switched_off or locked), so the record never confuses a choice with a failure."""
    started = time.perf_counter()
    audit = AuditLog()
    if progress:
        audit.listeners.append(progress)
    cfg = settings.analysis
    universe = dataset.universe
    warnings: list[str] = []

    # 1. Event validation ------------------------------------------------------
    full_scan = scan or SentinelMonitor(cfg).run(dataset).scan
    event = full_scan.event(event_id)
    if event is None:
        audit.record(ORCHESTRATOR, "stage", "Event validation", "error", f"Event {event_id} was not found.")
        raise InvestigationError(f"Event {event_id} is not among the detected events with the current thresholds.")
    date = pd.Timestamp(event["date"])
    asof = dataset.truncated(date)
    asof_scan = scan_universe(asof.frames, universe, cfg)
    re_event = asof_scan.event(event_id)
    lookahead_ok = re_event is not None and abs(re_event["priority_score"] - event["priority_score"]) < 1e-6
    feats = asof_scan.features.get(event["ticker"])
    baseline_n = float(feats.loc[date, "baseline_n"]) if feats is not None and date in feats.index else 0.0
    q = dataset.quality.get(event["ticker"])
    issues = [i.message for i in (q.issues if q else []) if i.level in ("warning", "error")]
    validation = {
        "event_found": True,
        "redetected_as_of_event_date": re_event is not None,
        "lookahead_check_passed": lookahead_ok,
        "score_full_data": event["priority_score"],
        "score_as_of_data": None if re_event is None else re_event["priority_score"],
        "baseline_observations": baseline_n,
        "min_required": cfg.min_obs,
        "data_mode": dataset.mode,
        "data_quality_status": q.status if q else "unknown",
        "data_quality_issues": issues,
        "partial_session": f"{date:%Y-%m-%d}" in [f"{d:%Y-%m-%d}" for d in dataset.partial_dates()],
    }
    status = "ok" if lookahead_ok and baseline_n >= cfg.min_obs else "warning"
    summary = (f"{event_id} validated. Re-detected using only data up to {date:%Y-%m-%d} with the same score "
               f"({event['priority_score']:.1f}); {int(baseline_n)} baseline observations.")
    if not lookahead_ok:
        summary = f"{event_id}: re-detection on as-of data did not reproduce the alert; investigate with caution."
        warnings.append(summary)
    if issues:
        warnings.append(f"Data-quality notes for {event['ticker']}: " + " | ".join(issues[:3]))
    if dataset.is_demo:
        warnings.append("Demonstration mode: all prices, volumes and announcements are synthetic and fictional.")
    audit.record(ORCHESTRATOR, "stage", "Event validation", status, summary, stage="Event validation",
                 output=to_jsonable(validation))

    cal = asof_scan.panel.calendar
    pos = cal.get_loc(date)
    prev_session = cal[pos - 1] if pos >= 1 else None
    cutoff = session_close_utc(date) if historical else None
    news_service = news_service or NewsService(settings, universe, dataset.mode, last_session=dataset.latest_bar())
    ctx = InvestigationContext(event=re_event or event, scan=asof_scan, dataset=asof, settings=settings,
                               news_service=news_service, historical=historical, prev_session=prev_session,
                               news_cutoff=cutoff)

    # 2-4. Investigation -----------------------------------------------------
    if backend is not None:
        host = urlparse(backend.cfg.base_url or "").netloc or backend.cfg.base_url
        audit.record(ORCHESTRATOR, "decision", "Engine selection", "ok",
                     f"Model-directed investigation: {backend.cfg.model} ({backend.cfg.vendor or backend.cfg.provider}, "
                     f"{host}); key read from {backend.cfg.key_source or 'the configured variable'}. The model chooses "
                     "the tools; every number comes from Python tools.",
                     output={"engine": "llm", "model": backend.cfg.model, "vendor": backend.cfg.vendor,
                             "endpoint_host": host, "key_source": backend.cfg.key_source})
    else:
        reason = rules_reason or "no_credentials"
        audit.record(ORCHESTRATOR, "decision", "Engine selection", "ok",
                     f"Rule-based protocol: {RULES_REASONS.get(reason, reason)} The same tools run in a fixed order.",
                     output={"engine": "rules", "reason": reason})
    llm_errors: list[str] = []
    investigator = MarketInvestigator(ctx, audit, backend, budget=settings.llm.max_tool_calls,
                                      max_turns=settings.llm.max_turns)
    inv_out = investigator.run()
    inv_engine = inv_out.engine
    if inv_out.engine == "llm" and inv_out.status == "completed":
        for a in (inv_out.submission or {}).get("news_assessments") or []:
            if a.get("source_id") in ctx.news_items:
                ctx.assessments[a["source_id"]] = {"relevance": a["relevance"], "rationale": a.get("rationale", ""),
                                                   "basis": "LLM judgement"}
    inv_submission = inv_out.submission
    if inv_out.engine == "llm" and inv_out.status != "completed":
        msg = f"The AI investigation did not complete ({inv_out.error}). Findings below come from the rule-based engine."
        llm_errors.append(msg)
        warnings.append(msg)
        audit.record(ORCHESTRATOR, "warning", "LLM investigation incomplete", "warning", msg)
        fallback = investigator.run_rules(actor="Market Investigator (rule-based fallback)")
        inv_submission = fallback.submission
        inv_engine = "rules (fallback after LLM failure)"
    # After any fallback, so a failed model call does not make the orchestrator repeat checks the fallback runs anyway.
    skipped = enforce_required_checks(ctx, audit)
    if skipped:
        warnings.append("Orchestrator ran required checks the investigator skipped: " + ", ".join(skipped))

    # 5. Hypothesis evaluation on the complete evidence ---------------------------
    ctx.rubric = evaluate(ctx)
    audit.record(ORCHESTRATOR, "stage", "Hypothesis evaluation", "ok",
                 f"Final rubric: {ctx.rubric.leading_label} ({ctx.rubric.confidence} confidence).",
                 stage="Hypothesis evaluation", output={"scores": {r.id: r.score for r in ctx.rubric.results}})
    if inv_engine == "llm" and not ctx.assessments and ctx.news_items:
        warnings.append("The LLM did not submit relevance judgements; news relevance uses the keyword heuristic.")

    # 6. Risk interpretation --------------------------------------------------------
    strategist = RiskStrategist(ctx, audit, backend)
    brief = {k: inv_submission.get(k) for k in ("summary", "key_findings", "unknowns")} if inv_submission else {}
    brief["rubric_leading"] = ctx.rubric.leading_label
    brief["rubric_confidence"] = ctx.rubric.confidence
    strat_out = strategist.run(brief)
    strat_engine = strat_out.engine
    strat_submission = strat_out.submission
    if strat_out.engine == "llm" and strat_out.status != "completed":
        msg = f"The AI risk interpretation did not complete ({strat_out.error}). Rule-based risk notes are shown instead."
        llm_errors.append(msg)
        warnings.append(msg)
        audit.record(ORCHESTRATOR, "warning", "LLM risk step incomplete", "warning", msg)
        strat_submission = strategist.run_rules(actor="Risk Strategist (rule-based fallback)").submission
        strat_engine = "rules (fallback after LLM failure)"
    done = audit.successful_tools()
    missing_risk = [t for t in STRATEGIST_REQUIRED if t not in done]
    if missing_risk:
        reg = ToolRegistry(build_strategist_tools(ctx), audit, ORCHESTRATOR, budget=len(missing_risk) + 1)
        for name in missing_risk:
            audit.record(ORCHESTRATOR, "warning", "Required check skipped by agent", "warning",
                         f"The strategist did not complete '{name}'. The orchestrator is running it now.")
            reg.execute(name, {})
    audit.record(ORCHESTRATOR, "stage", "Risk interpretation", "ok", "Risk interpretation recorded.",
                 stage="Risk interpretation")

    # 7. Final report ----------------------------------------------------------------
    unverified = {}
    for label, out in (("investigator", inv_out), ("strategist", strat_out)):
        if out.unverified_figures and out.status == "completed":
            unverified[label] = out.unverified_figures
    if unverified:
        warnings.append("Some figures written by the LLM could not be matched to tool outputs; they are flagged.")

    news = []
    for it in ctx.news_items.values():
        d = it.as_dict()
        rel, basis, why = ctx.final_relevance(it)
        d.update({"final_relevance": rel, "final_basis": basis, "final_rationale": why})
        news.append(d)
    order = {"direct": 0, "indirect": 1, "uncertain": 2, "unrelated": 3}
    news.sort(key=lambda d: (order.get(d["final_relevance"], 4), d.get("published_at") or ""))

    llm_label = backend.label if backend else None
    if not backend:
        engine_summary = "Rule-based (" + {"selected": "selected by the user", "no_credentials": "no LLM configured",
                                           "config_problem": "LLM configuration problem",
                                           "switched_off": "LLM switched off", "locked": "LLM locked"}.get(
            rules_reason or "no_credentials", "no LLM") + ")"
    elif inv_engine == "llm" and strat_engine == "llm":
        engine_summary = "LLM: " + llm_label
    elif inv_engine != "llm" and strat_engine != "llm":
        engine_summary = "Rule-based fallback after LLM failure"
    else:
        engine_summary = (f"Mixed ({llm_label}): investigator {'LLM' if inv_engine == 'llm' else 'rule-based fallback'}, "
                          f"strategist {'LLM' if strat_engine == 'llm' else 'rule-based fallback'}")
    error_categories = [classify_error(e) for e in llm_errors]
    if not backend:
        mode = f"rules_{rules_reason or 'no_credentials'}"
        mode_text = "Rule-based protocol: " + RULES_REASONS.get(rules_reason or "no_credentials", "")
    elif inv_engine == "llm" and strat_engine == "llm":
        mode, mode_text = "llm", (f"{backend.cfg.vendor or 'The LLM'} ({backend.cfg.model}) directed the investigation "
                                  "and the risk assessment: it chose the tools, read their results and submitted "
                                  "validated findings.")
    elif inv_engine != "llm" and strat_engine != "llm":
        first = error_categories[0] if error_categories else "provider_error"
        who = f"{backend.cfg.vendor or 'The LLM'} ({backend.cfg.model})"
        if first in PROVIDER_ERROR_CATEGORIES:
            mode, mode_text = "llm_provider_fallback", (f"{who} was called, but the provider returned an error, so the "
                                                        "rule-based protocol produced this report. Reason: "
                                                        + describe_error(first))
        else:
            mode, mode_text = "llm_failed", (f"{who} ran, but its output could not be used, so the rule-based "
                                             "protocol produced this report. Reason: " + describe_error(first))
    else:
        first = error_categories[0] if error_categories else "provider_error"
        mode, mode_text = "mixed", (f"{backend.cfg.vendor or 'The LLM'} ({backend.cfg.model}) directed part of the run; "
                                    f"the {'investigation' if inv_engine != 'llm' else 'risk step'} fell back to rules. "
                                    "Reason: " + describe_error(first))
    engine = {
        "requested": llm_label or "Rule-based reasoning engine (no LLM configured)",
        "investigator": inv_engine,
        "strategist": strat_engine,
        "llm_errors": llm_errors,
        "error_categories": error_categories,
        "summary": engine_summary,
        "mode": mode,
        "mode_text": mode_text,
        "llm_attempted": backend is not None,
        "model": backend.cfg.model if backend else None,
        "vendor": backend.cfg.vendor if backend else None,
        "key_source": backend.cfg.key_source if backend else None,
        "investigator_turns": inv_out.turns,
        "strategist_turns": strat_out.turns,
    }
    fresh = dataset.freshness()
    created = datetime.now(timezone.utc)
    safe_id = re.sub(r"[^A-Za-z0-9]", "-", event_id)
    record_id = f"{safe_id}_{created:%Y%m%dT%H%M%S}"
    record = InvestigationRecord(
        record_id=record_id,
        created_at=created.isoformat(timespec="seconds"),
        app_version=APP_VERSION,
        event=to_jsonable(ctx.event),
        historical=historical,
        data={
            "mode": dataset.mode,
            **MARKET_FACTS.as_dict(),
            "benchmark": universe.benchmark,
            "benchmark_name": universe.short_label(universe.benchmark),
            "symbol_currency": (dataset.meta[event["ticker"]].currency if event["ticker"] in dataset.meta else None),
            "provider": dataset.provider_label,
            "latest_bar_in_dataset": fresh.get("latest_bar"),
            "prices_used_up_to": f"{date:%Y-%m-%d}",
            "data_retrieved_at": fresh.get("newest_retrieval"),
            "dataset_loaded_at": dataset.loaded_at,
            "stale_symbols": fresh.get("stale_symbols"),
            "news_cutoff_utc": None if cutoff is None else cutoff.isoformat(),
        },
        engine=engine,
        validation=to_jsonable(validation),
        investigator=to_jsonable(inv_submission or {}),
        strategist=to_jsonable(strat_submission or {}),
        rubric=to_jsonable(ctx.rubric.as_dict()),
        evidence=to_jsonable(ctx.evidence),
        news=to_jsonable(news),
        news_statuses=to_jsonable([asdict(s) for s in ctx.news_statuses]),
        news_queries=list(ctx.news_queries),
        warnings=warnings,
        unverified_figures=to_jsonable(unverified),
        audit=[to_jsonable(e.as_dict()) for e in audit.entries],
        config=cfg.as_dict(),
        duration_s=round(time.perf_counter() - started, 2),
        usage={"investigator": inv_out.usage, "strategist": strat_out.usage},
        official_links=to_jsonable(ctx.official_links),
    )
    # 8. Action guidance: evidence level, business summary and one prioritised next action, derived from the
    # record itself so a saved report can always be re-checked against its own evidence.
    guidance = build_guidance(record.as_dict())
    act, cat = guidance["action"], guidance["catalyst"]
    audit.record(ORCHESTRATOR, "decision", "Action guidance", "ok",
                 f"Catalyst evidence: level {cat['level']} ({cat['label']}). Explanation status: "
                 f"{guidance['explanation']['status']}. Next action ({act['kind']}): {act['primary']}.",
                 output=to_jsonable({"catalyst_level": cat["level"], "catalyst_source_id": cat.get("source_id"),
                                     "action_kind": act["kind"], "evidence_refs": act["evidence"]}))
    audit.record(ORCHESTRATOR, "stage", "Final report", "ok", f"Report assembled as {record_id}.", stage="Final report")
    record.audit = [to_jsonable(e.as_dict()) for e in audit.entries]
    record.guidance = to_jsonable(guidance)
    if save:
        try:
            save_record(record)
        except OSError as exc:
            record.warnings.append(f"Could not save the investigation to history: {exc}")
    return record
