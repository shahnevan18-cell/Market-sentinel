"""Indian market conventions: watchlist and symbols, NSE calendar, rupee formatting, symbol validation and
company-name matching. Everything here runs offline; live symbol checks are in scripts/validate_symbols.py."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import market as mkt
from config.watchlist import DEMO_UNIVERSE, LIVE_UNIVERSE
from providers.market_data import FetchResult, MarketDataProvider
from providers.news_data import company_exclusions, company_terms, mentions_company
from providers.symbol_validation import summary, validate_universe

ROOT = Path(__file__).resolve().parents[1]


# --- Watchlist and provider symbols ------------------------------------------------------------------------

def test_live_watchlist_is_25_nse_shares_with_the_nifty_benchmark():
    u = LIVE_UNIVERSE
    assert len(u.tickers) == 25 and len(set(u.tickers)) == 25
    assert all(t.endswith(".NS") for t in u.tickers)
    assert u.benchmark == "^NSEI" and u.short_label("^NSEI") == "NIFTY 50"
    assert u.currency == "INR"
    assert "WIPRO.NS" not in u.tickers                        # left the NIFTY 50 on 30 Sep 2026
    for us in ("SPY", "AAPL", "XLK", "XLF", "MSFT", "BAC"):
        assert us not in u.all_symbols


def test_sector_indices_belong_to_real_groups_and_others_are_peer_only():
    u = LIVE_UNIVERSE
    assert set(u.sector_indices) <= set(u.sectors)
    # NIFTY Energy, FMCG and Auto failed the live symbol check on 20 Oct 2026 (3 sessions of history) and were removed
    assert set(u.sector_indices.values()) == {"^NSEBANK", "^CNXIT", "^CNXPHARMA"}
    for removed in ("^CNXENERGY", "^CNXFMCG", "^CNXAUTO"):
        assert removed not in u.all_symbols
    peer_only = [g for g in u.sectors if g not in u.sector_indices]
    assert set(peer_only) == {"Oil, gas & power", "FMCG", "Autos", "Consumer durables", "Cement & steel",
                              "Construction", "Telecom"}
    assert u.peers_of("LT.NS") == [] and u.peers_of("BHARTIARTL.NS") == []   # documented: no peer in the watchlist
    for t in u.tickers:
        if t not in ("LT.NS", "BHARTIARTL.NS"):
            assert u.peers_of(t), t


def test_bare_nse_symbols_resolve_to_provider_symbols():
    assert LIVE_UNIVERSE.resolve("reliance") == "RELIANCE.NS"
    assert LIVE_UNIVERSE.resolve("M&M") == "M&M.NS"
    assert LIVE_UNIVERSE.resolve("^NSEI") == "^NSEI"
    assert LIVE_UNIVERSE.resolve("AAPL") is None
    assert LIVE_UNIVERSE.get("M&M.NS").exchange_symbol == "M&M"


def test_demo_universe_is_fictional_and_labelled():
    for s in DEMO_UNIVERSE.securities:
        assert s.ticker.endswith(".DEMO") and s.is_synthetic and "(fictional)" in s.name
    assert not set(DEMO_UNIVERSE.tickers) & set(LIVE_UNIVERSE.tickers)


# --- Symbol validation (fake provider; the live run is scripts/validate_symbols.py) ----------------------

class _Provider(MarketDataProvider):
    key = "fake"
    label = "fake"

    def __init__(self, bad=None):
        self.bad = bad or {}

    def fetch(self, symbols, start, end):
        res = FetchResult()
        days = mkt.trading_days_ending("2026-10-19", 400)
        for s in symbols:
            kind = self.bad.get(s)
            if kind == "missing":
                res.failures[s] = "Provider returned no rows (symbol may be invalid or delisted)."
                continue
            n = 90 if kind == "short" else 400
            f = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "adj_close": 1.0,
                              "volume": 0.0 if kind == "novol" else 1e6, "dividends": 0.0, "splits": 0.0},
                             index=days[-n:])
            if kind == "stale":
                f = f.iloc[:-10]
            res.frames[s] = f
            res.meta[s] = {"currency": "USD" if kind == "usd" else "INR",
                           "exchange": "BSE" if s == "^BSESN" else "NSE", "timezone": "Asia/Kolkata",
                           "instrument_type": "INDEX" if s.startswith("^") else "EQUITY"}
        return res


NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)      # 17:30 IST on an NSE holiday


def test_all_configured_symbols_pass_when_the_provider_returns_good_data():
    checks = validate_universe(LIVE_UNIVERSE, _Provider(), now=NOW)
    s = summary(checks)
    assert s["total"] == len(LIVE_UNIVERSE.all_symbols) == 30 and s["fail"] == 0 and s["warn"] == 0
    roles = {c.symbol: c.role for c in checks}
    assert roles["^NSEI"] == "benchmark" and roles["^CNXIT"] == "sector index" and roles["^BSESN"] == "display index"


@pytest.mark.parametrize("kind,status,needle", [
    ("missing", "FAIL", "No data from the provider"),
    ("usd", "FAIL", "must not be relabelled"),
    ("short", "FAIL", "estimate beta"),
    ("stale", "WARN", "sessions behind"),
    ("novol", "WARN", "No positive volume"),
])
def test_failed_or_doubtful_symbols_are_reported_not_kept_quietly(kind, status, needle):
    checks = validate_universe(LIVE_UNIVERSE, _Provider({"TCS.NS": kind}), now=NOW)
    tcs = next(c for c in checks if c.symbol == "TCS.NS")
    assert tcs.status == status and any(needle in p for p in tcs.problems), tcs.problems
    if status == "FAIL":
        assert summary(checks)["failed_symbols"] == ["TCS.NS"]


# --- NSE calendar and sessions ------------------------------------------------------------------------------

def test_nse_holidays_and_trading_days():
    assert not mkt.is_trading_day("2026-10-20")                # Dussehra
    assert mkt.is_trading_day("2026-10-21")
    assert not mkt.is_trading_day("2026-01-26") and not mkt.is_trading_day("2026-10-02")
    assert not mkt.is_trading_day("2026-10-24")                # Saturday
    assert mkt.holiday_name("2026-11-10") == "Diwali-Balipratipada"
    assert mkt.next_trading_day("2026-10-19") == pd.Timestamp("2026-10-21")
    assert mkt.previous_trading_day("2026-10-21") == pd.Timestamp("2026-10-19")
    assert mkt.sessions_between("2026-10-16", "2026-10-21") == 2     # 19 and 21 October; 20 is a holiday
    assert len(mkt.trading_days("2026-01-01", "2026-12-31")) == 261 - 16   # weekdays minus 16 weekday holidays


def test_session_times_in_utc():
    assert mkt.session_close_utc("2026-10-21").isoformat() == "2026-10-21T10:00:00+00:00"   # 15:30 IST
    assert mkt.session_open_utc("2026-10-21").isoformat() == "2026-10-21T03:45:00+00:00"    # 09:15 IST
    assert mkt.bar_final_utc("2026-10-21").isoformat() == "2026-10-21T10:45:00+00:00"       # 16:15 IST
    assert mkt.fmt_market_time("2026-10-21T10:45:00+00:00") == "21 Oct 2026, 16:15 IST"


def test_partial_bar_is_detected_in_india_time_whatever_the_server_zone():
    # 23:00 UTC on 20 Oct is 04:30 IST on 21 Oct: a bar dated 21 Oct then is not final.
    assert mkt.is_partial_session("2026-10-21", datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc))
    assert not mkt.is_partial_session("2026-10-19", datetime(2026, 10, 20, 23, 0, tzinfo=timezone.utc))


def test_demo_calendar_follows_nse_trading_days():
    from providers.market_data import demo_calendar
    cal = demo_calendar()
    assert cal[-1] == pd.Timestamp("2026-09-30") and len(cal) == 520
    assert all(mkt.is_trading_day(d) for d in cal)
    assert pd.Timestamp("2026-09-14") not in cal                 # Ganesh Chaturthi


# --- Rupee formatting -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("value,grouped,short", [
    (999, "₹999", "₹999"),
    (100000, "₹1,00,000", "₹1.00 lakh"),
    (1234567, "₹12,34,567", "₹12.35 lakh"),
    (10_000_000, "₹1,00,00,000", "₹1.00 crore"),
    (-245000, "-₹2,45,000", "-₹2.45 lakh"),
])
def test_rupee_formatting_uses_indian_grouping(value, grouped, short):
    assert mkt.fmt_inr(value) == grouped and mkt.fmt_inr_short(value) == short
    assert mkt.fmt_inr(None) == "n/a" and mkt.fmt_inr(np.nan) == "n/a"


# --- Company names in headlines --------------------------------------------------------------------------------

@pytest.mark.parametrize("ticker,text,expected", [
    ("RELIANCE.NS", "RIL share price", True),
    ("RELIANCE.NS", "Reliance Industries share price", True),
    ("RELIANCE.NS", "Reliance Power share price", False),
    ("RELIANCE.NS", "Jio Financial share price", False),
    ("ITC.NS", "ITC share price", True),
    ("ITC.NS", "ITC Hotels share price", False),
    ("M&M.NS", "M&M share price", True),
    ("M&M.NS", "Tech Mahindra share price", False),
    ("M&M.NS", "Kotak Mahindra Bank share price", False),
    ("HDFCBANK.NS", "HDFC Life share price", False),
    ("SBIN.NS", "SBI share price", True),
    ("SBIN.NS", "SBI Life share price", False),
    ("NTPC.NS", "NTPC Green share price", False),
    ("LT.NS", "L&T share price", True),
    ("LT.NS", "L&T Finance share price", False),
    ("BHARTIARTL.NS", "Bharti Hexacom share price", False),
    ("HINDUNILVR.NS", "HUL share price", True),
])
def test_company_aliases_and_look_alike_names(ticker, text, expected):
    names = company_terms(LIVE_UNIVERSE, ticker)
    assert mentions_company(text, names, company_exclusions(LIVE_UNIVERSE, ticker)) is expected


# --- No US market conventions in what the app shows or sends to the model --------------------------------------

US_TOKENS = ("SEC EDGAR", "EDGAR", "8-K", "SPDR", "S&P 500", "New York", "America/New_York", "Wall Street", "NYSE",
             "Nasdaq", "USD", "Tiingo", "sector fund", "sector ETF")


def test_no_us_market_terms_in_interface_agents_or_reports():
    files = [p for d in ("ui", "reports", "agents", "config", "scripts") for p in (ROOT / d).rglob("*.py")]
    files += [ROOT / "app.py", ROOT / "providers" / "news_data.py", ROOT / "providers" / "symbol_validation.py"]
    found = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in US_TOKENS:
            if token in text:
                found.append(f"{path.relative_to(ROOT)}: {token}")
    assert not found, found


# --- The live NSE path end to end, on labelled test prices (no network) ------------------------------------------

class _LiveLikeProvider(MarketDataProvider):
    """Synthetic test prices for every live symbol on real NSE sessions, with planted moves. Test data only."""
    key = "live-like-test"
    label = "Test provider (synthetic prices for live symbols)"

    def fetch(self, symbols, start, end):
        rng = np.random.default_rng(7)
        days = mkt.trading_days_ending("2026-09-30", 320)
        n = len(days)
        market = rng.normal(0.0004, 0.009, n)
        res = FetchResult()
        for s in symbols:
            r = market.copy() if s.startswith("^") else 0.9 * market + rng.normal(0, 0.012, n)
            vol = np.full(n, 0.0) if s.startswith("^") else rng.lognormal(14, 0.2, n)
            if s == "LT.NS":
                r[-1], vol[-1] = 0.085, vol[-1] * 6          # isolated jump on the last session
            close = 1000 * np.cumprod(1 + r)
            res.frames[s] = pd.DataFrame({"open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
                                          "adj_close": close, "volume": vol, "dividends": 0.0, "splits": 0.0},
                                         index=pd.DatetimeIndex(days, name="date"))
            res.meta[s] = {"currency": "INR", "exchange": "BSE" if s == "^BSESN" else "NSE",
                           "timezone": "Asia/Kolkata", "instrument_type": "INDEX" if s.startswith("^") else "EQUITY"}
        res.retrieved_at = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
        return res


def test_live_nse_path_runs_end_to_end_for_a_stock_without_peers_or_sector_index(settings, tmp_path,
                                                                                    fake_session_cls,
                                                                                    fake_response_cls):
    from agents.orchestrator import run_investigation
    from agents.sentinel_monitor import SentinelMonitor
    from providers.market_data import load_live_dataset
    from providers.news_data import NewsService
    from reports.report_builder import build_markdown

    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)                 # 17:30 IST, the day is final
    ds = load_live_dataset(LIVE_UNIVERSE, settings, provider=_LiveLikeProvider(), cache_root=tmp_path, now=now)
    assert not ds.failures and ds.freshness(now=now)["latest_bar"] == "2026-09-30"
    assert ds.freshness(now=now)["currencies"] == ["INR"]
    mon = SentinelMonitor(settings.analysis).run(ds)
    assert "LT.NS:2026-09-30" in set(mon.events["event_id"])
    empty_rss = '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title></channel></rss>'
    news = NewsService(settings, LIVE_UNIVERSE, "live", cache_root=tmp_path,
                       session=fake_session_cls({"news.google.com": fake_response_cls(200, text=empty_rss)}))
    rec = run_investigation("LT.NS:2026-09-30", ds, settings, scan=mon.scan, news_service=news, save=False)
    peers = rec.evidence["compare_with_peers"]
    assert peers["n_peers"] == 0 and peers["sector_index"] is None
    h2 = next(r for r in rec.rubric["results"] if r["id"] == "H2")
    assert any("No sector index is configured" in c["evidence"] for c in h2["criteria"])
    assert rec.evidence["compare_with_benchmark"]["benchmark_name"] == "NIFTY 50"
    assert rec.data["benchmark_name"] == "NIFTY 50" and rec.data["symbol_currency"] == "INR"
    assert rec.official_links and rec.news == []
    statuses = {s["provider"]: s["status"] for s in rec.news_statuses}
    assert statuses["Google News RSS (India edition)"] == "empty"
    assert statuses["NSE/BSE official disclosures (link-only)"] == "link_only"
    assert rec.rubric["leading"] == "H4"                              # searched, nothing found, stock-specific move
    md = build_markdown(rec.as_dict())
    assert "NIFTY 50" in md and "link-only" in md and "Larsen & Toubro" in md
    assert "No public explanation was found in the sources searched" in md
