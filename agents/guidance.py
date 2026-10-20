"""Evidence levels, business-facing summary and prioritised next action for one investigation.

Everything here is derived from what the investigation record already contains: tool outputs, the rubric and its
inputs, the retrieved news items with their timing and source type, the news provider statuses, the validation
results and the link-only official pages. Nothing is fetched, invented or inferred from outside the record.

Catalyst evidence levels
    A  Verified company event: a retrieved company announcement (in this app only the synthetic demonstration
       announcements, which the retrieve_source_details tool can open) dated inside the information window.
    B  Potential catalyst, not yet verified: a headline that names the company and a possible cause inside the
       window. Only the headline, publisher, publication time and link were retrieved; the article text and the
       underlying official disclosure were not read.
    C  No identified catalyst: no direct, timely item, or the news sources could not be searched.

Live NSE/BSE announcements are link-only (exchange terms of use), so a live investigation can reach level B at most.
That is deliberate: a headline is the source's claim, not a verified fact.

The next action is chosen by fixed rules from the unresolved question the record leaves, in this order: unreliable
data first, then a news search that failed, then an unresolved tie between explanations, then the leading
explanation's weakest link. Recommendations are investigative only; they never say buy, sell, hold or a price target.
"""
from __future__ import annotations

from datetime import datetime

from config.market import SESSION_CLOSE, SESSION_OPEN, fmt_market_time, to_market_time
from providers.news_data import is_noise_headline, is_roundup_headline

GUIDANCE_VERSION = 1

LEVELS = {
    "A": "Verified company event",
    "B": "Potential catalyst - not yet verified",
    "C": "No identified catalyst",
}

# Headline words grouped into the kind of event they suggest. Taken from the cause vocabulary of the news rules.
CATEGORY_WORDS = [
    ("quarterly results or earnings", ["results", "earnings", "profit", "net profit", "loss", "losses", "revenue",
                                       "income", "margin", "margins", "ebitda", "q1", "q2", "q3", "q4", "quarter",
                                       "quarterly", "fy26", "fy27", "fy28", "beat", "beats", "miss", "misses", "eps",
                                       "guidance", "outlook", "provisions", "npa", "npas", "gnpa", "asset quality",
                                       "slippages"]),
    ("an order or contract win", ["order", "orders", "order win", "bags", "secures", "wins", "contract", "tender",
                                  "letter of award"]),
    ("a deal, stake sale or merger", ["acquisition", "acquire", "acquires", "acquired", "merger", "demerger", "stake",
                                      "stake sale", "block deal", "bulk deal", "promoter", "pledge", "deal", "deals",
                                      "takeover", "full ownership", "full control"]),
    ("a corporate action or fundraising", ["dividend", "bonus", "split", "buyback", "record date", "rights issue",
                                           "qip", "fundraise", "ipo", "offer for sale", "ofs"]),
    ("a management change", ["ceo", "md", "cfo", "chairman", "resign", "resigns", "steps down", "appointed",
                             "appoints"]),
    ("a regulatory or legal development", ["sebi", "rbi", "penalty", "fine", "fined", "show cause", "notice", "probe",
                                           "investigation", "raid", "tax demand", "court", "nclt", "verdict", "ban",
                                           "licence", "license", "usfda", "fda", "warning letter", "observations",
                                           "approval", "approves", "recall"]),
    ("a broker rating change", ["downgrade", "downgrades", "upgrade", "upgrades", "rating", "target price",
                                "price target", "brokerage"]),
    ("an operational update", ["sales", "volumes", "deliveries", "production", "capacity", "plant", "outage", "fire",
                               "strike", "launch", "launches", "exports", "tariff", "tariffs"]),
]

# What to check in the official filing for each kind of event (used in the verification steps).
CATEGORY_CHECK = {
    "quarterly results or earnings": "the results filing or the board-meeting outcome",
    "an order or contract win": "the disclosure of the order or contract",
    "a deal, stake sale or merger": "the disclosure of the transaction",
    "a corporate action or fundraising": "the corporate-action or fundraising disclosure",
    "a management change": "the disclosure of the management change",
    "a regulatory or legal development": "the company's disclosure or clarification on the matter",
    "a broker rating change": "whether any company disclosure accompanied the rating change (ratings themselves are "
                              "broker opinions, not company events)",
    "an operational update": "the company's disclosure of the update",
}


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


def _pct(x, signed: bool = True) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.1%}" if signed else f"{abs(x):.1%}"


def _words(text: str) -> str:
    return f" {''.join(ch.lower() if ch.isalnum() else ' ' for ch in (text or ''))} "


def headline_category(headline: str) -> str | None:
    """The kind of event a headline names, from the cause words it contains; None when it names none."""
    t = _words(headline)
    best, hits_best = None, 0
    for label, words in CATEGORY_WORDS:
        hits = sum(1 for w in words if f" {w} " in t)
        if hits > hits_best:
            best, hits_best = label, hits
    return best


def _session_position(published_iso: str | None, event_date: str) -> str:
    """Where the publication falls relative to the event session: before the open, during the session, or the
    previous evening. Daily prices cannot show intraday order, so 'during' leaves the order open."""
    if not published_iso:
        return "unknown"
    try:
        ts = to_market_time(datetime.fromisoformat(str(published_iso).replace("Z", "+00:00")))
    except ValueError:
        return "unknown"
    day = str(event_date)[:10]
    if ts.date().isoformat() < day:
        return "before_open"
    if ts.time() < SESSION_OPEN:
        return "before_open"
    if ts.time() <= SESSION_CLOSE:
        return "during_session"
    return "after_close"


def _news_unavailable(rec: dict) -> bool:
    attempted = [s for s in rec.get("news_statuses") or [] if s.get("status") not in ("skipped", "link_only")]
    return not attempted or all(s.get("status") == "failed" for s in attempted)


# Social-media posts are not independent publishers: they are excluded from choosing and corroborating a catalyst.
SOCIAL_PLATFORMS = {"facebook", "instagram", "x", "twitter", "x (formerly twitter)", "youtube", "telegram",
                    "whatsapp", "reddit", "linkedin", "threads", "quora", "pinterest", "tiktok"}

# The category as a noun phrase for action wording ("Verify the reported quarterly results ...").
CATEGORY_NOUN = {
    "quarterly results or earnings": "quarterly results", "an order or contract win": "order or contract win",
    "a deal, stake sale or merger": "deal or stake transaction", "a corporate action or fundraising":
    "corporate action or fundraising", "a management change": "management change",
    "a regulatory or legal development": "regulatory or legal development",
    "a broker rating change": "broker rating change", "an operational update": "operational update",
}


def _publisher(n: dict) -> str:
    return (n.get("publisher") or n.get("provider") or "").strip()


def is_social(n: dict) -> bool:
    return _publisher(n).lower() in SOCIAL_PLATFORMS


def _strongest_headline(headlines: list[dict]) -> tuple[dict, list[dict]]:
    """The candidate catalyst among direct, in-window headlines: the subject (event category) reported by the most
    distinct publishers, then the earliest report of it. Returns it with the other reports of the same subject.

    Corroboration guards against a single misleading match (for example a tax 'ITC demand' headline matched to the
    company ITC); earliest-first keeps the report closest to when the information arrived.
    """
    credible = [n for n in headlines if not is_social(n)] or headlines
    groups: dict = {}
    for n in credible:
        groups.setdefault(headline_category(n.get("headline") or ""), []).append(n)

    def strength(item):
        cat, items = item
        return (len({_publisher(n) for n in items if _publisher(n)}), cat is not None,
                -min(_sort_time(n) for n in items))
    cat, items = max(groups.items(), key=strength)
    # Earliest report that names the company; the rest of the subject's reports corroborate it.
    items = sorted(items, key=lambda n: (not n.get("mentions_company", True), _sort_time(n)))
    seen, others = {_publisher(items[0])}, []
    for n in items[1:]:
        if _publisher(n) not in seen:
            seen.add(_publisher(n))
            others.append(n)
    return items[0], others


def _sort_time(n: dict) -> float:
    try:
        return datetime.fromisoformat(str(n.get("published_at")).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return float("inf")


# ---------------------------------------------------------------------------
# Catalyst evidence
# ---------------------------------------------------------------------------

def classify_catalyst(rec: dict) -> dict:
    ev = rec.get("event") or {}
    news = rec.get("news") or []
    demo = (rec.get("data") or {}).get("mode") == "demo"
    name = ev.get("name") or ev.get("ticker")
    date = str(ev.get("date"))[:10]
    if _news_unavailable(rec):
        return {"level": "C", "label": LEVELS["C"], "reason": "news_unavailable",
                "statement": "No catalyst can be identified because no news source could be searched.",
                "access_note": "News providers failed or were not searched; official NSE/BSE pages are link-only."}
    direct = [n for n in news if n.get("final_relevance") == "direct" and n.get("timing") == "in_window"]
    announcements = [n for n in direct if n.get("source_type") == "synthetic_demo"]
    # Re-screen with the current headline rules, so tips and forecast pages saved under older rules never lead.
    headlines = [n for n in direct if n.get("source_type") == "news_headline"
                 and not is_noise_headline(n.get("headline") or "") and not is_roundup_headline(n.get("headline") or "")]
    corroborating = []
    if announcements:
        best = sorted(announcements, key=lambda n: n.get("published_at") or "")[0]
        level = "A"
    elif headlines:
        best, corroborating = _strongest_headline(headlines)
        level = "B"
    else:
        later = [n for n in news if n.get("final_relevance") in ("direct", "uncertain") and n.get("timing") == "after_close"
                 and n.get("mentions_company")]
        searched = len(news)
        statement = (f"No news item or announcement retrieved for {name} names a cause inside the information window "
                     f"({searched} item(s) checked).")
        if later:
            statement += " Some company headlines appeared only after the event-day close, so they describe the move " \
                         "rather than cause it."
        return {"level": "C", "label": LEVELS["C"], "reason": "nothing_direct", "statement": statement,
                "n_items_checked": searched,
                "access_note": "Headlines only; official NSE/BSE announcements were not searched automatically."
                if not demo else "Synthetic demonstration sources only."}

    category = headline_category(best.get("headline") or "")
    publishers = sorted({_publisher(n) for n in [best] + corroborating if _publisher(n)})
    position = _session_position(best.get("published_at"), date)
    published_ist = fmt_market_time(best.get("published_at")) if best.get("published_at") else "time not given"
    out = {
        "level": level, "label": LEVELS[level], "reason": "announcement" if level == "A" else "headline",
        "source_id": best.get("source_id"), "headline": best.get("headline"),
        "publisher": best.get("publisher") or best.get("provider"), "source_type": best.get("source_type"),
        "provider": best.get("provider"), "url": best.get("url"),
        "published_at": best.get("published_at"), "published_ist": published_ist,
        "retrieved_at": best.get("retrieved_at"), "event_date": best.get("event_date"),
        "event_note": best.get("event_note") or "", "timing": best.get("timing"), "session_position": position,
        "category": category, "independent_publishers": publishers, "n_direct_items": len(direct),
        "corroborating": [{"source_id": n.get("source_id"), "publisher": _publisher(n), "headline": n.get("headline"),
                           "url": n.get("url"), "published_ist": fmt_market_time(n.get("published_at"))
                           if n.get("published_at") else "time not given"} for n in corroborating[:3]],
    }
    if level == "A":
        out["statement"] = (f"{name} announcement retrieved: \"{best.get('headline')}\" ({published_ist}). "
                            + (f"The announcement states the event took place on {best.get('event_date')}"
                               + (f" ({best.get('event_note')})" if best.get("event_note") else "") + ". "
                               if best.get("event_date") else "")
                            + "It falls between the previous session's 15:30 IST close and the event-day close.")
        out["access_note"] = ("Synthetic demonstration announcement (fictional company), opened in full with "
                              "retrieve_source_details." if demo else "Company announcement retrieved in full.")
        out["source_claim"] = best.get("headline")
        out["app_inference"] = ("The announcement is the most likely trigger because it is the only company "
                                "disclosure in the window and the stock moved far more than its market and peers.")
    else:
        what = f"reports {category}" if category else "names the company and a possible cause"
        check = CATEGORY_CHECK.get(category, "the company's official announcement")
        out["source_claim"] = best.get("headline")
        others = len(publishers) - 1
        corro = (f" Headlines from {others} other publisher(s) report the same kind of event; that corroborates the "
                 "report but is still not an official record." if others > 0 else "")
        out["statement"] = (f"Potential catalyst: a news headline from {out['publisher']} ({published_ist}) {what}: "
                            f"\"{best.get('headline')}\". The retrieved evidence does not establish the full content or "
                            f"verify that this explains this specific price move.{corro} Check {check} and its timing "
                            "before attributing the move to it.")
        out["access_note"] = ("Only the headline, publisher, publication time and link were retrieved. The article "
                              "text was not read, and the official NSE/BSE filing was not retrieved (link-only).")
        n_pub = len(publishers)
        out["app_inference"] = (f"Market Sentinel treats this as a candidate, not a cause: it names the company and a "
                                f"possible cause inside the window ({n_pub} publisher(s) carried a direct headline).")
    return out


# ---------------------------------------------------------------------------
# Plain-language facts
# ---------------------------------------------------------------------------

def _facts(rec: dict) -> dict:
    ev = rec.get("event") or {}
    rub = rec.get("rubric") or {}
    x = rub.get("inputs") or {}
    evid = rec.get("evidence") or {}
    pc = evid.get("compare_with_peers") or {}
    ret = _f(x.get("ret")) if x.get("ret") is not None else _f(ev.get("ret"))
    rel = _f(x.get("rel_ret"))
    peer_median = _f(pc.get("peer_median_return"))
    if peer_median is None and ret is not None and rel is not None:
        peer_median = ret - rel
    return {
        "name": ev.get("name") or ev.get("ticker"), "ticker": ev.get("ticker"), "date": str(ev.get("date"))[:10],
        "ret": ret, "mkt_ret": _f(x.get("mkt_ret")), "z_mkt": _f(x.get("z_mkt")), "abn": _f(x.get("abnormal_ret")),
        "z_abn": _f(x.get("z_abn")), "rel": rel, "z_rel": _f(x.get("z_rel")), "peer_median": peer_median,
        "n_peers": int(_f(x.get("n_peers")) or 0), "sector_ret": _f(x.get("sector_ret")),
        "z_sector": _f(x.get("z_sector")), "sector_index": x.get("sector_index") if x.get("z_sector") is not None or
        x.get("sector_ret") is not None else None, "sector_configured": bool(x.get("sector_index_configured")),
        "peers_configured": bool(x.get("peers_configured")), "vol_x": _f(x.get("volume_ratio")),
        "z_vol": _f(x.get("z_volume")), "z_ret": _f(x.get("z_ret")), "breadth_same": _f(x.get("breadth_same")),
        "bench": x.get("benchmark") or (rec.get("data") or {}).get("benchmark_name") or "the benchmark",
        "sector_wide": bool(x.get("sector_wide_move")), "market_wide": bool(x.get("market_wide_move")),
        "group": ev.get("sector"),
    }


def _moved(x) -> str:
    return "rose" if x is not None and x > 0 else ("fell" if x is not None and x < 0 else "was flat")


def _move_phrase(x) -> str:
    if x is None:
        return "n/a"
    if abs(x) < 0.0005:
        return "was virtually unchanged"
    return f"{_moved(x)} {_pct(x, False)}"


def _index_name(name: str) -> str:
    return name if "index" in (name or "").lower() else f"{name} index"


def what_happened(f: dict) -> str:
    s = [f"{f['name']} {_move_phrase(f['ret'])} on {f['date']}"
         + (f", while the {f['bench']} {_move_phrase(f['mkt_ret'])}." if f["mkt_ret"] is not None else ".")]
    comp = []
    if f["z_abn"] is not None:
        if abs(f["z_abn"]) >= 3:
            comp.append("far more than the market move would explain")
        elif abs(f["z_abn"]) >= 2:
            comp.append("noticeably more than the market move would explain")
        else:
            comp.append("about as much as the market move would explain")
    if f["peer_median"] is not None and f["n_peers"]:
        peers = f"its {f['n_peers']} watchlist peer(s), whose median {_move_phrase(f['peer_median'])}"
        opposite = abs(f["peer_median"]) >= 0.0005 and (f["peer_median"] > 0) != ((f["ret"] or 0) > 0)
        if opposite:
            comp.append(f"against {peers}")
        elif f["z_rel"] is not None and abs(f["z_rel"]) >= 2:
            comp.append(f"further than {peers}")
        else:
            comp.append(f"in line with {peers}")
    if comp:
        s.append("It moved " + " and ".join(comp) + ".")
    if f["sector_index"] and f["sector_ret"] is not None:
        s.append(f"Its sector index ({f['sector_index']}) {_move_phrase(f['sector_ret'])}.")
    elif not f["sector_configured"]:
        s.append("Its peer group has no sector index in this app, so the sector check rests on peers only."
                 if f["peers_configured"] else "It has no sector index or peer in the watchlist to compare with.")
    if f["vol_x"] is not None:
        if (f["z_vol"] or 0) >= 3:
            s.append(f"Trading volume was unusually heavy, {f['vol_x']:.1f} times its typical level.")
        elif (f["z_vol"] or 0) >= 2:
            s.append(f"Trading volume was above normal, {f['vol_x']:.1f} times its typical level.")
        else:
            s.append("Trading volume was close to normal.")
    s.append("These observations show the move was unusual; on their own they do not show what caused it.")
    return " ".join(s)


# ---------------------------------------------------------------------------
# Explanation and its strength
# ---------------------------------------------------------------------------

def _support_for(hid: str, f: dict, cat: dict) -> tuple[list[str], list[str]]:
    sup, con = [], []
    if hid == "H1":
        if f["mkt_ret"] is not None:
            sup.append(f"The {f['bench']} itself {_move_phrase(f['mkt_ret'])} the same day.")
        if f["breadth_same"] is not None and f["breadth_same"] >= 0.75:
            sup.append(f"{f['breadth_same']:.0%} of the watchlist moved the same way.")
        if f["z_abn"] is not None and abs(f["z_abn"]) >= 2:
            con.append("The stock still moved more than its usual link to the market would predict.")
    elif hid == "H2":
        if f["sector_index"] and f["sector_ret"] is not None:
            sup.append(f"The {_index_name(f['sector_index'])} {_move_phrase(f['sector_ret'])}.")
        if f["peer_median"] is not None and f["n_peers"]:
            sup.append(f"Its peers' median move was {_pct(f['peer_median'])}.")
        if f["z_rel"] is not None and abs(f["z_rel"]) >= 2:
            con.append(f"The stock moved {_pct(f['rel'], False)} beyond its peers' median, more than a shared sector "
                       "move alone would suggest.")
        if cat["level"] in ("A", "B"):
            con.append("A company-specific item was also found inside the window.")
    elif hid == "H3":
        if f["z_abn"] is not None and abs(f["z_abn"]) >= 2:
            sup.append(f"The stock {'rose' if (f['abn'] or 0) > 0 else 'fell'} {_pct(f['abn'], False)} more than the "
                       "market move would explain.")
        if cat["level"] == "A":
            sup.append("A company announcement was published inside the information window.")
        elif cat["level"] == "B":
            sup.append(f"A headline from {cat.get('publisher')} names the company and "
                       f"{cat.get('category') or 'a possible cause'} inside the window.")
        if (f["z_vol"] or 0) >= 3:
            sup.append("Heavy volume is typical when new company information arrives.")
        if f["sector_wide"] or (f["z_sector"] is not None and abs(f["z_sector"]) >= 2):
            con.append("Its sector also moved strongly, so part of the move may be sector-wide.")
        if cat["level"] == "B" and len(cat.get("independent_publishers") or []) <= 1:
            con.append("Only one publisher carried a direct headline, and its article was not read.")
    elif hid == "H4":
        if (f["z_vol"] or 0) >= 3:
            sup.append(f"Volume was {f['vol_x']:.1f} times its typical level." if f["vol_x"] else "Volume was abnormal.")
        if cat["level"] == "C" and cat.get("reason") == "nothing_direct":
            sup.append("No company news inside the window was found in the sources searched.")
        con.append("Not finding news is not proof that none exists: official NSE/BSE announcements are checked by hand.")
    return sup[:3], con[:2]


def explanation(rec: dict, f: dict, cat: dict) -> dict:
    rub = rec.get("rubric") or {}
    lead = rub.get("leading")
    results = {r["id"]: r for r in rub.get("results") or []}
    if rub.get("inconclusive"):
        ranked = [r for r in rub.get("results") or [] if r["id"] != "H5"]
        a, b = (ranked + [None, None])[:2]
        return {"status": "unresolved", "hypothesis": "H5",
                "headline": f"Unresolved: {a['label'] if a else 'n/a'} or {b['label'] if b else 'n/a'}",
                "text": (f"The evidence fits {a['label'].lower()} ({a['score']:.0f} points) and "
                         f"{b['label'].lower()} ({b['score']:.0f}) almost equally, so no single explanation is "
                         "stated." if a and b else "No explanation reaches the evidence threshold."),
                "supporting": [], "contradicting": []}
    label = results.get(lead, {}).get("label", rub.get("leading_label"))
    sup, con = _support_for(lead, f, cat)
    if lead == "H3" and cat["level"] == "A":
        status = "verified" if rub.get("confidence") == "High" else "provisional"
        head = f"Company announcement: {cat.get('headline')}"
    elif lead == "H3" and cat["level"] == "B":
        status, head = "provisional", f"Potential catalyst: {cat.get('category') or 'company news'} reported in a headline"
    elif lead == "H3":
        status, head = "provisional", "Company-specific move, catalyst not identified"
    elif lead == "H4":
        status, head = "provisional", "Unusual trading with no public explanation found"
    elif lead == "H1":
        status, head = "provisional", f"The move was largely shared with the {f['bench']}"
    else:
        status, head = "provisional", f"The move was largely shared with its sector ({f.get('group') or 'peer group'})"
    status_text = {
        "verified": "Verified: a retrieved company announcement inside the window supports it, and the evidence "
                    "clearly favours this explanation.",
        "provisional": "Provisional: the evidence favours this explanation, but the cause has not been verified.",
    }[status]
    if status == "verified" and (rec.get("data") or {}).get("mode") == "demo":
        status_text += " (Within the synthetic demonstration data.)"
    return {"status": status, "hypothesis": lead, "label": label, "headline": head, "status_text": status_text,
            "confidence": rub.get("confidence"), "supporting": sup, "contradicting": con}


# ---------------------------------------------------------------------------
# Unresolved cases
# ---------------------------------------------------------------------------

PAIR_TESTS = {
    frozenset({"H2", "H3"}): {
        "why": "the whole peer group moved strongly the same day, yet {name} moved further than its peers and "
               "{found}; a daily close cannot separate a company reaction from a larger reaction to the same sector "
               "news.",
        "checks": [
            ("Whether {name} made its own disclosure inside the window (results, order, corporate action)",
             "a company disclosure inside the window strengthens the company explanation",
             "no company disclosure strengthens the sector explanation"),
            ("Whether the peers' move traces to one shared driver, such as a large peer's results or a sector policy",
             "a shared driver strengthens the sector explanation",
             "no shared driver leaves the company explanation stronger"),
        ]},
    frozenset({"H1", "H3"}): {
        "why": "the broad market also moved unusually, yet {name} moved more than its link to the market predicts; "
               "the market move may have amplified a company reaction, or the reverse.",
        "checks": [
            ("Whether {name} made its own disclosure inside the window",
             "a company disclosure strengthens the company explanation",
             "no disclosure strengthens the market explanation"),
            ("What drove the market that day (policy, flows, global cues)",
             "a market-wide driver that hits {name} harder strengthens the market explanation", ""),
        ]},
    frozenset({"H3", "H4"}): {
        "why": "the move is specific to {name}, but {found}; without the underlying disclosure it is unclear whether "
               "public news or other trading explains it.",
        "checks": [
            ("Whether an official NSE/BSE announcement for {name} exists inside the window",
             "an announcement moves the case to company news",
             "none found keeps it as unexplained trading"),
        ]},
    frozenset({"H1", "H2"}): {
        "why": "both the market and the sector moved unusually; the question is whether the sector moved by more "
               "than the market itself explains.",
        "checks": [
            ("Whether the sector index moved clearly more than the market",
             "a much larger sector move strengthens the sector explanation",
             "a similar move strengthens the market explanation"),
        ]},
}


def unresolved_analysis(rec: dict, f: dict, cat: dict) -> dict | None:
    rub = rec.get("rubric") or {}
    if not rub.get("inconclusive"):
        return None
    ranked = [r for r in rub.get("results") or [] if r["id"] != "H5"]
    a, b = ranked[0], ranked[1]
    established = (f"{f['name']} had a statistically unusual move on {f['date']} ({_pct(f['ret'])}"
                   + (f", volume {f['vol_x']:.1f} times typical" if f["vol_x"] else "") + "). The available evidence "
                   "does not distinguish its cause well enough to name one.")
    found = {"A": "a company announcement was retrieved",
             "B": "a company headline was found but its article was not read",
             "C": "no company item was found"}[cat["level"]]
    pair = PAIR_TESTS.get(frozenset({a["id"], b["id"]}))
    if pair:
        why = pair["why"].format(name=f["name"], found=found)
        checks = [{"check": c.format(name=f["name"]), "if_yes": y.format(name=f["name"]), "if_no": n.format(name=f["name"])}
                  for c, y, n in pair["checks"]]
    elif a["score"] < 45:
        why = (f"no explanation reaches the evidence threshold (best: {a['label'].lower()}, {a['score']:.0f} points), "
               "so the evidence gathered is too thin to separate the options.")
        checks = [{"check": "The gap that keeps every explanation weak (see the recommended action)",
                   "if_yes": "", "if_no": ""}]
    else:
        why = (f"{a['label'].lower()} ({a['score']:.0f}) and {b['label'].lower()} ({b['score']:.0f}) fit the "
               "evidence almost equally.")
        checks = [{"check": "The evidence named in the recommended action", "if_yes": "", "if_no": ""}]
    return {"established": established, "plausible": [{"id": a["id"], "label": a["label"], "score": a["score"]},
                                                      {"id": b["id"], "label": b["label"], "score": b["score"]}],
            "why_undistinguished": why[0].upper() + why[1:], "discriminating_checks": checks}


# ---------------------------------------------------------------------------
# Next action
# ---------------------------------------------------------------------------

def _official(rec: dict, labels: tuple[str, ...]) -> list[dict]:
    return [{"label": link.get("label"), "url": link.get("url"), "search_for": link.get("search_for")}
            for link in rec.get("official_links") or [] if link.get("label") in labels]


def _window_text(rec: dict, f: dict) -> str:
    return f"the window from the previous session's 15:30 IST close to 15:30 IST on {f['date']}"


def _data_problems(rec: dict, f: dict) -> list[str]:
    val = rec.get("validation") or {}
    rub = rec.get("rubric") or {}
    x = rub.get("inputs") or {}
    probs = []
    if val.get("lookahead_check_passed") is False:
        probs.append("the alert was not reproduced when only data up to the event date was used")
    base, need = _f(val.get("baseline_observations")), _f(val.get("min_required"))
    if base is not None and need is not None and base < need:
        probs.append(f"only {base:.0f} sessions of baseline history (at least {need:.0f} needed)")
    if val.get("partial_session"):
        probs.append("the event-day bar was still in progress when the data was loaded")
    if x.get("beta") is None:
        probs.append("the market model (beta) could not be estimated")
    for w in material_quality_issues(rec):
        probs.append(f"data-quality issue: {w}")
    return probs


def material_quality_issues(rec: dict) -> list[str]:
    """Data-quality notes that undermine this event's numbers: a large single-day gap dated on the event day itself
    (possibly an unadjusted bonus issue, split or demerger) or an error. Routine notes, such as a zero-volume day
    elsewhere in the history, are reported as limitations instead of blocking the interpretation."""
    date = str((rec.get("event") or {}).get("date"))[:10]
    val = rec.get("validation") or {}
    out = []
    for msg in val.get("data_quality_issues") or (rec.get("rubric") or {}).get("inputs", {}).get("data_quality_warnings") or []:
        text = str(msg)
        if (text.startswith("Single-day moves") and date in text) or text.startswith(("No rows", "No volume column")) \
                or "non-positive" in text:
            out.append(text)
    return out[:2]


def choose_action(rec: dict, f: dict, cat: dict, unres: dict | None) -> dict:
    rub = rec.get("rubric") or {}
    lead = rub.get("leading")
    demo = (rec.get("data") or {}).get("mode") == "demo"
    name, date = f["name"], f["date"]
    window = _window_text(rec, f)
    tools = sorted((rec.get("evidence") or {}).keys())
    limits = []
    if not demo:
        limits.append("Official NSE/BSE announcements are link-only in this app (exchange terms of use), so they must "
                      "be checked by hand.")
    if any(n.get("source_type") == "news_headline" for n in rec.get("news") or []):
        limits.append("News evidence is headlines only; article text is not read.")
    limits.append("Daily prices cannot show whether the price moved before or after news published during the session.")
    if demo:
        limits.append("Synthetic demonstration data: companies and announcements are fictional.")
    if not f["sector_configured"]:
        limits.append("No sector index is configured for this peer group; sector evidence rests on peers.")
    routine = [w for w in (rec.get("rubric") or {}).get("inputs", {}).get("data_quality_warnings") or []
               if w not in material_quality_issues(rec)]
    if routine:
        limits.append("Data note for this security (not material to this event): " + routine[0])
    base_escalate = {
        "A": "Ask a reviewer before relying on the explanation if the announcement's content looks too small for the "
             "size of the move.",
        "B": "Withhold a firmer conclusion, and ask a reviewer, if the official filing cannot be found or contradicts "
             "the headline.",
        "C": "Withhold a firmer conclusion, and ask a reviewer, if an official announcement turns up that this "
             "reading does not account for.",
    }[cat["level"]]

    def action(kind, primary, why, evidence, steps, reassess, outcome, escalate, links=None):
        if demo:   # fictional companies have no exchange filings: say what the live step would be
            steps = [f"On live data: {st[0].lower()}{st[1:].rstrip('.')} (not possible here: the company is fictional)."
                     if ("NSE" in st or "BSE" in st or "exchanges'" in st) else st for st in steps]
            links = []
        return {"kind": kind, "primary": primary, "why": why, "evidence": evidence, "steps": steps[:3],
                "reassess_if": reassess, "expected_outcome": outcome, "escalate_if": escalate,
                "limitations": limits, "links": links or [], "advice_note":
                "Investigative guidance only. It is not a recommendation to buy, sell or hold the security."}

    # 1. Data that cannot be trusted comes first.
    probs = _data_problems(rec, f)
    if probs:
        return action(
            "validate_data", f"Validate the price data for {name} before relying on any explanation",
            "The assessment rests on statistics that may be unreliable: " + "; ".join(probs) + ".",
            [{"kind": "validation", "ref": "Event validation", "text": p} for p in probs],
            ["Open Methodology and data, Data quality tab, and read the notes for this security.",
             "Refresh the market data and re-run the investigation once the session is final (after 16:15 IST)."
             if not demo else "Re-run the investigation after correcting the data issue.",
             "Compare the event-day close with the exchange's published close for the same date."],
            "If the corrected data no longer shows an unusual move, treat the alert as a data artefact.",
            "A trustworthy price series, so that the explanation can be assessed.",
            "Do not report a cause while any of these data problems stands.")

    # 2. The news search failed: the cause question cannot be asked yet.
    if cat.get("reason") == "news_unavailable":
        links = _official(rec, ("NSE corporate announcements", "BSE corporate filings"))
        return action(
            "restore_news", f"Check {name}'s official announcements by hand for {date}",
            "The automated news search failed, so company news was never tested as an explanation.",
            [{"kind": "provider", "ref": s.get("provider"), "text": f"{s.get('status')}: {str(s.get('message'))[:120]}"}
             for s in rec.get("news_statuses") or []],
            [f"Open the NSE corporate announcements page and search {name} for the window {window}." if not demo
             else "Re-run with news enabled.",
             "Re-run the investigation when the news sources respond (Refresh market data, then Run investigation).",
             "Note any disclosure found and its time in IST."],
            "An announcement inside the window would make company news the leading candidate.",
            "Whether a public company event exists that could explain the move.",
            "Do not describe the move as unexplained until a news search has succeeded.", links)

    # 3. Unresolved: separate the two leading explanations.
    if unres:
        ids = {p["id"] for p in unres["plausible"]}
        links = _official(rec, ("NSE corporate announcements", "NSE financial results"))
        first = unres["discriminating_checks"][0]
        evidence = [{"kind": "tool", "ref": t, "text": d} for t, d in (
            ("compare_with_benchmark", f"{f['bench']} {_pct(f['mkt_ret'])}; stock beyond the market model {_pct(f['abn'])}"),
            ("compare_with_peers", (f"peer median {_pct(f['peer_median'])}; stock beyond peers {_pct(f['rel'])}"
                                    + (f"; {f['sector_index']} {_pct(f['sector_ret'])}" if f["sector_index"] else ""))),
        ) if t in tools]
        if cat.get("source_id"):
            evidence.append({"kind": "source", "ref": cat["source_id"],
                             "text": f"{cat.get('publisher')}: \"{cat.get('headline')}\" ({cat.get('published_ist')})"})
        if ids == {"H2", "H3"} or ids == {"H1", "H3"} or ids == {"H3", "H4"}:
            check = CATEGORY_CHECK.get(cat.get("category"), "any company disclosure")
            primary = (f"Check {name}'s exchange filings for {check} inside the window, then compare with what "
                       "drove its peers" if "H2" in ids else
                       f"Check whether {name} made an official disclosure inside the window")
            steps = [f"Open NSE corporate announcements and search {name} for {window}." if not demo else
                     "Open the announcement in the Evidence tab and note its publication time.",
                     (f"Open the candidate headline ({cat.get('publisher')}, {cat.get('published_ist')}) and confirm it "
                      "describes a company event, not just the price move." if cat.get("level") == "B" else
                      "Look for any company headline the keyword search may have missed."),
                     ("Compare the peers' headlines for a shared driver (for example a large peer's results)." if "H2" in ids
                      else f"Note what moved the {f['bench']} that day." if "H1" in ids else
                      "If nothing is found, record the move as unexplained trading.")]
            reassess = (f"{first['if_yes'].capitalize()}; {first['if_no']}." if first.get("if_yes") else
                        "Reassess when the official record is checked.")
        else:
            primary = "Compare the sector index with the market for that day to see which move came first in size"
            steps = ["Open the Evidence tab and compare the sector index and benchmark bars.",
                     "Look for a sector-specific headline among the indirect news items.",
                     "Re-run after the next session to see whether the sector diverges from the market."]
            reassess = "A sector move well beyond the market's favours the sector explanation; a similar move favours the market."
        return action(
            "separate_explanations", primary,
            unres["why_undistinguished"],
            evidence, steps, reassess,
            f"Which of {unres['plausible'][0]['label'].lower()} and {unres['plausible'][1]['label'].lower()} drove "
            "the move.", base_escalate, links)

    # 4. A leading explanation exists: test its weakest link.
    if lead == "H3" and cat.get("level") == "B" and cat.get("category") == "a broker rating change":
        links = _official(rec, ("NSE corporate announcements",))
        return action(
            "verify_rating_change", f"Confirm the broker rating change behind {name}'s move and check for company news",
            ("The leading candidate is a broker's rating change reported in headlines. A rating is an analyst's "
             "opinion, not a company event, and the articles were not read."),
            [{"kind": "source", "ref": cat.get("source_id"),
              "text": f"{cat.get('publisher')}: \"{cat.get('headline')}\" ({cat.get('published_ist')})"}] +
            [{"kind": "source", "ref": o.get("source_id"), "text": f"{o.get('publisher')}: \"{o.get('headline')}\""}
             for o in cat.get("corroborating", [])[:2]],
            [f"Open the article ({cat.get('publisher')}) and note which broker changed its rating, to what, and when.",
             f"Check NSE corporate announcements for any {name} disclosure in {window}, in case company news lies "
             "behind the rating change.",
             "Compare with the peers' moves that day to see whether the rating change was specific to this stock."],
            ("If a company disclosure appears in the window, treat it as the primary candidate; if the rating change is "
             "the only news, describe the move as a reaction to an analyst opinion."),
            "Whether the move was a reaction to a broker's opinion or to new company information.",
            base_escalate, links)
    if lead == "H3" and cat.get("level") == "B":
        check = CATEGORY_CHECK.get(cat.get("category"), "the company's official announcement")
        noun = CATEGORY_NOUN.get(cat.get("category"), "company event")
        links = _official(rec, ("NSE corporate announcements", "NSE financial results", "BSE financial results"))
        return action(
            "verify_catalyst", f"Verify the reported {noun} in {name}'s official filings",
            ("The explanation rests on a headline whose article was not read; the underlying disclosure and its time "
             "have not been checked."),
            [{"kind": "source", "ref": cat.get("source_id"),
              "text": f"{cat.get('publisher')}: \"{cat.get('headline')}\" ({cat.get('published_ist')})"}] +
            ([{"kind": "tool", "ref": "compare_with_benchmark",
               "text": f"stock beyond the market model {_pct(f['abn'])}"}] if "compare_with_benchmark" in tools else []),
            [f"Open NSE corporate announcements and find {check} for {name}.".replace("..", "."),
             f"Confirm the filing time falls within {window}, and whether it came before the open, during the "
             "session or after the previous close.",
             f"Open the headline's article ({cat.get('publisher')}) to confirm it reports the company event, not only "
             "the price move."],
            ("Reconsider the company explanation if no filing exists, if the filing came after the move, or if the "
             "peers moved by a similar amount on the same day."),
            "Whether the reported event is real, official and timed to explain this move.",
            base_escalate, links)
    if lead == "H3" and cat.get("level") == "A":
        pos = cat.get("session_position")
        timing_note = {"before_open": "before the session opened, so the whole session could react to it",
                       "during_session": "during the session, so part of the move may have come before it",
                       "after_close": "after the close", "unknown": "at an unknown time"}.get(pos, "")
        return action(
            "align_timing", f"Align the announcement time with {name}'s price move",
            f"The announcement is retrieved and inside the window; it was published {timing_note}.",
            [{"kind": "source", "ref": cat.get("source_id"), "text": f"\"{cat.get('headline')}\" ({cat.get('published_ist')})"}],
            ["Read the full announcement (Evidence tab, source details) and note what it discloses.",
             "Check the following sessions in the replay page to see whether the move held or reversed.",
             "Compare the size of the move with how the peers reacted on the same day."],
            "Reconsider if the peers moved by a similar amount, which would point to a shared driver.",
            "Confirmation that the disclosure, not a market or sector factor, explains the move.",
            "Escalate for review if the announcement's content looks too small for the size of the move.")
    if lead == "H3":
        links = _official(rec, ("NSE corporate announcements",))
        return action(
            "find_catalyst", f"Search {name}'s official announcements for the event window",
            "The move is specific to the stock, but no company item names a cause inside the window.",
            [{"kind": "tool", "ref": "compare_with_benchmark", "text": f"stock beyond the market model {_pct(f['abn'])}"}],
            [f"Open NSE corporate announcements and search {name} for {window}.",
             "Check whether the company released results or held a board meeting that day.",
             "Record any disclosure and its time in IST."],
            "If no disclosure exists, the case moves toward unexplained trading.",
            "The specific company event, if one exists.", base_escalate, links)
    if lead == "H4":
        links = _official(rec, ("NSE corporate announcements", "BSE corporate filings"))
        return action(
            "investigate_volume", f"Check public announcements and trading disclosures for {name} on {date}",
            ("Volume was unusual and no public explanation was found in the sources searched; official announcements "
             "and deal disclosures were not checked automatically."),
            [{"kind": "tool", "ref": "calculate_abnormal_volume",
              "text": f"volume {f['vol_x']:.1f} times typical" if f["vol_x"] else "abnormal volume"}],
            [f"Open NSE corporate announcements and search {name} for {window}.",
             "Check the exchanges' bulk and block deal reports for that date (linked from the NSE and BSE pages).",
             "Note whether an index change, F&O expiry or results date fell on that day."],
            "A disclosure or reported large deal would explain the trading without unknown information.",
            "Whether a public event or a disclosed large trade explains the volume.",
            ("Unusual volume alone is not evidence of misconduct. Escalate to a compliance reviewer only if no public "
             "explanation exists and the pattern repeats."), links)
    if lead == "H1":
        return action(
            "confirm_market_move", f"Confirm that {name}'s move was mainly the market's move",
            f"The {f['bench']} moved unusually the same day"
            + (f", and {f['breadth_same']:.0%} of the watchlist moved the same way." if f["breadth_same"] is not None
               else "."),
            [{"kind": "tool", "ref": "compare_with_benchmark",
              "text": f"{f['bench']} {_pct(f['mkt_ret'])}; stock beyond the market model {_pct(f['abn'])}"},
             {"kind": "tool", "ref": "get_market_context",
              "text": f"{f['breadth_same']:.0%} of the watchlist moved the same way" if f["breadth_same"] is not None
              else "market breadth"}],
            ["Identify the market-wide driver among the indirect (market) headlines in the Evidence tab.",
             f"Check that the stock's move beyond the market model ({_pct(f['abn'])}) is small.",
             "Re-run after the next session to see whether the stock keeps tracking the market."],
            "Reconsider if a company announcement inside the window turns up, or the stock keeps diverging.",
            "Confirmation that no company-specific explanation is needed.", base_escalate)
    # H2
    return action(
        "confirm_sector_move", f"Identify the shared driver behind the {f.get('group') or 'sector'} move",
        "Peers and the sector moved together, so the explanation is a shared driver that is not yet named.",
        [{"kind": "tool", "ref": "compare_with_peers",
          "text": f"peer median {_pct(f['peer_median'])}" + (f"; {f['sector_index']} {_pct(f['sector_ret'])}"
                                                              if f["sector_index"] else "")}],
        ["Look for a sector headline among the indirect news items (policy, commodity prices, a large peer's results).",
         (f"Find out why {name} moved {_pct(f['rel'], False)} beyond its peers' median: a larger reaction to the same "
          "driver, or company news of its own." if f["z_rel"] is not None and abs(f["z_rel"]) >= 2 else
          f"Confirm that {name} stayed close to its peers ({_pct(f['rel'])} beyond their median)."),
         "Re-run after the next session to see whether the sector move persists."],
        f"Reconsider if {name} keeps diverging from its peers, which would point to company-specific news.",
        "The sector-level cause of the move.", base_escalate)


# ---------------------------------------------------------------------------
# Unknowns and the full guidance
# ---------------------------------------------------------------------------

def material_unknowns(rec: dict, f: dict, cat: dict, expl: dict, unres: dict | None) -> list[str]:
    out = []
    if unres:
        a, b = unres["plausible"]
        out.append(f"Which of {a['label'].lower()} and {b['label'].lower()} drove the move.")
    if cat["level"] == "B":
        out.append(f"Whether the headline's report of {cat.get('category') or 'a company event'} matches an official "
                   "filing, and when that filing was made relative to the move.")
    elif cat.get("reason") == "news_unavailable":
        out.append("Whether any public news explains the move: the news sources could not be searched.")
    elif cat["level"] == "C":
        out.append("Whether an official company announcement exists that the automated search did not cover.")
    if expl.get("hypothesis") in ("H1", "H2") and not unres:
        out.append(f"What drove the {'market' if expl['hypothesis'] == 'H1' else 'sector'} move itself.")
    if cat["level"] in ("A", "B") and cat.get("session_position") == "during_session":
        out.append("Whether the price moved before or after the item was published during the session.")
    return out[:4]


def build_guidance(rec: dict) -> dict:
    f = _facts(rec)
    cat = classify_catalyst(rec)
    unres = unresolved_analysis(rec, f, cat)
    expl = explanation(rec, f, cat)
    act = choose_action(rec, f, cat, unres)
    return {
        "version": GUIDANCE_VERSION,
        "what_happened": what_happened(f),
        "explanation": expl,
        "catalyst": cat,
        "unresolved": unres,
        "action": act,
        "unknowns": material_unknowns(rec, f, cat, expl, unres),
    }
