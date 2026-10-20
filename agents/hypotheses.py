"""Transparent hypothesis rubric.

Five candidate explanations are scored from 0 to 100 with fixed, documented
criteria. Each criterion either supports (+points), contradicts (-points),
is neutral, or is missing because the evidence was unavailable. The rubric is
deterministic: the same evidence always gives the same scores. The only
qualitative input is the relevance label of each news item, which comes from
the LLM investigator when one is configured (and is logged with its
rationale) or from the keyword heuristic otherwise.

Scores measure how well each explanation fits the evidence gathered. They are
not probabilities and they do not establish cause.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from providers.news_data import COMPANY_ANNOUNCEMENT_TYPES

HYPOTHESES = {
    "H1": "Broad-market movement",
    "H2": "Sector-wide movement",
    "H3": "Company-specific news or announcement",
    "H4": "Unusual trading activity without an identified public explanation",
    "H5": "Insufficient evidence to classify the event",
}

LEAD_THRESHOLD = 45.0     # leading explanation must reach this score
MARGIN_THRESHOLD = 10.0   # and be this many points ahead of the next one


@dataclass
class Criterion:
    hypothesis: str
    name: str
    effect: str              # supports | contradicts | neutral | missing
    points: float
    evidence: str


@dataclass
class HypothesisResult:
    id: str
    label: str
    score: float
    verdict: str
    criteria: list[Criterion] = field(default_factory=list)
    cap_note: str | None = None


@dataclass
class HypothesisEvaluation:
    results: list[HypothesisResult]
    leading: str
    leading_label: str
    conclusion: str
    confidence: str
    margin: float
    confidence_explanation: str
    inconclusive: bool
    inputs: dict
    news_basis: str

    def as_dict(self) -> dict:
        return asdict(self)

    def result(self, hid: str) -> HypothesisResult | None:
        return next((r for r in self.results if r.id == hid), None)


def _v(d: dict | None, key: str):
    if not d:
        return None
    val = d.get(key)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def _z(x):
    return "n/a" if x is None else f"{x:+.1f}"


def _pct(x):
    if x is None:
        return "n/a"
    return f"{(0.0 if abs(x) < 0.00005 else x):+.2%}"


def _share(x):
    return "n/a" if x is None else f"{x:.0%}"


def verdict_for(score: float) -> str:
    if score >= 70:
        return "Strongly supported"
    if score >= 50:
        return "Supported"
    if score >= 25:
        return "Weakly supported"
    return "Not supported"


def _sign(x):
    return 0 if x is None or x == 0 else (1 if x > 0 else -1)


def gather_inputs(ctx) -> dict:
    ev = ctx.evidence
    rv = ev.get("calculate_returns_and_volatility") or {}
    vol = ev.get("calculate_abnormal_volume") or {}
    bm = ev.get("compare_with_benchmark") or {}
    pc = ev.get("compare_with_peers") or {}
    mc = ev.get("get_market_context") or {}
    ret = _v(rv, "simple_return") if rv else ctx.event.get("ret")
    share_up = _v(mc, "share_up")
    share_down = _v(mc, "share_down")
    breadth_same = None
    if ret is not None and share_up is not None:
        breadth_same = share_up if ret > 0 else share_down
    items = list(ctx.news_items.values())
    direct = []
    official = []
    llm_reviewed = 0
    for it in items:
        rel, basis, _ = ctx.final_relevance(it)
        if basis != "keyword heuristic":
            llm_reviewed += 1
        if rel == "direct" and it.timing == "in_window":
            direct.append(it)
            if it.source_type in COMPANY_ANNOUNCEMENT_TYPES:
                official.append(it)
    q = ctx.dataset.quality.get(ctx.ticker)
    dq_warnings = [i.message for i in (q.issues if q else []) if i.level in ("warning", "error")]
    return {
        "ret": ret,
        "z_ret": _v(rv, "robust_z_return") if rv else ctx.event.get("z_ret"),
        "z_volume": _v(vol, "robust_z_log_volume") if vol else ctx.event.get("z_volume"),
        "volume_ratio": _v(vol, "volume_ratio"),
        "z_mkt": _v(bm, "benchmark_z"),
        "mkt_ret": _v(bm, "benchmark_return"),
        "beta": _v(bm, "beta"),
        "z_abn": _v(bm, "abnormal_z"),
        "abnormal_ret": _v(bm, "abnormal_return"),
        "explained_ratio": _v(bm, "market_explained_ratio"),
        "r2": _v(bm, "r_squared"),
        "z_sector": _v(pc, "sector_index_z"),
        "sector_ret": _v(pc, "sector_index_return"),
        "sector_index": (pc.get("sector_index_name") or pc.get("sector_index")) if pc else None,
        "sector_index_configured": ctx.universe.sector_index_for(ctx.ticker) is not None,
        "peers_configured": bool(ctx.universe.peers_of(ctx.ticker)),
        "share_same": _v(pc, "share_same_direction"),
        "share_same_z2": _v(pc, "share_same_direction_z2"),
        "z_rel": _v(pc, "relative_z"),
        "rel_ret": _v(pc, "relative_return"),
        "n_peers": _v(pc, "n_peers"),
        "breadth_same": breadth_same,
        "n_news_items": len(items),
        "n_direct_in_window": len(direct),
        "n_official_in_window": len(official),
        "n_direct_publishers": len({(i.publisher or i.provider or "").strip().lower() for i in direct
                                    if i.source_type == "news_headline"}),
        "direct_ids": [i.source_id for i in direct],
        "news_searched": ctx.news_searched(),
        "news_available": ctx.news_available(),
        # True when no news source returned a usable answer: all failed, or none was searched (for example news
        # disabled in settings). Link-only official pages are not a search, so they never count as one.
        "news_all_failed": ctx.news_all_failed() or not ctx.news_available(),
        "llm_reviewed_items": llm_reviewed,
        "data_quality_warnings": dq_warnings,
        "benchmark": ctx.universe.short_label(ctx.universe.benchmark),
    }


def evaluate(ctx) -> HypothesisEvaluation:
    x = gather_inputs(ctx)
    crit: dict[str, list[Criterion]] = {h: [] for h in HYPOTHESES}

    def add(h, name, effect, points, evidence):
        crit[h].append(Criterion(h, name, effect, float(points), evidence))

    ret, z_mkt, z_abn, z_sec, z_rel, z_vol, z_ret = (x["ret"], x["z_mkt"], x["z_abn"], x["z_sector"],
                                                     x["z_rel"], x["z_volume"], x["z_ret"])
    s_ret = _sign(ret)
    bench = x["benchmark"]
    sector_wide = (z_sec is not None and abs(z_sec) >= 2 and _sign(x["sector_ret"]) == s_ret
                   and x["share_same_z2"] is not None and x["share_same_z2"] >= 0.5)
    market_wide = (z_mkt is not None and abs(z_mkt) >= 2 and _sign(x["mkt_ret"]) == s_ret
                   and x["breadth_same"] is not None and x["breadth_same"] >= 0.75)
    x["sector_wide_move"] = sector_wide
    x["market_wide_move"] = market_wide

    # H1 broad market ------------------------------------------------------
    if z_mkt is None:
        add("H1", "Benchmark move was itself unusual", "missing", 0, "Benchmark z-score unavailable.")
    elif abs(z_mkt) >= 2 and _sign(x["mkt_ret"]) == s_ret:
        add("H1", "Benchmark move was itself unusual", "supports", 35,
            f"{bench} return {_pct(x['mkt_ret'])} (robust z {_z(z_mkt)}) moved in the same direction.")
    elif abs(z_mkt) >= 2:
        add("H1", "Benchmark moved the opposite way", "contradicts", -30,
            f"{bench} return {_pct(x['mkt_ret'])} (z {_z(z_mkt)}) went the other way.")
    elif abs(z_mkt) < 1:
        add("H1", "Benchmark move was itself unusual", "contradicts", -10,
            f"{bench} return {_pct(x['mkt_ret'])} (z {_z(z_mkt)}) was an ordinary day.")
    else:
        add("H1", "Benchmark move was itself unusual", "neutral", 0, f"{bench} z {_z(z_mkt)} is moderate.")

    if ret is not None and abs(ret) < 0.005:
        add("H1", "Market model explains the move", "neutral", 0,
            f"The price move ({_pct(ret)}) is too small to attribute meaningfully.")
    elif x["explained_ratio"] is None:
        add("H1", "Market model explains the move", "missing", 0, "Beta or expected return unavailable.")
    elif x["explained_ratio"] >= 0.5:
        add("H1", "Market model explains the move", "supports", 25,
            f"Expected return from beta x market return covers {x['explained_ratio']:.0%} of the actual move.")
    elif x["explained_ratio"] <= 0.2:
        add("H1", "Market model explains the move", "contradicts", -15,
            f"Beta x market return explains only {x['explained_ratio']:.0%} of the move.")
    else:
        add("H1", "Market model explains the move", "neutral", 0,
            f"Beta x market return explains {x['explained_ratio']:.0%} of the move.")

    if z_abn is None:
        add("H1", "Stock is ordinary after market adjustment", "missing", 0, "Abnormal return z unavailable.")
    elif abs(z_abn) < 2:
        add("H1", "Stock is ordinary after market adjustment", "supports", 20,
            f"Market-adjusted return z is {_z(z_abn)}, within normal range.")
    elif abs(z_abn) >= 3:
        add("H1", "Stock is ordinary after market adjustment", "contradicts", -30,
            f"Market-adjusted return z is {_z(z_abn)}: the stock moved far more than the market explains.")
    else:
        add("H1", "Stock is ordinary after market adjustment", "neutral", 0, f"Market-adjusted z {_z(z_abn)}.")

    if x["breadth_same"] is None:
        add("H1", "Most of the watchlist moved the same way", "missing", 0, "Breadth unavailable.")
    elif x["breadth_same"] >= 0.75:
        add("H1", "Most of the watchlist moved the same way", "supports", 20,
            f"{_share(x['breadth_same'])} of watchlist stocks moved in the same direction.")
    elif x["breadth_same"] <= 0.5:
        add("H1", "Most of the watchlist moved the same way", "contradicts", -10,
            f"Only {_share(x['breadth_same'])} of watchlist stocks moved in the same direction.")
    else:
        add("H1", "Most of the watchlist moved the same way", "neutral", 0,
            f"{_share(x['breadth_same'])} of watchlist stocks moved in the same direction.")

    # H2 sector -------------------------------------------------------------
    index_name = x["sector_index"] or "the sector index"
    if z_sec is None and not x["sector_index_configured"]:
        add("H2", "Sector index move was unusual", "missing", 0,
            "No sector index is configured for this peer group, so no sector-index comparison was performed; "
            "H2 rests on the peer comparison alone.")
    elif z_sec is None:
        add("H2", "Sector index move was unusual", "missing", 0, f"{index_name} data unavailable for this date.")
    elif abs(z_sec) >= 2 and _sign(x["sector_ret"]) == s_ret:
        add("H2", "Sector index move was unusual", "supports", 30,
            f"{index_name} returned {_pct(x['sector_ret'])} (z {_z(z_sec)}) in the same direction.")
    elif abs(z_sec) < 1:
        add("H2", "Sector index move was unusual", "contradicts", -10,
            f"{index_name} returned {_pct(x['sector_ret'])} (z {_z(z_sec)}), an ordinary day.")
    else:
        add("H2", "Sector index move was unusual", "neutral", 0, f"{index_name} z {_z(z_sec)}.")

    if x["share_same_z2"] is None and not x["peers_configured"]:
        add("H2", "Peers moved together", "missing", 0,
            "No other watchlist stock belongs to this peer group, so no peer comparison was made.")
    elif x["share_same_z2"] is None:
        add("H2", "Peers moved together", "missing", 0, "No peer data.")
    elif x["share_same_z2"] >= 0.5:
        add("H2", "Peers moved together", "supports", 25,
            f"{_share(x['share_same_z2'])} of peers moved the same way with |z| >= 2.")
    elif x["share_same"] is not None and x["share_same"] <= 0.34:
        add("H2", "Peers moved together", "contradicts", -15,
            f"Only {_share(x['share_same'])} of peers moved in the same direction.")
    else:
        add("H2", "Peers moved together", "neutral", 0,
            f"{_share(x['share_same'])} of peers moved the same way, {_share(x['share_same_z2'])} strongly.")

    if z_rel is None:
        add("H2", "Stock in line with peers", "missing", 0, "Peer-relative z unavailable.")
    elif abs(z_rel) < 2:
        add("H2", "Stock in line with peers", "supports", 25,
            f"Return relative to peer median has z {_z(z_rel)}, in line with peers.")
    elif abs(z_rel) >= 3 and sector_wide:
        add("H2", "Stock in line with peers", "neutral", 0,
            f"The stock moved further than its peers (relative z {_z(z_rel)}) but in the same direction as a strong "
            "sector move.")
    elif abs(z_rel) >= 3:
        add("H2", "Stock in line with peers", "contradicts", -30,
            f"Return relative to peer median has z {_z(z_rel)}: the stock diverged from its peers.")
    else:
        add("H2", "Stock in line with peers", "neutral", 0, f"Peer-relative z {_z(z_rel)}.")

    if z_sec is not None and z_mkt is not None:
        gap = abs(z_sec) - abs(z_mkt)
        if gap >= 1.5:
            add("H2", "Sector moved more than the market", "supports", 20,
                f"Sector z {_z(z_sec)} exceeds market z {_z(z_mkt)} by {gap:.1f}.")
        elif abs(z_mkt) >= 2 and gap < 0.5:
            add("H2", "Sector moved more than the market", "contradicts", -20,
                f"Sector z {_z(z_sec)} is no larger than market z {_z(z_mkt)}; the market explains the sector move.")
        else:
            add("H2", "Sector moved more than the market", "neutral", 0,
                f"Sector z {_z(z_sec)} vs market z {_z(z_mkt)}.")
    else:
        add("H2", "Sector moved more than the market", "missing", 0, "Sector or market z unavailable.")

    # Stock-specific strength used by H3 and H4 ------------------------------
    candidates = [abs(v) for v in (z_abn, z_rel) if v is not None]
    specific = min(candidates) if candidates else None
    news_ok = x["news_available"]
    news_failed = x["news_all_failed"]
    volume_only = (z_ret is not None and abs(z_ret) < 2 and z_vol is not None and z_vol >= 3)

    # H3 company-specific news ----------------------------------------------
    if specific is None:
        add("H3", "Move is specific to this stock", "missing", 0, "Market- and peer-adjusted measures unavailable.")
    elif specific >= 3 and sector_wide:
        add("H3", "Move is specific to this stock", "supports", 10,
            f"Adjusted measures are large (z {_z(z_abn)}, relative z {_z(z_rel)}) but occur within a strong "
            "sector-wide move, so part of the divergence may be a larger reaction to the same sector driver.")
    elif specific >= 3:
        add("H3", "Move is specific to this stock", "supports", 30,
            f"Both market-adjusted (z {_z(z_abn)}) and peer-relative (z {_z(z_rel)}) measures are extreme.")
    elif specific >= 2:
        add("H3", "Move is specific to this stock", "supports", 15,
            f"Market-adjusted z {_z(z_abn)} and peer-relative z {_z(z_rel)} are elevated.")
    elif specific < 1.5:
        add("H3", "Move is specific to this stock", "contradicts", -30,
            f"After adjusting for market or peers the move is ordinary (smallest |z| {specific:.1f}).")
    else:
        add("H3", "Move is specific to this stock", "neutral", 0, f"Smallest stock-specific |z| {specific:.1f}.")

    if news_failed:
        add("H3", "Direct company evidence in the information window", "missing", 0,
            "News sources could not be searched, so company-specific evidence cannot be confirmed.")
    elif x["n_official_in_window"] >= 1 or x["n_direct_publishers"] >= 2:
        add("H3", "Direct company evidence in the information window", "supports", 40,
            f"{x['n_direct_in_window']} item(s) judged direct were published between the previous close "
            f"and the event-day close ({x['n_official_in_window']} company announcement(s), headlines from "
            f"{x['n_direct_publishers']} publisher(s)).")
    elif x["n_direct_in_window"] >= 1:
        add("H3", "Direct company evidence in the information window", "supports", 20,
            "One direct headline from a single publisher inside the window: weaker evidence than a company "
            "announcement or several independent sources.")
    else:
        add("H3", "Direct company evidence in the information window", "contradicts", -15,
            f"{x['n_news_items']} item(s) retrieved, none judged a direct, timely explanation.")

    if x["n_official_in_window"] >= 1:
        add("H3", "Company announcement in the window", "supports", 15,
            "A company announcement falls inside the information window.")
    elif x["news_searched"] and not x["news_all_failed"]:
        add("H3", "Company announcement in the window", "neutral", 0,
            "No company announcement was retrieved. Official NSE/BSE announcements are link-only in this app, so "
            "check them manually through the links in the evidence section.")
    else:
        add("H3", "Company announcement in the window", "neutral", 0, "No company announcement in the window.")

    if z_vol is None:
        add("H3", "Abnormal volume accompanies the move", "missing", 0, "Volume z unavailable.")
    elif z_vol >= 3:
        add("H3", "Abnormal volume accompanies the move", "supports", 15,
            f"Volume z {_z(z_vol)}: information events usually bring heavy trading.")
    elif z_vol < 1:
        add("H3", "Abnormal volume accompanies the move", "contradicts", -5, f"Volume z {_z(z_vol)} is ordinary.")
    else:
        add("H3", "Abnormal volume accompanies the move", "neutral", 0, f"Volume z {_z(z_vol)}.")

    # H4 unusual trading without explanation --------------------------------
    if z_vol is None:
        add("H4", "Trading volume was abnormal", "missing", 0, "Volume z unavailable.")
    elif z_vol >= 3:
        add("H4", "Trading volume was abnormal", "supports", 30,
            f"Volume z {_z(z_vol)} ({x['volume_ratio']:.1f}x the median)." if x["volume_ratio"] else f"Volume z {_z(z_vol)}.")
    elif z_vol >= 2:
        add("H4", "Trading volume was abnormal", "supports", 15, f"Volume z {_z(z_vol)}.")
    elif z_vol < 1:
        add("H4", "Trading volume was abnormal", "contradicts", -10, f"Volume z {_z(z_vol)} is ordinary.")
    else:
        add("H4", "Trading volume was abnormal", "neutral", 0, f"Volume z {_z(z_vol)}.")

    if volume_only:
        add("H4", "Stock-specific trading pattern", "supports", 15,
            f"Heavy volume (z {_z(z_vol)}) without a large price move (return z {_z(z_ret)}).")
    elif specific is not None and specific >= 2.5 and sector_wide:
        add("H4", "Stock-specific trading pattern", "neutral", 0,
            f"The stock-specific component (smallest |z| {specific:.1f}) sits inside a strong sector-wide move.")
    elif specific is not None and specific >= 2.5:
        add("H4", "Stock-specific trading pattern", "supports", 20,
            f"Price move is stock-specific (smallest |z| {specific:.1f}).")
    elif specific is not None and specific < 1.5:
        add("H4", "Stock-specific trading pattern", "contradicts", -10,
            f"The move is ordinary after market or peer adjustment (smallest |z| {specific:.1f}).")
    else:
        add("H4", "Stock-specific trading pattern", "neutral", 0, "Stock-specific measures are moderate or missing.")

    if news_failed:
        add("H4", "No public explanation found despite searching", "missing", 0,
            "Sources could not be searched, so the absence of news cannot be established.")
    elif x["n_official_in_window"] >= 1 or x["n_direct_publishers"] >= 2:
        add("H4", "No public explanation found despite searching", "contradicts", -40,
            "Direct, timely evidence was found (a company announcement or several independent headlines).")
    elif x["n_direct_in_window"] >= 1:
        add("H4", "No public explanation found despite searching", "contradicts", -20,
            "One direct headline from a single publisher was found.")
    elif (sector_wide or (market_wide and (specific is None or specific < 2.5))) and not volume_only:
        add("H4", "No public explanation found despite searching", "supports", 10,
            "No direct company item was found, but none is needed when a broad market or sector move explains "
            "the event.")
    else:
        add("H4", "No public explanation found despite searching", "supports", 30,
            f"Searched sources returned {x['n_news_items']} item(s), none a direct, timely explanation.")

    if z_mkt is None and z_sec is None:
        add("H4", "Market and sector do not explain it", "missing", 0, "Market and sector z unavailable.")
    elif (z_mkt is None or abs(z_mkt) < 2) and (z_sec is None or abs(z_sec) < 2):
        add("H4", "Market and sector do not explain it", "supports", 20,
            f"Market z {_z(z_mkt)} and sector z {_z(z_sec)} were ordinary.")
    else:
        add("H4", "Market and sector do not explain it", "contradicts", -15,
            f"Market z {_z(z_mkt)} or sector z {_z(z_sec)} was unusual.")

    # Score H1-H4 ---------------------------------------------------------------
    results = {}
    for h in ("H1", "H2", "H3", "H4"):
        raw = sum(c.points for c in crit[h])
        score = float(np.clip(raw, 0, 100))
        cap_note = None
        if h == "H3" and news_failed and score > 50:
            score, cap_note = 50.0, "Capped at 50 because news sources could not be searched."
        if h == "H4" and news_failed and score > 40:
            score, cap_note = 40.0, "Capped at 40 because the absence of news could not be established."
        results[h] = HypothesisResult(h, HYPOTHESES[h], score, verdict_for(score), crit[h], cap_note)

    ranked = sorted(results.values(), key=lambda r: -r.score)
    top, second = ranked[0], ranked[1]
    margin = top.score - second.score

    # A measure counts as missing only when it should exist: groups with no sector index or no peer in the
    # watchlist are a design limit of the universe, recorded in the H2 criteria, not a data failure.
    core = ["beta"] + (["z_rel"] if x["peers_configured"] else []) + (["z_sector"] if x["sector_index_configured"] else [])
    missing_core = [k for k in core if x[k] is None]
    h5 = []
    if margin < MARGIN_THRESHOLD:
        h5.append(Criterion("H5", "Leading explanations are close", "supports", 30,
                            f"{top.label} ({top.score:.0f}) and {second.label} ({second.score:.0f}) are within {margin:.0f} points."))
    if news_failed:
        h5.append(Criterion("H5", "News sources unavailable", "supports", 25,
                            "No news source could be searched."))
    if missing_core:
        h5.append(Criterion("H5", "Core measures missing", "supports", 20,
                            "Missing: " + ", ".join(missing_core)))
    if x["data_quality_warnings"]:
        h5.append(Criterion("H5", "Data-quality warnings", "supports", 15,
                            f"{len(x['data_quality_warnings'])} warning(s) for this security."))
    if top.score < LEAD_THRESHOLD:
        h5.append(Criterion("H5", "No explanation reaches the evidence threshold", "supports", 10,
                            f"Best score is {top.score:.0f}, below {LEAD_THRESHOLD:.0f}."))
    if not h5:
        h5.append(Criterion("H5", "Evidence is sufficient", "contradicts", 0,
                            "Core measures are present and one explanation leads clearly."))
    h5_score = float(np.clip(sum(c.points for c in h5), 0, 100))
    results["H5"] = HypothesisResult("H5", HYPOTHESES["H5"], h5_score, verdict_for(h5_score), h5)

    inconclusive = top.score < LEAD_THRESHOLD or margin < MARGIN_THRESHOLD
    if inconclusive:
        leading, leading_label = "H5", HYPOTHESES["H5"]
        confidence = "Low"
        if top.score < LEAD_THRESHOLD:
            conclusion = (f"No explanation reaches the {LEAD_THRESHOLD:.0f}-point evidence threshold (best: {top.label}, "
                          f"{top.score:.0f}). The available evidence does not identify a reliable explanation.")
        else:
            conclusion = (f"The evidence does not separate {top.label} ({top.score:.0f}) from {second.label} "
                          f"({second.score:.0f}). Treat the cause as unresolved.")
        conf_expl = (f"Low: the leading score is below {LEAD_THRESHOLD:.0f} or less than {MARGIN_THRESHOLD:.0f} "
                     "points ahead of the next explanation.")
    else:
        leading, leading_label = top.id, top.label
        if top.score >= 70 and margin >= 25 and not missing_core and not news_failed:
            confidence = "High"
            conf_expl = "High: leading score of 70 or more, at least 25 points ahead, and no missing core inputs."
        else:
            confidence = "Moderate"
            reasons = []
            if top.score < 70:
                reasons.append("leading score below 70")
            if margin < 25:
                reasons.append(f"margin of {margin:.0f} points (below 25)")
            if missing_core:
                reasons.append("missing core inputs")
            if news_failed:
                reasons.append("news unavailable")
            conf_expl = "Moderate: " + ", ".join(reasons) + "."
        conclusion = (f"The evidence is most consistent with: {top.label} (score {top.score:.0f}, "
                      f"{margin:.0f} points ahead of {second.label}). This describes fit with the evidence, not proven cause.")

    ordered = sorted(results.values(), key=lambda r: (-r.score, r.id))
    total_items = x["n_news_items"]
    news_basis = (f"{x['llm_reviewed_items']} of {total_items} news item(s) had relevance reviewed by the LLM; "
                  f"the rest use the keyword heuristic.") if total_items else "No news items were available."
    return HypothesisEvaluation(
        results=ordered, leading=leading, leading_label=leading_label, conclusion=conclusion,
        confidence=confidence, margin=margin, confidence_explanation=conf_expl, inconclusive=inconclusive,
        inputs={k: v for k, v in x.items() if k not in ("direct_ids",)}, news_basis=news_basis,
    )
