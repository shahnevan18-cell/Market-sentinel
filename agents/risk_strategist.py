"""Agent 3: Risk Strategist.

Turns the validated investigation into qualified conclusions: risk
implications, monitoring thresholds, what would change the conclusion and next
steps. All risk numbers come from Python functions (VaR, volatility, stress
tests on an illustrative portfolio). No trading advice is produced.
"""
from __future__ import annotations

from agents.context import InvestigationContext
from agents.investigation_tools import build_strategist_tools
from agents.llm_loop import AgentOutcome, run_llm_agent
from agents.market_investigator import allowed_numbers
from agents.prompts import STRATEGIST_SYSTEM, strategist_user_prompt
from agents.schemas import SUBMIT_RISK_SCHEMA, StrategistSubmission
from agents.tools import AuditLog, ToolRegistry
from providers.llm import LLMBackend

ACTOR = "Risk Strategist"


def _pct(x, signed=False):
    if x is None:
        return "n/a"
    if abs(x) < 0.00005:          # avoid printing "-0.00%"
        x = 0.0
    return f"{x:+.2%}" if signed else f"{x:.2%}"


def _is_held(ctx: InvestigationContext) -> bool:
    expo = ctx.evidence.get("get_portfolio_exposure") or {}
    return bool(expo.get("holding_weight"))


class RiskStrategist:
    def __init__(self, ctx: InvestigationContext, audit: AuditLog, backend: LLMBackend | None = None,
                 budget: int = 6, max_turns: int = 6):
        self.ctx = ctx
        self.audit = audit
        self.backend = backend
        self.budget = budget
        self.max_turns = max_turns
        self.registry = ToolRegistry(build_strategist_tools(ctx), audit, ACTOR, budget)

    def run(self, investigator_submission: dict | None) -> AgentOutcome:
        if self.backend is None:
            return self.run_rules(ACTOR)
        return run_llm_agent(
            backend=self.backend, actor=ACTOR, system=STRATEGIST_SYSTEM,
            user_prompt=strategist_user_prompt(self.ctx.event, investigator_submission, self.budget),
            registry=self.registry, submit_name="submit_risk_assessment",
            submit_description="Submit the final risk assessment. Call once.",
            submit_schema=SUBMIT_RISK_SCHEMA, model_cls=StrategistSubmission, audit=self.audit,
            allowed_numbers=lambda: allowed_numbers(self.ctx, self.audit), max_turns=self.max_turns,
            stage="Risk interpretation",
        )

    def run_rules(self, actor: str = ACTOR) -> AgentOutcome:
        registry = self.registry if actor == ACTOR else ToolRegistry(build_strategist_tools(self.ctx), self.audit,
                                                                     actor, self.budget)
        done = self.audit.successful_tools()
        for name, args in (("get_investigation_summary", {}), ("get_risk_metrics", {}), ("get_portfolio_exposure", {})):
            if actor != ACTOR and name in done:
                continue
            registry.execute(name, args)
        ret = self.ctx.event.get("ret") or 0.0
        sign = -1.0 if ret < 0 else 1.0
        lead = self.ctx.rubric.leading if self.ctx.rubric else None
        if _is_held(self.ctx):
            registry.execute("run_stress_scenario", {"scope": "security", "shock_pct": 10.0 * sign})
        else:
            # Not held: a shock to the stock alone changes nothing, so test its sector instead.
            registry.execute("run_stress_scenario", {"scope": "sector", "shock_pct": 5.0 * sign})
        if lead == "H1":
            registry.execute("run_stress_scenario", {"scope": "market", "shock_pct": -5.0})
        elif lead == "H2" and _is_held(self.ctx):
            registry.execute("run_stress_scenario", {"scope": "sector", "shock_pct": -5.0})
        return AgentOutcome(actor=actor, engine="rules", status="completed", submission=rules_risk(self.ctx),
                            tool_calls=registry.calls_used)


def rules_risk(ctx: InvestigationContext) -> dict:
    ev = ctx.evidence
    risk = ev.get("get_risk_metrics") or {}
    expo = ev.get("get_portfolio_exposure") or {}
    vol = ev.get("calculate_abnormal_volume") or {}
    stresses = ev.get("run_stress_scenario") or []
    rubric = ctx.rubric
    t = ctx.ticker
    lead_label = rubric.leading_label if rubric else "unknown"
    conf = rubric.confidence if rubric else "Low"

    summary = [f"{ctx.event.get('name')} ({t}) produced a {ctx.event.get('severity', '').lower()} priority alert "
               f"on {ctx.date:%Y-%m-%d} (score {ctx.event.get('priority_score', 0):.0f} of 100)."]
    summary.append(f"The leading assessment is '{lead_label}' with {conf.lower()} confidence. This is a judgement of fit "
                   "with the evidence, not a proven cause.")
    var_pre = risk.get("hist_var_1d_before_event")
    mult = risk.get("event_move_as_multiple_of_prior_var")
    if var_pre is not None and mult is not None:
        summary.append(f"Before the event, the one-day 95% historical VaR was {_pct(var_pre)}; the event-day move was "
                       f"{mult:.1f} times that level.")
    if expo and expo.get("holding_weight"):
        summary.append(f"In the illustrative portfolio the holding weight is {_pct(expo.get('holding_weight'))}, and the "
                       f"event day contributed {_pct(expo.get('event_day_contribution_to_portfolio_return'), True)} to its return.")
    elif expo:
        summary.append(f"{t} is not held in the illustrative portfolio, so the event did not change its value directly; "
                       f"the portfolio's {expo.get('sector')} exposure is {_pct(expo.get('sector_weight'))}.")

    implications = []
    ratio = risk.get("vol_regime_ratio")
    if ratio is not None:
        if ratio >= 1.5:
            implications.append(f"Recent 10-day volatility ({_pct(risk.get('vol_10d_annualised'))} annualised) is "
                                f"{ratio:.2f} times the earlier 60-day level, a higher-volatility regime than before.")
        else:
            implications.append(f"Recent 10-day volatility is {ratio:.2f} times the earlier 60-day level, so the event "
                                "has not yet shifted the volatility regime much.")
    if mult is not None and mult >= 2:
        implications.append("A move of this size relative to VaR suggests historical VaR understated the tail for this "
                            "security; risk limits based on it may need review.")
    if expo.get("holding_weight"):
        implications.append(f"Sector exposure in the illustrative portfolio: {_pct(expo.get('sector_weight'))} in "
                            f"{expo.get('sector')}, so a sector-wide repeat would matter more than the single holding.")
    elif expo.get("sector_weight"):
        implications.append(f"The illustrative portfolio would feel this only if the move spread to its {expo.get('sector')} "
                            f"holdings ({_pct(expo.get('sector_weight'))} of the portfolio).")
    for st in stresses[:2]:
        o = st.get("outputs") or {}
        implications.append(f"Hypothetical stress, {st.get('scenario')}: illustrative portfolio return "
                            f"{_pct(o.get('portfolio_return'), True)}.")

    monitoring = []
    if var_pre is not None:
        monitoring.append(f"Flag the next sessions if the absolute daily return exceeds the pre-event one-day VaR of "
                          f"{_pct(var_pre)}.")
    if vol.get("baseline_median_volume"):
        monitoring.append(f"Flag if volume stays above twice the 60-day median of {vol['baseline_median_volume']:,.0f} "
                          "shares for more than two sessions.")
    if risk.get("vol_prior_60d_annualised") is not None:
        monitoring.append(f"Track whether 10-day realised volatility returns toward the earlier 60-day level of "
                          f"{_pct(risk.get('vol_prior_60d_annualised'))} annualised.")
    monitoring.append("Re-run the investigation after the next close to include post-event trading.")

    change = {
        "H1": ["A company announcement on NSE/BSE or a company-specific headline inside the window would shift "
               "weight toward H3.",
               "A peer group that diverged from the market would point to a sector driver (H2)."],
        "H2": ["Evidence that one large peer's news drove the sector would refine the explanation.",
               "If the stock keeps diverging from peers in later sessions, H3 or H4 become more likely."],
        "H3": ["If the linked item turns out to be unrelated or published after the move, support for H3 falls.",
               "A sector-wide reaction in later sessions would suggest a broader driver (H2)."],
        "H4": ["A timely announcement on the NSE or BSE corporate filings pages (for example results declared after "
               "market hours) would move the assessment to H3.",
               "A reported bulk or block deal, or an index rebalancing date, would explain volume without new "
               "information about the company."],
        "H5": ["Successful news retrieval, longer price history or estimable beta would allow a clearer assessment."],
    }
    lead_id = rubric.leading if rubric else "H5"
    next_steps = ["Confirm the timing of any linked item against the trading session.",
                  "Check whether peers or the sector index move on the following session.",
                  "Review the audit trail and data-quality notes before relying on the conclusion."]
    return {
        "executive_summary": " ".join(summary),
        "risk_implications": implications,
        "monitoring_suggestions": monitoring,
        "what_would_change_conclusion": change.get(lead_id, change["H5"]),
        "next_steps": next_steps,
    }
