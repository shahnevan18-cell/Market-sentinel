"""Agent 2: Market Investigator.

With an LLM configured, the model plans the investigation: it decides which
tools to call (and with which arguments, such as custom peers or a refined
news query), reviews headline relevance and writes its findings. Without an
LLM, a fixed rule-based protocol calls the same tools in a set order and the
findings are written from templates. The report always states which engine ran.
"""
from __future__ import annotations

from agents.context import InvestigationContext
from agents.hypotheses import HYPOTHESES, evaluate
from agents.investigation_tools import build_investigator_tools
from agents.llm_loop import AgentOutcome, run_llm_agent
from agents.prompts import INVESTIGATOR_SYSTEM, investigator_user_prompt
from agents.schemas import SUBMIT_INVESTIGATION_SCHEMA, InvestigatorSubmission
from agents.tools import AuditLog, ToolRegistry
from providers.llm import LLMBackend

ACTOR = "Market Investigator"
REQUIRED_TOOLS = [
    "calculate_returns_and_volatility",
    "calculate_abnormal_volume",
    "compare_with_benchmark",
    "compare_with_peers",
    "search_public_news",
]
RULE_PLAN = [
    ("get_price_history", {"days": 15}),
    ("calculate_returns_and_volatility", {}),
    ("calculate_abnormal_volume", {}),
    ("compare_with_benchmark", {}),
    ("compare_with_peers", {}),
    ("get_market_context", {}),
    ("search_public_news", {}),
]


def _pct(x):
    if x is None:
        return "n/a"
    return f"{(0.0 if abs(x) < 0.00005 else x):+.2%}"


def _z(x):
    return "n/a" if x is None else f"{x:+.1f}"


def _f(x, fmt=".2f"):
    return "n/a" if x is None else format(x, fmt)


class MarketInvestigator:
    def __init__(self, ctx: InvestigationContext, audit: AuditLog, backend: LLMBackend | None = None,
                 budget: int = 14, max_turns: int = 10):
        self.ctx = ctx
        self.audit = audit
        self.backend = backend
        self.budget = budget
        self.max_turns = max_turns
        self.registry = ToolRegistry(build_investigator_tools(ctx), audit, ACTOR, budget)

    def mode_note(self) -> str:
        if self.ctx.historical:
            return (f"historical as-of investigation: prices end on {self.ctx.date:%Y-%m-%d} and news published after "
                    "that day's close is excluded.")
        return "live investigation of a detected event; news published after the event-day close is labelled as such."

    def run(self) -> AgentOutcome:
        if self.backend is None:
            return self.run_rules(actor=ACTOR)
        return run_llm_agent(
            backend=self.backend, actor=ACTOR, system=INVESTIGATOR_SYSTEM,
            user_prompt=investigator_user_prompt(self.ctx.event, self.mode_note(), self.budget),
            registry=self.registry, submit_name="submit_investigation",
            submit_description="Submit the final structured findings. Call once, after evaluate_hypotheses.",
            submit_schema=SUBMIT_INVESTIGATION_SCHEMA, model_cls=InvestigatorSubmission, audit=self.audit,
            allowed_numbers=lambda: allowed_numbers(self.ctx, self.audit), max_turns=self.max_turns,
            stage="Investigation",
        )

    def run_rules(self, actor: str = ACTOR) -> AgentOutcome:
        registry = self.registry if actor == ACTOR else ToolRegistry(build_investigator_tools(self.ctx), self.audit,
                                                                     actor, self.budget)
        done = self.audit.successful_tools()
        for name, args in RULE_PLAN:
            if actor != ACTOR and name in done:
                continue
            registry.execute(name, args)
        for item in list(self.ctx.news_items.values())[:3]:
            if item.relevance in ("direct", "uncertain"):
                registry.execute("retrieve_source_details", {"source_id": item.source_id})
        registry.execute("evaluate_hypotheses", {})
        submission = rules_submission(self.ctx)
        return AgentOutcome(actor=actor, engine="rules", status="completed", submission=submission,
                            tool_calls=registry.calls_used)


def allowed_numbers(ctx: InvestigationContext, audit: AuditLog) -> list[float]:
    from agents.grounding import collect_numbers
    nums: list[float] = []
    collect_numbers(ctx.event, nums)
    collect_numbers(ctx.evidence, nums)
    for e in audit.entries:
        if e.output is not None:
            collect_numbers(e.output, nums)
    collect_numbers(ctx.scan.config.as_dict(), nums)
    for it in ctx.news_items.values():
        collect_numbers(it.headline, nums)
    return nums


def rules_submission(ctx: InvestigationContext) -> dict:
    """Template-based findings built only from tool outputs (no LLM)."""
    ev = ctx.evidence
    rv = ev.get("calculate_returns_and_volatility") or {}
    vol = ev.get("calculate_abnormal_volume") or {}
    bm = ev.get("compare_with_benchmark") or {}
    pc = ev.get("compare_with_peers") or {}
    mc = ev.get("get_market_context") or {}
    rubric = ctx.rubric or evaluate(ctx)
    name, ticker, date = ctx.event.get("name"), ctx.ticker, f"{ctx.date:%Y-%m-%d}"
    ret, z = rv.get("simple_return"), rv.get("robust_z_return")
    bench = ctx.universe.short_label(ctx.universe.benchmark)
    nse = ctx.universe.get(ticker)
    label = nse.exchange_symbol if nse else ticker

    s = []
    if ret is not None and z is not None:
        side = "above" if z > 0 else "below"
        s.append(f"{name} (NSE: {label}) returned {_pct(ret)} on {date}, {abs(z):.1f} robust standard deviations "
                 f"{side} its recent typical daily move.")
    if bm.get("available"):
        s.append(f"{bench} returned {_pct(bm.get('benchmark_return'))}. With a beta of {_f(bm.get('beta'))}, the market "
                 f"model expected {_pct(bm.get('expected_return'))}, leaving an abnormal return of "
                 f"{_pct(bm.get('abnormal_return'))} (z {_z(bm.get('abnormal_z'))}).")
    if pc.get("available") and pc.get("sector_index_name"):
        s.append(f"Configured peers had a median return of {_pct(pc.get('peer_median_return'))} and the "
                 f"{pc.get('sector_index_name')} sector index returned {_pct(pc.get('sector_index_return'))}.")
    elif pc.get("available"):
        s.append(f"Configured peers had a median return of {_pct(pc.get('peer_median_return'))}; no sector index is "
                 "configured for this group, so no sector-index comparison was made.")
    elif pc.get("sector_index_name"):
        s.append(f"No peer comparison was possible; the {pc.get('sector_index_name')} sector index returned "
                 f"{_pct(pc.get('sector_index_return'))}.")
    else:
        s.append("No peer or sector-index comparison was possible for this stock: no other watchlist stock belongs to "
                 "its group and no sector index is configured.")
    if vol.get("available") and vol.get("volume_ratio") is not None:
        s.append(f"Volume was {_f(vol.get('volume_ratio'), '.1f')}x its 60-day median.")
    direct = [i for i in ctx.news_items.values() if ctx.final_relevance(i)[0] == "direct" and i.timing == "in_window"]
    if ctx.news_all_failed() or not ctx.news_available():
        s.append("News evidence unavailable: no news source could be searched.")
    elif direct:
        first = direct[0]
        s.append(f"{len(direct)} direct item(s) fell inside the information window, for example "
                 f"\"{first.headline[:140]}\" ({first.publisher or first.provider}).")
    else:
        s.append(f"{len(ctx.news_items)} news item(s) were retrieved, but none was judged a direct, timely explanation. "
                 "No public explanation was found in the sources searched.")
    s.append(rubric.conclusion)

    findings = []
    if z is not None:
        findings.append(f"Return {_pct(ret)} with robust z {_z(z)} against the previous {ctx.scan.config.lookback} sessions.")
    if vol.get("available") and vol.get("volume_ratio") is not None:
        findings.append(f"Volume {_f(vol.get('volume_ratio'), '.1f')}x the 60-day median (robust z of log volume "
                        f"{_z(vol.get('robust_z_log_volume'))}).")
    if bm.get("available"):
        findings.append(f"Market-adjusted abnormal return {_pct(bm.get('abnormal_return'))} (z {_z(bm.get('abnormal_z'))}), "
                        f"beta {_f(bm.get('beta'))}, R-squared {_f(bm.get('r_squared'))}.")
    if pc.get("available"):
        idx = (f"{pc.get('sector_index_name')} z {_z(pc.get('sector_index_z'))}" if pc.get("sector_index_name")
               else "no sector index for this group")
        findings.append(f"Return relative to peer median {_pct(pc.get('relative_return'))} (z {_z(pc.get('relative_z'))}); "
                        f"{idx}.")
    if mc.get("available"):
        findings.append(f"{(mc.get('share_up') or 0):.0%} of watchlist stocks rose that day; {mc.get('n_events')} "
                        "alert(s) across the watchlist.")
    findings.append(f"News: {len(ctx.news_items)} item(s), {len(direct)} judged direct inside the window.")

    notes = {}
    for res in rubric.results:
        sup = [c.evidence for c in res.criteria if c.effect == "supports"][:2]
        con = [c.evidence for c in res.criteria if c.effect == "contradicts"][:2]
        mis = [c.evidence for c in res.criteria if c.effect == "missing"][:1]
        parts = []
        if sup:
            parts.append("For: " + " ".join(sup))
        if con:
            parts.append("Against: " + " ".join(con))
        if mis:
            parts.append("Missing: " + " ".join(mis))
        notes[res.id] = " ".join(parts) or "No criteria fired."

    unknowns = ["Intraday timing of the move relative to any announcement (the analysis uses daily data)."]
    if ctx.news_items:
        unknowns.append("Article text was not read; relevance rests on headlines, publishers and publication times.")
    if not ctx.dataset.is_demo:
        unknowns.append("Official NSE/BSE announcements were not searched automatically (link-only); a filing on the "
                        "exchange website could explain the move and should be checked manually.")
    if ctx.news_all_failed() or not ctx.news_available():
        unknowns.append("Whether any public news explains the move, because news sources were unavailable.")
    if not bm.get("available"):
        unknowns.append("The market-adjusted return, because beta could not be estimated.")
    unknowns.append("Order flow, F&O activity, bulk and block deals and FII/DII flows are not observed by this system.")
    if ctx.historical:
        unknowns.append("Information published after the event-day close was deliberately excluded (as-of mode).")

    follow = []
    if any(i.source_type == "news_headline" for i in direct):
        follow.append("Open the linked article to confirm its content and publication time.")
    if not ctx.dataset.is_demo:
        follow.append("Check the company's announcements on the NSE corporate filings page for the event window "
                      "(link in the evidence section).")
    lead = rubric.leading
    if lead == "H1":
        follow.append("Review macro releases (RBI policy, inflation data) and index-level news for the event date.")
    elif lead == "H2":
        follow.append("Check sector-level drivers (regulation, commodity prices, a large peer's news) and whether the "
                      "sector move persists.")
    elif lead == "H4":
        follow.append("Look for after-hours announcements, bulk and block deal reports and F&O activity around the event.")
    elif lead == "H3":
        follow.append("Compare the disclosed figures with expectations (consensus estimates, earlier guidance) to judge "
                      "whether the size of the reaction fits the news.")
    else:
        follow.append("Gather more evidence before attributing the move; re-run once more data is available.")
    follow.append("Compare the next 1 to 5 sessions with the market model to see whether the move continues or reverses.")
    return {
        "summary": " ".join(s),
        "key_findings": findings,
        "hypothesis_notes": notes,
        "unknowns": unknowns,
        "follow_up_checks": follow,
        "news_assessments": [],
    }
