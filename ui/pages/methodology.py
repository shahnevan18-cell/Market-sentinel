"""Methodology and data: sources, formulas, thresholds, the agent design and limitations."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from agents.hypotheses import LEAD_THRESHOLD, MARGIN_THRESHOLD
from agents.investigation_tools import build_investigator_tools, build_strategist_tools
from config.market import DISCLOSURE_TERMS_NOTE, HOLIDAY_SOURCE, OFFICIAL_DISCLOSURE_LINKS, TIMINGS_SOURCE, session_text
from ui import components as c
from ui.state import app_data, get_settings

ARCH_DOT = """
digraph G {
  rankdir=LR; bgcolor="transparent"; pad=0.2; nodesep=0.35; ranksep=0.45;
  node [shape=box, style="rounded,filled", fillcolor="#0F1B2E", color="#1D2C45", fontcolor="#E3E9F2",
        fontname="Helvetica", fontsize=11, margin="0.18,0.1"];
  edge [color="#6C7FA0", fontcolor="#8B9AB2", fontname="Helvetica", fontsize=9, arrowsize=0.7];
  data [label="Market data (NSE)\\nyfinance / cache / demo"];
  news [label="Evidence sources\\nGoogle News India, Yahoo\\nheadlines; NSE/BSE links\\n(manual check)"];
  mon [label="Sentinel Monitor\\nrule-based agent", color="#2BB3A3"];
  orch [label="Orchestrator\\nlimits, validation,\\nrequired checks, audit", color="#E9A23B"];
  inv [label="Market Investigator\\nLLM tool loop or\\nrule-based protocol", color="#45C4E0"];
  tools [label="Python tools\\nreturns, z-scores, beta,\\npeers, news, rubric"];
  strat [label="Risk Strategist\\nLLM or rule-based", color="#45C4E0"];
  rep [label="Report and\\naudit trail"];
  data -> mon [label="prices"]; mon -> orch [label="ranked events"];
  orch -> inv [label="event"]; inv -> tools [label="tool calls"]; tools -> inv [label="results"];
  news -> tools; data -> tools;
  inv -> orch [label="validated findings"]; orch -> strat [label="findings + rubric"];
  strat -> tools [label="risk tools"]; strat -> orch [label="risk assessment"]; orch -> rep;
}
"""


def render() -> None:
    ds, mon = app_data()
    c.page_header("Methodology and data",
                  "Where the data comes from, how every number is calculated, how alerts are scored and what makes "
                  "the workflow agentic.", ds)
    settings = get_settings()
    cfg = settings.analysis
    tabs = st.tabs(["Data sources", "Statistical methods", "Scoring and thresholds", "Agentic workflow",
                    "Data quality", "Limitations"])

    with tabs[0]:
        register = pd.DataFrame([
            ("Yahoo Finance via yfinance (NSE)", "Daily OHLC, adjusted close, volume, splits, dividends, currency and "
             "exchange time zone for NSE shares (.NS), NIFTY 50 (^NSEI), NSE sector indices and SENSEX (^BSESN)",
             "Unofficial open-source client; no key", "Not an official Yahoo or NSE feed. Data can be delayed or "
             "corrected; Yahoo may throttle requests. Personal and educational use. Every symbol is checked by "
             "scripts/validate_symbols.py (rows returned, currency INR, exchange, time zone)."),
            ("Local cache (data/cache)", "Last successful download per symbol", "Automatic",
             "Kept with its original retrieval time; marked stale when a refresh fails."),
            ("Google News RSS search, India edition", "Headlines, publisher, publication time, link",
             "Public RSS feed (hl=en-IN, gl=IN)", "Low-volume, non-commercial use. Coverage and ranking are "
             "controlled by Google; Indian business publishers dominate the results."),
            ("Yahoo Finance headlines via yfinance", "Latest headlines for a ticker", "Unofficial",
             "Only the most recent headlines; cannot reconstruct older windows."),
            ("NSE and BSE corporate filings pages", "Company announcements, results, board meetings",
             "Link-only (manual verification)", DISCLOSURE_TERMS_NOTE),
            ("SEBI directory of corporate filings", "Where each filing type is published on NSE and BSE",
             "Link-only", "Reference page; nothing is downloaded."),
            ("NSE market timings and holiday circulars", "Session times (" + session_text() + ") and the "
             "trading-holiday table", "Copied by hand into config/market.py",
             f"Sources: {TIMINGS_SOURCE}; {HOLIDAY_SOURCE}. The table covers 2024 to 2026 and must be updated yearly."),
            ("NIFTY 50 constituents (NSE Indices)", "Choice of the 25-stock watchlist", "Manual check",
             "Checked against NSE Indices press releases on 20 Oct 2026 (Wipro left the index on 30 Sep 2026)."),
            ("Synthetic demonstration generator", "Fictional India-themed .DEMO securities and announcements",
             "Built in, fixed random seed", "For offline demonstrations only. Never mixed with live data."),
            ("LLM provider (optional)", "Tool selection, headline relevance, narrative",
             "Anthropic API key or an OpenAI-compatible key (for example Gemini)",
             "A chat subscription does not include API access."),
        ], columns=["Source", "Used for", "Access", "Limits and terms"])
        st.table(register.set_index("Source"))
        f = ds.freshness()
        st.markdown(f"This session: **{ds.mode}** mode, provider {ds.provider_label}. Latest session in the data "
                    f"{f.get('latest_bar')}. Symbol statuses: "
                    + ", ".join(f"{n} {k}" for k, n in (f.get("status_counts") or {}).items())
                    + f". LLM: {settings.llm.describe()}.")
        st.caption("Bar dates are NSE trading sessions (Asia/Kolkata). Publication, retrieval and run times are shown "
                   "in IST and stored in UTC. A daily bar retrieved before 16:15 IST on its own day is treated as "
                   "incomplete and excluded from detection. Prices are in Indian rupees; the currency each symbol "
                   "reports is checked, never relabelled.")
        st.markdown("Official pages for manual checks: " + "; ".join(
            f"[{link['label']}]({link['url']})" for link in OFFICIAL_DISCLOSURE_LINKS) + ".")

    with tabs[1]:
        st.markdown("##### Returns\n\nPrices are not comparable across stocks; returns are, because they scale each "
                    "change by the starting price. All returns use the adjusted close (dividends, splits and bonus "
                    "issues removed when the provider records them). Returns do not depend on the currency. Volume is "
                    "the provider's share volume. Series are aligned on the NIFTY 50's trading dates, and no return is "
                    "computed across a missing session such as a trading suspension.")
        st.latex(r"r_t = \frac{P_t}{P_{t-1}} - 1 \qquad \ell_t = \ln\frac{P_t}{P_{t-1}}")
        st.markdown(f"##### Robust z-score\n\nBaseline = the previous {cfg.lookback} sessions, ending the day before the "
                    f"test day, so no future data is used. At least {cfg.min_obs} observations are required.")
        st.latex(r"z_t = \frac{x_t - \operatorname{median}(x_{t-L},\dots,x_{t-1})}{1.4826 \cdot \operatorname{MAD}(x_{t-L},\dots,x_{t-1})}")
        st.markdown("The median and the median absolute deviation (MAD) barely move when a few extreme days enter the "
                    "window, unlike the mean and standard deviation. The factor 1.4826 makes MAD comparable to a "
                    "standard deviation for normal data. Volume is tested on the log scale because it is right-skewed.")
        st.markdown(f"##### Market model and abnormal return\n\nAlpha and beta are estimated by OLS over the previous "
                    f"{cfg.beta_window} sessions (minimum {cfg.beta_min_obs}).")
        st.latex(r"r_{i,t} = \alpha + \beta\, r_{m,t} + \varepsilon_t \qquad AR_t = r_{i,t} - (\hat\alpha + \hat\beta\, r_{m,t}) \qquad z^{AR}_t = AR_t / \hat\sigma_\varepsilon")
        u = ds.universe
        indexed = ", ".join(f"{g} ({u.sector_index_names.get(g, idx).split(' (')[0]})"
                            for g, idx in u.sector_indices.items())
        peer_only = ", ".join(g for g in u.sectors if g not in u.sector_indices)
        st.markdown("##### Peer-relative return\n\nReturn minus the median return of the other watchlist stocks in the "
                    "same peer group, then a robust z-score of that difference. Groups with a sector index are also "
                    f"compared with it: {indexed or 'none in this universe'}. These groups have no sector index, "
                    f"and the report says so: {peer_only or 'none'}.")
        st.markdown(f"##### Volatility regime ratio\n\nStandard deviation of the last {cfg.vol_short} returns (including "
                    f"the event day) divided by that of the {cfg.vol_long} returns before them. Annualised volatility "
                    "multiplies daily standard deviation by the square root of 252 (NSE has roughly 245 to 250 "
                    "sessions a year, so this is a convention). All volatility shown is historical.")
        st.markdown(f"##### Value at Risk\n\nOne-day historical VaR at {cfg.var_confidence:.0%} is the loss exceeded on "
                    f"{1 - cfg.var_confidence:.0%} of the previous {cfg.var_window} sessions. Parametric VaR assumes "
                    "normal returns: VaR = z x sigma.")
        st.latex(r"\mathrm{VaR}_{95\%} = -Q_{0.05}(r) \qquad \mathrm{HHI} = \sum_i w_i^2 \qquad N_{eff} = 1/\mathrm{HHI}")

    with tabs[2]:
        st.markdown("##### Alert rule\n\nA stock-day is an alert when any test fires.")
        thr = pd.DataFrame([
            ("Price test", f"|robust z of return| >= {cfg.z_price}"),
            ("Market-relative test", f"|z of abnormal return| >= {cfg.z_abnormal}"),
            ("Volume test", f"robust z of log volume >= {cfg.z_volume} (one-sided)"),
        ], columns=["Test", "Condition"])
        st.dataframe(thr, hide_index=True, width="stretch")
        st.markdown("##### Priority score\n\nEach component is normalised to 0-1 (capped), weighted and summed to a 0-100 "
                    "scale. The score ranks attention; it is not a probability.")
        st.latex(r"S = 100\Big(w_p \min(\tfrac{|z_r|}{6},1) + w_a \min(\tfrac{|z_{AR}|}{6},1) + w_v \min(\tfrac{\max(z_V,0)}{6},1) + w_\sigma \min(\tfrac{\max(\rho-1,0)}{2},1)\Big)")
        w = pd.DataFrame([("Abnormal price move", cfg.w_price), ("Market-relative move", cfg.w_abnormal),
                          ("Abnormal volume", cfg.w_volume), ("Volatility regime shift", cfg.w_vol_regime)],
                         columns=["Component", "Weight"])
        st.dataframe(w, hide_index=True, width="stretch")
        st.markdown(f"Severity bands: Critical >= {cfg.severity_critical:.0f}, High >= {cfg.severity_high:.0f}, "
                    f"Moderate >= {cfg.severity_moderate:.0f}, otherwise Low.")
        st.markdown(f"##### Hypothesis rubric\n\nFive fixed explanations, each scored 0-100 from documented criteria (open "
                    f"any investigation's Hypotheses tab to see every criterion and its points). A conclusion is stated "
                    f"only when the leading score is at least {LEAD_THRESHOLD:.0f} and at least {MARGIN_THRESHOLD:.0f} "
                    "points ahead of the next. Confidence is High when the lead is 70 or more, 25 or more points "
                    "ahead and no core input is missing; otherwise Moderate; inconclusive cases are Low.")
        st.markdown("##### News timing and relevance\n\nThe information window runs from the previous session's 15:30 "
                    "IST close to the event-day close, so results declared after market hours count for the next "
                    "session. Only items inside it can count as an explanation; anything published after the close is "
                    "shown but cannot explain that day's move. Without an LLM, a keyword rule labels each item: a "
                    "headline naming the company (with aliases such as RIL, HUL or L&T, and with other companies "
                    "such as Reliance Power or ITC Hotels excluded) together with a cause word (results, order, "
                    "provisions, SEBI, RBI, USFDA, block deal, downgrade) is direct; a headline that only describes the "
                    "move is uncertain; tips, live price pages and holdings reports are unrelated. With an LLM, the "
                    "model's judgement replaces the keyword label and its reason is shown. Strong direct evidence for "
                    "company-specific news (H3) needs a company announcement or headlines from at least two "
                    "publishers; a single headline earns half the points. In live mode NSE/BSE announcements are "
                    "link-only, so live evidence comes from independent publishers; the demo's fictional announcements "
                    "show the announcement path. Publication time is kept apart from the date of the event a source "
                    "reports. News is evidence that may explain a move, never proof that it did.")
        st.markdown("##### Evidence levels and the next action\n\n"
                    "Each investigation labels its catalyst evidence. **A, verified company event**: a retrieved "
                    "company announcement inside the window (only the demo's fictional announcements, because live "
                    "NSE/BSE pages are link-only). **B, potential catalyst, not yet verified**: a headline names the "
                    "company and a cause inside the window; the app shows the exact headline, publisher, times and "
                    "link, and says the article and the filing were not read. The candidate is the subject most "
                    "independent publishers report; social posts, tips and forecast pages are ignored. **C, no "
                    "identified catalyst**. The Summary then gives one next action chosen by fixed rules: unreliable "
                    "data first, then a failed news search, then an unresolved tie, then the leading explanation's "
                    "weakest link. It states why, the steps, what would change the assessment and when to hold back, "
                    "and it is never buy or sell advice.")

    with tabs[3]:
        st.graphviz_chart(ARCH_DOT, width="stretch")
        st.markdown(
            "What makes it agentic: the Market Investigator receives a goal (explain this alert) and a set of tools, "
            "and with an LLM configured it decides which tools to call, with which arguments, and when it has enough "
            "evidence. It can, for example, choose its own peer list or refine a news query after seeing results. "
            "Its outputs are validated against schemas and a numeric grounding check, and the orchestrator runs any "
            "required check it skipped. The Risk Strategist then works from the validated findings.")
        st.markdown(
            "What is deliberately not left to the LLM: anomaly detection (the Sentinel Monitor is rule-based so "
            "alerts are reproducible), every number (computed by Python tools), and the hypothesis scores (a fixed "
            "rubric). Without an LLM key the same tools run in a fixed order and the report says so.")
        if mon is not None and not mon.events.empty:
            sample = mon.events.iloc[0].to_dict()
            from agents.context import InvestigationContext
            from providers.news_data import NewsService
            ctx = InvestigationContext(event=sample, scan=mon.scan, dataset=ds, settings=settings,
                                       news_service=NewsService(settings, ds.universe, ds.mode))
            rows = [(t.name, "Market Investigator", t.description) for t in build_investigator_tools(ctx)]
            rows += [(t.name, "Risk Strategist", t.description) for t in build_strategist_tools(ctx)]
            st.dataframe(pd.DataFrame(rows, columns=["Tool", "Used by", "What it does"]), hide_index=True,
                         width="stretch", column_config={"What it does": st.column_config.TextColumn(width="large")})

    with tabs[4]:
        rows = []
        for sym, q in ds.quality.items():
            rows.append({"Symbol": sym, "Status": q.status, "Observations": q.n_obs, "First": q.first_date,
                         "Last": q.last_date, "Issues": " | ".join(f"{i.level}: {i.message}" for i in q.issues),
                         "Cleaning actions": " | ".join(q.actions)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=480,
                     column_config={"Issues": st.column_config.TextColumn(width="large")})
        st.caption("Checks: missing and duplicated dates, non-positive prices, missing or zero volume, close outside "
                   "the high-low range, single-day moves of 25% or more (often an unadjusted bonus issue, split or "
                   "demerger), splits, bars on weekends or NSE holidays (special sessions such as Muhurat trading are "
                   "kept), currency (INR expected), staleness against the NSE calendar and incomplete sessions before "
                   "16:15 IST. Prices are never interpolated or invented.")

    with tabs[5]:
        st.markdown(
            "- A statistical alert says a move was unusual for this stock. It does not say why, and many unusual moves "
            "have no discoverable public cause.\n"
            "- Hypothesis scores measure fit with the evidence gathered, not causation or probability.\n"
            "- Daily data cannot show whether news came before or after the move within a session.\n"
            "- Headline relevance is judged from titles and timing; article text is not read.\n"
            "- Yahoo data via yfinance is unofficial, may be delayed or revised against NSE's official bhavcopy, and "
            "may be throttled.\n"
            "- NSE and BSE announcements are not retrieved automatically (link-only), so a filing on the exchange "
            "website can explain a move the app reports as unexplained. Check the official pages.\n"
            "- Google News results depend on Google's ranking; absence of a headline is not proof of no news.\n"
            "- Beta from 120 sessions can be unstable; NIFTY sector indices are free-float weighted and include the "
            "stock itself. Several peer groups have no sector index or no peer at all.\n"
            "- The NSE holiday table covers 2024 to 2026; later years need the new circular.\n"
            "- A corporate action the provider does not adjust (for example a demerger) appears as a large move and is "
            "flagged for checking rather than corrected.\n"
            "- Historical volatility and VaR describe the past and understate tail risk in stressed markets.\n"
            "- Replay outcomes on live data are descriptive; there is no ground truth for a correct alert.\n"
            "- This is an educational prototype. It does not give investment advice, does not trade and does not "
            "predict prices.")
