"""News and announcement evidence for NSE-listed companies.

Sources, each optional and each reported with its own status:

* Google News RSS search with the India edition (hl=en-IN, gl=IN, ceid=IN:en). Returns headlines with
  publisher and publication time, and supports date-bounded queries (after:/before:), which allows historical
  windows. Intended here for low-volume, non-commercial academic use.
* Yahoo Finance headlines via yfinance (latest headlines only, so it can only help with recent events).
* Official NSE/BSE disclosures: LINK-ONLY. NSE's website terms of use (clause 9) prohibit systematic or
  automated data collection, and neither exchange offers a documented public API for announcements, so the app
  never scrapes them or calls undocumented endpoints. It returns links to the official search pages for manual
  verification, labelled as such. This is not an automated filing search.
* Synthetic announcements for the fictional .DEMO securities (demonstration mode only).

Only headlines, publishers, timestamps and links are stored. Article text is not scraped. Every item records
which provider returned it and when (retrieval time), separately from when it was published (source time).
Relevance labels produced here come from a keyword heuristic and are marked as such; the LLM investigator may
review them. Session times come from config/market.py (NSE, 15:30 IST close).
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

from config.market import (DISCLOSURE_TERMS_NOTE, MARKET_TZ, OFFICIAL_DISCLOSURE_LINKS, fmt_market_time,
                           previous_trading_day, session_close_utc, shift_trading_days)
from config.settings import CACHE_DIR, Settings
from config.watchlist import Universe

GOOGLE_NEWS_LOCALE = "hl=en-IN&gl=IN&ceid=IN:en"
OFFICIAL_LINKS_PROVIDER = "NSE/BSE official disclosures (link-only)"

SOURCE_TYPES = ("news_headline", "synthetic_demo")
# Source types that count as the company's own announcement in the hypothesis rubric. Live mode retrieves none:
# official NSE/BSE announcements are link-only (see config/market.py). The fictional announcements of the
# demonstration dataset use this path so the rubric's announcement criterion can be shown and tested.
COMPANY_ANNOUNCEMENT_TYPES = ("synthetic_demo",)

# Words that name a possible cause of a price move (Indian business-news vocabulary included).
CAUSE_WORDS = [
    "results", "earnings", "profit", "net profit", "loss", "losses", "revenue", "income", "margin", "margins",
    "ebitda", "guidance", "outlook", "forecast", "beat", "beats", "miss", "misses", "q1", "q2", "q3", "q4",
    "quarter", "quarterly", "fy26", "fy27", "fy28", "provisions", "npa", "npas", "gnpa", "asset quality",
    "slippages", "loan growth", "deposits", "order", "orders", "order win", "bags", "secures", "wins", "contract",
    "deal", "deals", "tender", "letter of award", "acquisition", "acquire", "acquires", "merger", "demerger",
    "stake", "stake sale", "block deal", "bulk deal", "offer for sale", "ofs", "qip", "rights issue", "fundraise",
    "ipo", "dividend", "bonus", "split", "buyback", "record date", "ceo", "md", "cfo", "chairman", "resign",
    "resigns", "steps down", "appointed", "appoints", "sebi", "rbi", "penalty", "fine", "fined", "show cause",
    "notice", "probe", "investigation", "raid", "tax demand", "gst", "income tax", "court", "nclt", "verdict",
    "ban", "licence", "license", "usfda", "fda", "warning letter", "observations", "approval", "approves",
    "launch", "launches", "recall", "downgrade", "downgrades", "upgrade", "upgrades", "rating", "target price",
    "price target", "brokerage", "tariff", "tariffs", "export", "exports", "sales", "volumes", "deliveries",
    "production", "capacity", "plant", "outage", "fire", "strike", "breach", "cyberattack", "promoter", "pledge",
    "warns", "warning", "cuts", "raises", "lowers", "eps", "announces", "announcement", "clarification",
]
# Words that only describe the move itself. A headline with these and no cause word reports the move
# without explaining it (reaction coverage), so it is not treated as a direct explanation.
MOVE_WORDS = [
    "plunge", "plunges", "plunged", "surge", "surges", "surged", "tumble", "tumbles", "tumbled", "soar", "soars",
    "soared", "slump", "slumps", "slumped", "jump", "jumps", "jumped", "slide", "slides", "slid", "rally",
    "rallies", "rallied", "sink", "sinks", "sank", "fall", "falls", "fell", "rise", "rises", "rose", "drop",
    "drops", "dropped", "climb", "climbs", "climbed", "slip", "slips", "slipped", "dip", "dips", "dipped",
    "zooms", "tanks", "crash", "crashes", "gains", "declines", "upper circuit", "lower circuit", "52-week high",
    "52-week low", "record high", "in focus", "buzzing", "top gainer", "top loser", "worst day", "best day",
    "trade higher", "trade lower", "movers",
]
# Routine items that name the company but carry no news: holdings reports, tips and live price pages.
NOISE_PATTERNS = [
    r"\b(raises|boosts|lifts|grows|increases|trims|cuts|reduces|decreases|lowers|sells)\s+(its\s+)?(holdings|stake|position)\b",
    r"\b(stock|shares|stake|position)\s+(purchased|acquired|sold|bought)\s+by\b",
    r"\bhow to (earn|make)\b",
    r"\bshould you (buy|sell|hold)\b",
    r"\bbuy or sell\b",
    r"\bis\b.{0,60}\ba (buy|sell)\b",
    r"\bshare price (today )?live\b",
    r"\blive updates?\b",
    r"\b(intraday|trading) (ideas|picks|calls)\b",
    r"\btechnical (view|picks|outlook)\b",
    r"\bmultibagger\b",
    r"\bpenny stocks?\b",
]
# Round-ups that list many companies: may contain the explanation, but the headline alone does not show it.
ROUNDUP_PATTERNS = [r"\bstocks? to (watch|buy|track)\b", r"\bstocks in (news|focus)\b", r"\bbuzzing stocks\b",
                    r"\bmarket (wrap|highlights|live)\b"]
MARKET_WORDS = [
    "sensex", "nifty", "nifty 50", "bank nifty", "nifty bank", "dalal street", "stock market", "markets", "market",
    "indices", "rbi policy", "repo rate", "monetary policy", "mpc", "inflation", "cpi", "wpi", "gdp", "fii", "fiis",
    "fpi", "fpis", "dii", "diis", "foreign investors", "rupee", "crude", "oil prices", "brent", "budget",
    "gst council", "fed", "us fed", "global cues", "selloff", "sell-off", "bank stocks", "it stocks",
    "pharma stocks", "auto stocks", "metal stocks", "fmcg stocks", "psu banks", "psu stocks", "sectoral", "sector",
    "us tariffs", "trade deal", "monsoon", "elections",
]
CATALYST_WORDS = CAUSE_WORDS  # kept for backwards compatibility


def _utc_iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_any_time(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    s = str(value).strip()
    try:
        return parsedate_to_datetime(s).astimezone(timezone.utc)
    except Exception:
        pass
    try:
        ts = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _hash(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10]


@dataclass
class NewsItem:
    source_id: str
    headline: str
    provider: str
    source_type: str                     # news_headline | synthetic_demo
    publisher: str | None = None
    published_at: str | None = None      # ISO UTC: when the source published it (source time)
    url: str | None = None
    tickers: list[str] = field(default_factory=list)
    summary: str = ""                    # evidence summary written by Market Sentinel from structured fields
    feed_snippet: str = ""               # short text supplied by the feed, truncated
    timing: str = "unknown"              # before_window | in_window | after_close | unknown
    relevance: str = "uncertain"         # direct | indirect | uncertain | unrelated
    relevance_basis: str = "keyword heuristic"
    relevance_rationale: str = ""
    mentions_company: bool = False
    retrieved_at: str | None = None      # ISO UTC: when Market Sentinel retrieved it (retrieval time)
    event_date: str | None = None        # date of the underlying event, only when the source states it
    event_note: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class ProviderStatus:
    provider: str
    status: str                          # ok | empty | failed | skipped | link_only
    message: str = ""
    query: str | None = None
    n_items: int = 0
    retrieved_at: str | None = None


NOT_SEARCHED = ("skipped", "link_only")   # statuses that mean no automated search took place


@dataclass
class NewsSearchResult:
    ticker: str
    event_date: str
    window_start: str
    window_end: str
    cutoff: str | None
    items: list[NewsItem] = field(default_factory=list)
    statuses: list[ProviderStatus] = field(default_factory=list)
    official_links: list[dict] = field(default_factory=list)

    @property
    def any_provider_ok(self) -> bool:
        return any(s.status in ("ok", "empty") for s in self.statuses)

    @property
    def all_failed(self) -> bool:
        attempted = [s for s in self.statuses if s.status not in NOT_SEARCHED]
        return bool(attempted) and all(s.status == "failed" for s in attempted)


# ---------------------------------------------------------------------------
# Timing and heuristic relevance
# ---------------------------------------------------------------------------

def classify_timing(published_iso: str | None, prev_session, event_date) -> str:
    """Position of a publication time relative to the event's information window.

    The window runs from the previous trading session's close (15:30 IST) to the event session's close.
    Holidays and weekends are skipped when the previous session is not supplied.
    """
    ts = _parse_any_time(published_iso)
    if ts is None:
        return "unknown"
    prev = prev_session if prev_session is not None else previous_trading_day(event_date)
    window_open = session_close_utc(prev)
    window_close = session_close_utc(event_date)
    if ts <= window_open:
        return "before_window"
    if ts <= window_close:
        return "in_window"
    return "after_close"


TIMING_TEXT = {
    "before_window": "published before the previous session's 15:30 IST close",
    "in_window": "published between the previous session's close and the event-day close (15:30 IST)",
    "after_close": "published after the event-day close, so it cannot have caused the move and may describe it",
    "unknown": "publication time not available",
}


def _norm(text: str) -> str:
    return (text or "").replace("’", "'").replace("‘", "'").replace("&amp;", "&")


def _contains_any(text: str, words: list[str]) -> list[str]:
    t = f" {_norm(text).lower()} "
    hits = []
    for w in words:
        if re.search(r"(?<![a-z0-9])" + re.escape(w.lower()) + r"(?![a-z0-9])", t):
            hits.append(w)
    return hits


def company_terms(universe: Universe, ticker: str) -> list[str]:
    """Names that identify the company in a headline (configured aliases)."""
    sec = universe.get(ticker)
    if sec is None:
        return [ticker.split(".")[0]]
    return list(dict.fromkeys(sec.match_names))


def company_exclusions(universe: Universe, ticker: str) -> list[str]:
    sec = universe.get(ticker)
    return list(sec.exclude) if sec else []


def mentions_company(text: str, names: list[str], exclude: list[str] | tuple = ()) -> bool:
    """True when a configured name appears after removing names of other companies that contain it.

    'Reliance Power shares jump' does not mention Reliance Industries; 'ITC Hotels' does not mention ITC.
    """
    t = _norm(text)
    for ex in exclude:
        t = re.sub(r"(?<![A-Za-z0-9])" + re.escape(ex) + r"(?![A-Za-z0-9])", " ", t, flags=re.IGNORECASE)
    return bool(_contains_any(t, list(names)))


def is_noise_headline(text: str) -> bool:
    t = _norm(text).lower()
    return any(re.search(p, t) for p in NOISE_PATTERNS)


def is_roundup_headline(text: str) -> bool:
    t = _norm(text).lower()
    return any(re.search(p, t) for p in ROUNDUP_PATTERNS)


def heuristic_relevance(item: NewsItem, terms: list[str], exclude: list[str] | tuple = ()) -> None:
    """Fill relevance fields using simple, explainable keyword rules.

    direct:    names the company, published inside the information window, and names a possible cause
    indirect:  market or sector headline without the company name
    uncertain: names the company but has no cause word (for example only reports the move), is a round-up of
               many stocks, or is outside the window
    unrelated: routine holdings report, tip or live price page, or no link to the company or the market
    """
    text = item.headline or ""
    mentions = mentions_company(text, terms, exclude) or item.source_type == "synthetic_demo"
    item.mentions_company = mentions
    catalysts = _contains_any(text, CAUSE_WORDS)
    moves = _contains_any(text, MOVE_WORDS)
    market = _contains_any(text, MARKET_WORDS)
    noise = item.source_type == "news_headline" and is_noise_headline(text)
    roundup = item.source_type == "news_headline" and is_roundup_headline(text)
    if item.source_type == "synthetic_demo":
        if item.timing == "in_window":
            item.relevance, why = "direct", "company announcement (synthetic demo) inside the information window"
        else:
            item.relevance, why = "uncertain", f"company announcement {TIMING_TEXT.get(item.timing, '')}"
    elif noise and mentions:
        item.relevance, why = "unrelated", "tip, live price page or holdings report, not news about the company"
    elif roundup and mentions:
        item.relevance, why = "uncertain", "round-up of several stocks; the headline alone does not show the cause"
    elif mentions and item.timing == "in_window" and catalysts:
        item.relevance, why = "direct", f"names the company and a possible cause ({', '.join(catalysts[:3])}) inside the window"
    elif mentions and item.timing == "in_window" and moves:
        item.relevance, why = "uncertain", "reports the price move inside the window but names no cause"
    elif mentions and item.timing == "after_close":
        item.relevance, why = "uncertain", "names the company but was published after the move"
    elif mentions:
        item.relevance, why = "uncertain", "names the company but no cause keyword or timing match"
    elif market:
        item.relevance, why = "indirect", f"market or sector headline ({', '.join(market[:3])}) without the company name"
    else:
        item.relevance, why = "unrelated", "does not name the company or a market theme"
    item.relevance_basis = "keyword heuristic"
    item.relevance_rationale = why


def build_summary(item: NewsItem) -> str:
    when = TIMING_TEXT.get(item.timing, "")
    if item.source_type == "synthetic_demo":
        extra = f" {item.event_note}." if item.event_note else ""
        return f"Synthetic company announcement in the demonstration dataset (fictional), {when}.{extra}"
    who = item.publisher or "unknown publisher"
    scope = "company-specific headline" if item.mentions_company else "headline without the company name"
    return (f"{scope.capitalize()} from {who}, {when}. The time shown is the publication time; the event it "
            "reports may be earlier.")


def official_links_for(universe: Universe, ticker: str) -> list[dict]:
    """Official pages to check by hand. Link-only: nothing is fetched from them."""
    sec = universe.get(ticker)
    search_for = f"{sec.name} (NSE symbol {sec.exchange_symbol})" if sec else ticker
    return [{**link, "search_for": search_for, "access": "link-only (manual verification)"}
            for link in OFFICIAL_DISCLOSURE_LINKS]


# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

class _JsonFileCache:
    def __init__(self, root: Path):
        self.root = root

    def get(self, name: str, ttl: timedelta):
        path = self.root / name
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stamp = datetime.fromisoformat(payload["_cached_at"])
            if datetime.now(timezone.utc) - stamp < ttl:
                return payload["data"], payload["_cached_at"]
        except Exception:
            return None
        return None

    def put(self, name: str, data) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        (self.root / name).write_text(json.dumps({"_cached_at": stamp, "data": data}), encoding="utf-8")
        return stamp


class GoogleNewsRssProvider:
    name = "Google News RSS (India edition)"
    base = "https://news.google.com/rss/search"

    def __init__(self, timeout: float = 10.0, session=None):
        self.timeout = timeout
        self.session = session

    @staticmethod
    def default_query(search_name: str) -> str:
        """Exact company name plus market words. In Google search syntax OR binds tighter than the implicit AND,
        so this means: the name AND (share OR shares OR stock OR results)."""
        return f'"{search_name}" share OR shares OR stock OR results'

    @staticmethod
    def build_url(query: str, start_date, end_date) -> str:
        q = f"{query} after:{pd.Timestamp(start_date):%Y-%m-%d} before:{pd.Timestamp(end_date):%Y-%m-%d}"
        return f"{GoogleNewsRssProvider.base}?q={quote_plus(q)}&{GOOGLE_NEWS_LOCALE}"

    @staticmethod
    def parse(xml_text: str, ticker: str, retrieved_at: str) -> list[NewsItem]:
        root = ET.fromstring(xml_text)
        out = []
        for node in root.iter("item"):
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            src = node.find("source")
            publisher = src.text.strip() if src is not None and src.text else None
            if publisher and title.endswith(f" - {publisher}"):
                title = title[: -len(f" - {publisher}")].strip()
            pub = _parse_any_time(node.findtext("pubDate"))
            desc = re.sub(r"<[^>]+>", " ", html.unescape(node.findtext("description") or ""))
            desc = re.sub(r"\s+", " ", desc).strip()
            if not title:
                continue
            out.append(NewsItem(
                source_id=f"GN-{_hash(title, link)}",
                headline=title,
                provider=GoogleNewsRssProvider.name,
                source_type="news_headline",
                publisher=publisher,
                published_at=_utc_iso(pub),
                url=link or None,
                tickers=[ticker],
                feed_snippet=desc[:160],
                retrieved_at=retrieved_at,
            ))
        return out

    def search(self, query: str, ticker: str, start_date, end_date) -> tuple[list[NewsItem], ProviderStatus]:
        import requests
        url = self.build_url(query, start_date, end_date)
        sess = self.session or requests
        try:
            resp = sess.get(url, timeout=self.timeout,
                            headers={"User-Agent": "Mozilla/5.0 (compatible; MarketSentinel/2.0; academic project)"})
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP {resp.status_code}")
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            items = self.parse(resp.text, ticker, stamp)
            return items, ProviderStatus(self.name, "ok" if items else "empty", f"{len(items)} headline(s)",
                                         query=query, n_items=len(items), retrieved_at=stamp)
        except Exception as exc:  # noqa: BLE001
            return [], ProviderStatus(self.name, "failed", f"{type(exc).__name__}: {str(exc)[:160]}", query=query)


class YahooFinanceNewsProvider:
    name = "Yahoo Finance headlines (yfinance)"

    def __init__(self, count: int = 20):
        self.count = count

    @staticmethod
    def parse(raw: list[dict], ticker: str, retrieved_at: str) -> list[NewsItem]:
        out = []
        for entry in raw or []:
            c = entry.get("content") if isinstance(entry.get("content"), dict) else entry
            title = (c.get("title") or "").strip()
            if not title:
                continue
            pub = _parse_any_time(c.get("pubDate") or c.get("displayTime") or entry.get("providerPublishTime"))
            provider = c.get("provider") if isinstance(c.get("provider"), dict) else {}
            publisher = provider.get("displayName") or entry.get("publisher")
            url = ((c.get("canonicalUrl") or {}).get("url") if isinstance(c.get("canonicalUrl"), dict) else None) \
                or ((c.get("clickThroughUrl") or {}).get("url") if isinstance(c.get("clickThroughUrl"), dict) else None) \
                or entry.get("link")
            snippet = (c.get("summary") or c.get("description") or "")
            snippet = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(snippet))).strip()
            out.append(NewsItem(
                source_id=f"YF-{_hash(title, url)}",
                headline=title,
                provider="Yahoo Finance headlines (yfinance)",
                source_type="news_headline",
                publisher=publisher,
                published_at=_utc_iso(pub),
                url=url,
                tickers=[ticker],
                feed_snippet=snippet[:160],
                retrieved_at=retrieved_at,
            ))
        return out

    def search(self, ticker: str) -> tuple[list[NewsItem], ProviderStatus]:
        try:
            import yfinance as yf
            raw = yf.Ticker(ticker).get_news(count=self.count, tab="news")
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            items = self.parse(raw, ticker, stamp)
            return items, ProviderStatus(self.name, "ok" if items else "empty",
                                         f"{len(items)} latest headline(s) (not date-searchable)",
                                         query=ticker, n_items=len(items), retrieved_at=stamp)
        except Exception as exc:  # noqa: BLE001
            return [], ProviderStatus(self.name, "failed", f"{type(exc).__name__}: {str(exc)[:160]}", query=ticker)


class DemoAnnouncementsProvider:
    """Synthetic company announcements for the fictional .DEMO securities. Never used in live mode."""

    name = "Synthetic company announcements (fictional)"

    def search(self, ticker: str, start: datetime, end: datetime, last_session) -> tuple[list[NewsItem], ProviderStatus]:
        from providers.market_data import DEMO_ANNOUNCEMENTS, demo_calendar
        cal = demo_calendar()
        out = []
        for sessions_before, tick, hhmm, headline, lag_days, event in DEMO_ANNOUNCEMENTS:
            if tick != ticker:
                continue
            day = cal[-1 - sessions_before]
            hour, minute = (int(x) for x in hhmm.split(":"))
            ts = datetime(day.year, day.month, day.day, hour, minute, tzinfo=MARKET_TZ).astimezone(timezone.utc)
            event_day = (day - pd.Timedelta(days=lag_days)).date()
            if start <= ts <= end:
                out.append(NewsItem(
                    source_id=f"DEMO-{_hash(tick, day)}",
                    headline=headline,
                    provider=self.name,
                    source_type="synthetic_demo",
                    publisher="Synthetic exchange announcement feed (fictional, not a real publication)",
                    published_at=_utc_iso(ts),
                    url=None,
                    tickers=[ticker],
                    retrieved_at=None,
                    event_date=f"{event_day:%Y-%m-%d}",
                    event_note=(f"{event} on {event_day:%d %b %Y}; announcement published {fmt_market_time(ts)}"),
                ))
        return out, ProviderStatus(self.name, "ok" if out else "empty",
                                   f"{len(out)} synthetic announcement(s); fictional company", n_items=len(out))


# ---------------------------------------------------------------------------
# Aggregating service
# ---------------------------------------------------------------------------

class NewsService:
    def __init__(self, settings: Settings, universe: Universe, mode: str, cache_root: Path | None = None,
                 session=None, last_session=None):
        self.settings = settings
        self.universe = universe
        self.mode = mode
        self.last_session = last_session
        timeout = settings.data.news_timeout
        self.cache_root = cache_root or CACHE_DIR
        self.google = GoogleNewsRssProvider(timeout, session)
        self.yahoo = YahooFinanceNewsProvider()
        self.demo = DemoAnnouncementsProvider()

    def search(self, ticker: str, event_date, prev_session=None, days_before: int = 3, days_after: int = 1,
               cutoff: datetime | None = None, query: str | None = None,
               include_yahoo: bool = True) -> NewsSearchResult:
        event_date = pd.Timestamp(event_date)
        prev_session = pd.Timestamp(prev_session) if prev_session is not None else previous_trading_day(event_date)
        start = session_close_utc(shift_trading_days(event_date, -days_before))
        end = session_close_utc(shift_trading_days(event_date, days_after)) if days_after else session_close_utc(event_date)
        if cutoff is not None and cutoff < end:
            end = cutoff
        result = NewsSearchResult(ticker=ticker, event_date=f"{event_date:%Y-%m-%d}", window_start=_utc_iso(start),
                                  window_end=_utc_iso(end), cutoff=_utc_iso(cutoff))
        items: list[NewsItem] = []
        sec = self.universe.get(ticker)
        terms = company_terms(self.universe, ticker)
        exclude = company_exclusions(self.universe, ticker)
        live_names = (GoogleNewsRssProvider.name, YahooFinanceNewsProvider.name)

        if self.mode == "demo":
            demo_items, st = self.demo.search(ticker, start, end, self.last_session or event_date)
            items += demo_items
            result.statuses.append(st)
            for name in live_names:
                result.statuses.append(ProviderStatus(name, "skipped", "Demonstration mode: real news sources are "
                                                                       "not queried for fictional securities."))
            result.statuses.append(ProviderStatus(OFFICIAL_LINKS_PROVIDER, "skipped",
                                                  "Demonstration mode: fictional companies have no NSE/BSE filings."))
        elif not self.settings.data.news_enabled:
            for name in live_names:
                result.statuses.append(ProviderStatus(name, "skipped", "News retrieval disabled in settings (MS_NEWS_ENABLED=false)."))
            result.official_links = official_links_for(self.universe, ticker)
            result.statuses.append(ProviderStatus(OFFICIAL_LINKS_PROVIDER, "link_only", DISCLOSURE_TERMS_NOTE,
                                                  n_items=len(result.official_links)))
        else:
            q = query or GoogleNewsRssProvider.default_query(sec.search_name if sec else ticker.split(".")[0])
            day_end = end.astimezone(timezone.utc).date() + timedelta(days=1)
            gn_items, st = self.google.search(q, ticker, start.date() - timedelta(days=1), day_end)
            gn_items = [i for i in gn_items if i.published_at is None or start <= _parse_any_time(i.published_at) <= end]
            st.n_items = len(gn_items)
            st.message = f"{len(gn_items)} headline(s) inside the window" if st.status != "failed" else st.message
            if st.status == "ok" and not gn_items:
                st.status = "empty"
            items += gn_items
            result.statuses.append(st)
            recent_enough = (datetime.now(timezone.utc) - end) < timedelta(days=10)
            if include_yahoo and recent_enough:
                yf_items, st = self.yahoo.search(ticker)
                yf_items = [i for i in yf_items if i.published_at and start <= _parse_any_time(i.published_at) <= end]
                st.n_items = len(yf_items)
                if st.status == "ok" and not yf_items:
                    st.status = "empty"
                items += yf_items
                result.statuses.append(st)
            else:
                result.statuses.append(ProviderStatus(YahooFinanceNewsProvider.name, "skipped",
                                                      "Only serves the latest headlines; window is too old to reconstruct."))
            result.official_links = official_links_for(self.universe, ticker)
            result.statuses.append(ProviderStatus(OFFICIAL_LINKS_PROVIDER, "link_only", DISCLOSURE_TERMS_NOTE,
                                                  n_items=len(result.official_links)))

        seen = set()
        unique = []
        for it in items:
            key = re.sub(r"[^a-z0-9]", "", it.headline.lower())[:80]
            if key in seen:
                continue
            seen.add(key)
            it.timing = classify_timing(it.published_at, prev_session, event_date)
            heuristic_relevance(it, terms, exclude)
            it.summary = build_summary(it)
            unique.append(it)
        order = {"direct": 0, "indirect": 1, "uncertain": 2, "unrelated": 3}
        unique.sort(key=lambda i: (order.get(i.relevance, 4), i.published_at or ""))
        result.items = unique
        return result
