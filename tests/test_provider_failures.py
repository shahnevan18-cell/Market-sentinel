"""Provider behaviour: parsing documented formats, failures, timeouts, cache fallback and data quality (NSE)."""
import json
import sys
import time
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from analytics.data_quality import check_frame, clean_frame
from config.market import (MARKET_TZ, expected_latest_session, is_partial_session, trading_days, trading_days_ending)
from config.settings import AnalysisConfig, DataConfig, LLMConfig, Settings
from config.watchlist import LIVE_UNIVERSE, Security, Universe
from providers.market_data import (FetchResult, MarketDataProvider, YFinanceProvider, load_live_dataset, make_provider,
                                   normalise_ohlcv)
from providers.news_data import GoogleNewsRssProvider, NewsService, YahooFinanceNewsProvider, classify_timing

FIX = Path(__file__).parent / "fixtures"

# A fictional company, so no test invents news about a real listed company.
TEST_UNIVERSE = Universe(
    key="test", label="Test universe (fictional)",
    securities=(Security("TESTCO.NS", "Testco Industries Ltd. (fictional)", "Industrials", "Testco Industries", False,
                         "Capital Goods", ("Testco Industries", "Testco"), ("Testco Power",)),
                Security("PEERCO.NS", "Peerco Ltd. (fictional)", "Industrials", "Peerco", False, "Capital Goods",
                         ("Peerco",), ())),
    benchmark="^NSEI", benchmark_name="NIFTY 50 (broad-market benchmark)", sector_indices={}, sector_index_names={},
)


# --- Market data -----------------------------------------------------------------

def _yf_like_frame(n=5, end="2026-10-19"):
    """Daily bars as Yahoo returns them for NSE: stamped at midnight India time."""
    days = trading_days_ending(end, n)
    idx = pd.DatetimeIndex([pd.Timestamp(d).tz_localize(MARKET_TZ) for d in days])
    return pd.DataFrame({"Open": np.linspace(100, 104, n), "High": np.linspace(101, 105, n),
                         "Low": np.linspace(99, 103, n), "Close": np.linspace(100.5, 104.5, n),
                         "Adj Close": np.linspace(100.0, 104.0, n), "Volume": [1e6] * n,
                         "Dividends": [0.0] * n, "Stock Splits": [0.0] * n}, index=idx)


def test_normalise_yfinance_frame():
    out = normalise_ohlcv(_yf_like_frame())
    assert list(out.columns) == ["open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]
    assert out.index.tz is None and out.index[-1] == pd.Timestamp("2026-10-19")
    assert out["adj_close"].iloc[-1] == pytest.approx(104.0)


def test_nse_bars_keep_their_india_date():
    """Regression: the US version converted every bar to New York time, which moves a bar stamped
    2026-10-19 00:00 IST to 2026-10-18 (13:30 or 14:30 the previous day in New York)."""
    raw = _yf_like_frame(3, end="2026-10-19")
    assert list(normalise_ohlcv(raw).index) == [pd.Timestamp("2026-10-15"), pd.Timestamp("2026-10-16"),
                                               pd.Timestamp("2026-10-19")]
    old_way = pd.DatetimeIndex(raw.index).tz_convert("America/New_York").tz_localize(None).normalize()
    assert old_way[-1] == pd.Timestamp("2026-10-18")          # the defect this conversion fixed


class _FakeTicker:
    behaviour = "ok"
    currency = "INR"

    def __init__(self, symbol):
        self.symbol = symbol
        self.history_metadata = {"currency": _FakeTicker.currency, "exchangeName": "NSI", "fullExchangeName": "NSE",
                                 "exchangeTimezoneName": "Asia/Kolkata",
                                 "instrumentType": "INDEX" if symbol.startswith("^") else "EQUITY"}

    def history(self, **kwargs):
        if _FakeTicker.behaviour == "down":
            raise ConnectionError("curl: (7) Failed to connect")
        if _FakeTicker.behaviour == "empty":
            return pd.DataFrame()
        return _yf_like_frame(300)


@pytest.fixture
def fake_yf(monkeypatch):
    mod = types.ModuleType("yfinance")
    mod.Ticker = _FakeTicker
    mod.config = types.SimpleNamespace(debug=types.SimpleNamespace(hide_exceptions=True))
    mod.exceptions = types.SimpleNamespace(YFRateLimitError=type("YFRateLimitError", (Exception,), {}))
    monkeypatch.setitem(sys.modules, "yfinance", mod)
    _FakeTicker.behaviour = "ok"
    _FakeTicker.currency = "INR"
    return mod


def test_yfinance_provider_success_records_metadata(fake_yf):
    p = YFinanceProvider(throttle=0.0, max_workers=2)
    res = p.fetch(["RELIANCE.NS", "^NSEI"], pd.Timestamp("2025-01-01"), pd.Timestamp("2026-10-20"))
    assert set(res.frames) == {"RELIANCE.NS", "^NSEI"} and not res.failures
    m = res.meta["RELIANCE.NS"]
    assert m["currency"] == "INR" and m["exchange"] == "NSE" and m["timezone"] == "Asia/Kolkata"
    assert res.meta["^NSEI"]["instrument_type"] == "INDEX"
    assert res.frames["^NSEI"].index[-1] == pd.Timestamp("2026-10-19")


def test_unreachable_provider_stops_quickly(fake_yf):
    _FakeTicker.behaviour = "down"
    p = YFinanceProvider(throttle=0.0, max_workers=3, max_retries=2)
    started = time.perf_counter()
    res = p.fetch([f"S{i}.NS" for i in range(30)], pd.Timestamp("2025-01-01"), pd.Timestamp("2025-07-01"))
    assert len(res.failures) == 30 and not res.frames
    assert any("unreachable" in m for m in res.failures.values())
    assert time.perf_counter() - started < 15


def test_rate_limit_stops_further_requests(fake_yf):
    class RateLimited(_FakeTicker):
        def history(self, **kwargs):
            raise fake_yf.exceptions.YFRateLimitError("Too Many Requests")
    fake_yf.Ticker = RateLimited
    p = YFinanceProvider(throttle=0.0, max_workers=1)
    res = p.fetch(["A.NS", "B.NS", "C.NS"], pd.Timestamp("2025-01-01"), pd.Timestamp("2025-07-01"))
    assert "Rate limited" in res.failures["A.NS"]
    assert all("rate-limited" in res.failures[s] for s in ("B.NS", "C.NS"))


def test_only_the_nse_provider_is_offered():
    s = Settings(analysis=AnalysisConfig(), data=DataConfig(provider="tiingo"), llm=LLMConfig())
    with pytest.raises(ValueError, match=r"\.NS"):
        make_provider(s)


class _ScriptedProvider(MarketDataProvider):
    key = "scripted"
    label = "Scripted test provider"

    def __init__(self, frames=None, fail=False, clock=None, currency="INR"):
        self.frames = frames or {}
        self.fail = fail
        self.calls = 0
        self.clock = clock
        self.currency = currency

    def fetch(self, symbols, start, end):
        self.calls += 1
        res = FetchResult()
        for s in symbols:
            if self.fail:
                res.failures[s] = "TimeoutError: read timed out"
            else:
                res.frames[s] = self.frames.get(s, self.frames["__default__"])
                res.meta[s] = {"currency": self.currency, "exchange": "NSE", "timezone": "Asia/Kolkata"}
        if self.clock is not None:
            res.retrieved_at = self.clock
        return res


def _settings():
    return Settings(analysis=AnalysisConfig(), data=DataConfig(cache_ttl_hours=6), llm=LLMConfig())


def _nse_frame(n, end, frame_factory):
    """Synthetic test prices on real NSE sessions (weekends and listed holidays excluded)."""
    days = trading_days_ending(end, n)
    f = frame_factory(np.linspace(100, 120, n))
    f.index = pd.DatetimeIndex(days, name="date")
    return f


def test_cache_then_stale_fallback_keeps_original_timestamp(tmp_path, frame_factory):
    frame = _nse_frame(300, "2025-09-30", frame_factory)
    t0 = datetime(2025, 10, 1, 12, 0, tzinfo=timezone.utc)          # 17:30 IST, after the day was final
    ok = _ScriptedProvider({"__default__": frame}, clock=t0)
    ds1 = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=ok, cache_root=tmp_path, now=t0)
    assert len(ds1.frames) == len(LIVE_UNIVERSE.all_symbols)
    assert {m.status for m in ds1.meta.values()} == {"live"}

    ds2 = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=ok, cache_root=tmp_path, now=t0 + timedelta(hours=1))
    assert ok.calls == 1                                    # fresh cache: no second download
    assert {m.status for m in ds2.meta.values()} == {"cache"}

    failing = _ScriptedProvider(fail=True)
    later = t0 + timedelta(days=2)
    ds3 = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=failing, cache_root=tmp_path, now=later)
    assert {m.status for m in ds3.meta.values()} == {"cache-stale"}
    assert all(m.retrieved_at == "2025-10-01T12:00:00+00:00" for m in ds3.meta.values())
    assert ds3.freshness(now=later)["is_stale"] is True
    assert ds3.mode == "live"                              # never switched to demo data


def test_no_cache_and_failure_gives_no_synthetic_data(tmp_path):
    ds = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=_ScriptedProvider(fail=True), cache_root=tmp_path)
    assert ds.frames == {} and len(ds.failures) == len(LIVE_UNIVERSE.all_symbols)
    assert ds.mode == "live" and all(q.status == "Error" for q in ds.quality.values())


def test_non_inr_data_is_flagged_and_never_relabelled(tmp_path, frame_factory):
    frame = _nse_frame(300, "2026-09-30", frame_factory)
    now = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)
    ds = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=_ScriptedProvider({"__default__": frame}, clock=now,
                                                                                 currency="USD"),
                           cache_root=tmp_path, now=now)
    assert ds.meta["RELIANCE.NS"].currency == "USD"                     # kept as reported
    codes = {i.code for i in ds.quality["RELIANCE.NS"].issues}
    assert "currency_mismatch" in codes
    assert ds.freshness(now=now)["currencies"] == ["USD"]


# --- Data quality ----------------------------------------------------------------------

def test_cleaning_and_quality_checks(frame_factory):
    f = frame_factory(np.linspace(100, 110, 120))
    bad_day = f.index[20]
    f.loc[bad_day, "close"] = -5                                        # impossible price
    f.iloc[60:, f.columns.get_loc("adj_close")] *= 1.4                  # 40% gap
    f = pd.concat([f, f.iloc[[10]]]).sort_index()                       # duplicate date
    cleaned, actions = clean_frame(f)
    assert cleaned.index.is_unique and any("duplicated" in a for a in actions)
    assert np.isnan(cleaned.loc[bad_day, "close"])
    rep = check_frame("TEST.NS", cleaned, currency="USD", expected_currency="INR", min_required=200,
                      retrieved_at=datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc))
    codes = {i.code for i in rep.issues}
    assert {"short_history", "large_gaps", "currency_mismatch", "stale"} <= codes
    assert rep.status == "Warning"
    gap = next(i for i in rep.issues if i.code == "large_gaps")
    assert "bonus issue" in gap.message and "demerger" in gap.message


@pytest.mark.parametrize("currency,code", [("INR", None), ("USD", "currency_mismatch"), (None, "currency_unknown")])
def test_currency_metadata_is_validated(currency, code, frame_factory):
    f = _nse_frame(150, "2026-09-30", frame_factory)
    rep = check_frame("X.NS", f, currency=currency, expected_currency="INR", min_required=100)
    codes = {i.code for i in rep.issues}
    if code is None:
        assert not codes & {"currency_mismatch", "currency_unknown"}
    else:
        assert code in codes


def test_session_timing_helpers_use_india_time():
    # 19 Oct 2026 is a Monday. 14:00 IST is during the session; the day is final after 16:15 IST.
    during = datetime(2026, 10, 19, 8, 30, tzinfo=timezone.utc)      # 14:00 IST
    after = datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc)       # 16:30 IST
    assert is_partial_session(pd.Timestamp("2026-10-19"), during) is True
    assert is_partial_session(pd.Timestamp("2026-10-19"), after) is False
    assert expected_latest_session(during) == pd.Timestamp("2026-10-16")
    assert expected_latest_session(after) == pd.Timestamp("2026-10-19")
    # 20 Oct 2026 is an NSE holiday (Dussehra): no new session is expected that day.
    assert expected_latest_session(datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)) == pd.Timestamp("2026-10-19")
    # Late evening in New York is already the next morning in India, before that day's session is final.
    assert expected_latest_session(datetime(2026, 10, 21, 2, 0, tzinfo=timezone.utc)) == pd.Timestamp("2026-10-19")


def test_weekend_special_session_bar_is_kept_and_reported(frame_factory):
    """NSE holds occasional weekend sessions (Muhurat trading on Sunday 8 Nov 2026). Such a bar is kept."""
    days = list(trading_days("2026-09-01", "2026-11-06")) + [pd.Timestamp("2026-11-08")]
    f = frame_factory(np.linspace(100, 110, len(days)))
    f.index = pd.DatetimeIndex(days, name="date")
    cleaned, _ = clean_frame(f)
    assert pd.Timestamp("2026-11-08") in cleaned.index
    rep = check_frame("X.NS", cleaned, currency="INR", min_required=10)
    special = next(i for i in rep.issues if i.code == "special_sessions")
    assert special.level == "info" and "Muhurat" in special.message


def test_suspension_gap_gives_no_return_across_it(cfg, frame_factory):
    """A stock missing ten NSE sessions (for example a suspension) gets no return for the day it resumes."""
    from analytics.anomaly_detection import build_panel
    days = trading_days_ending("2026-09-30", 200)
    bench = frame_factory(np.linspace(20000, 21000, 200))
    bench.index = days
    stock = frame_factory(np.linspace(100, 130, 200))
    stock.index = days
    stock = stock.drop(days[150:160])
    panel = build_panel({"^NSEI": bench, "X.NS": stock}, "^NSEI", cfg)
    assert np.isnan(panel.returns.loc[days[160], "X.NS"])            # first day back: no return across the gap
    assert not np.isnan(panel.returns.loc[days[161], "X.NS"])
    rep = check_frame("X.NS", stock, calendar=bench.index, currency="INR", min_required=100)
    assert "missing_dates" in {i.code for i in rep.issues}


# --- News -------------------------------------------------------------------------

def test_google_news_parser():
    items = GoogleNewsRssProvider.parse((FIX / "google_news_rss.xml").read_text(encoding="utf-8"), "TESTCO.NS",
                                        "2026-09-30T12:00:00+00:00")
    assert len(items) == 3
    first = items[0]
    assert first.headline == "Testco Industries Q2 results: net profit falls 18% as provisions rise"
    assert first.publisher == "Example Business Daily"
    assert first.published_at == "2026-09-29T12:40:00+00:00"
    assert first.retrieved_at == "2026-09-30T12:00:00+00:00"           # retrieval time kept apart from publication
    assert first.url.startswith("https://news.google.com/rss/articles/")


def test_google_news_url_uses_the_india_edition():
    url = GoogleNewsRssProvider.build_url('"Testco Industries" share OR shares OR stock OR results',
                                          "2026-09-24", "2026-10-02")
    assert url.endswith("&hl=en-IN&gl=IN&ceid=IN:en")
    assert "after%3A2026-09-24" in url and "before%3A2026-10-02" in url


def test_yahoo_news_parser_handles_old_and_new_formats():
    raw = json.loads((FIX / "yahoo_news.json").read_text(encoding="utf-8"))
    items = YahooFinanceNewsProvider.parse(raw, "TESTCO.NS", "2025-03-05T00:00:00+00:00")
    assert [i.publisher for i in items] == ["Fixture News", "Legacy Fixture"]
    assert items[0].url == "https://example.com/fixture/a1"
    assert items[1].published_at is not None


def test_timing_classification_uses_the_1530_ist_close():
    prev, day = pd.Timestamp("2026-09-29"), pd.Timestamp("2026-09-30")
    assert classify_timing("2026-09-29T09:00:00+00:00", prev, day) == "before_window"   # 14:30 IST, before the close
    assert classify_timing("2026-09-29T12:35:00+00:00", prev, day) == "in_window"       # 18:05 IST, after hours
    assert classify_timing("2026-09-30T09:59:00+00:00", prev, day) == "in_window"       # 15:29 IST on the day
    assert classify_timing("2026-09-30T11:00:00+00:00", prev, day) == "after_close"     # 16:30 IST
    assert classify_timing(None, prev, day) == "unknown"
    # Holidays are skipped when the previous session is not given: 20 Oct 2026 is Dussehra.
    assert classify_timing("2026-10-20T06:00:00+00:00", None, pd.Timestamp("2026-10-21")) == "in_window"


def test_all_news_sources_failing_is_reported(settings, fake_session_cls, monkeypatch, tmp_path):
    import providers.news_data as nd
    monkeypatch.setattr(nd.YahooFinanceNewsProvider, "search",
                        lambda self, t: ([], nd.ProviderStatus(self.name, "failed", "TimeoutError")))
    svc = NewsService(settings, TEST_UNIVERSE, "live", session=fake_session_cls(error=TimeoutError("timed out")),
                      cache_root=tmp_path)
    res = svc.search("TESTCO.NS", pd.Timestamp.now().normalize(), include_yahoo=True)
    assert res.items == []
    assert res.all_failed and not res.any_provider_ok           # the link-only entry does not count as a search
    assert any(s.status == "link_only" for s in res.statuses) and res.official_links


def test_india_news_search_through_the_service(settings, fake_session_cls, fake_response_cls, tmp_path):
    session = fake_session_cls({
        "news.google.com": fake_response_cls(200, text=(FIX / "google_news_rss.xml").read_text(encoding="utf-8")),
    })
    svc = NewsService(settings, TEST_UNIVERSE, "live", session=session, cache_root=tmp_path)
    res = svc.search("TESTCO.NS", pd.Timestamp("2026-09-30"), prev_session=pd.Timestamp("2026-09-29"),
                     include_yahoo=False)
    assert "hl=en-IN&gl=IN&ceid=IN:en" in session.calls[0]
    by_id = {i.headline: i for i in res.items}
    results = by_id["Testco Industries Q2 results: net profit falls 18% as provisions rise"]
    assert results.timing == "in_window" and results.relevance == "direct"
    market = by_id["Sensex, Nifty end lower as FIIs sell banking stocks"]
    assert market.timing == "after_close" and market.relevance == "indirect"
    assert "Testco Industries launches a new product range" not in by_id     # published before the window opened
    assert all(i.relevance_basis == "keyword heuristic" for i in res.items)
    statuses = {s.provider: s.status for s in res.statuses}
    assert statuses["NSE/BSE official disclosures (link-only)"] == "link_only"
    assert res.official_links and all(link["access"].startswith("link-only") for link in res.official_links)
    assert all("nseindia.com" in link["url"] or "bseindia.com" in link["url"] or "sebi.gov.in" in link["url"]
               for link in res.official_links)


def test_bar_cached_mid_session_is_refetched_after_the_close(tmp_path, frame_factory):
    frame = _nse_frame(520, "2026-10-19", frame_factory)                        # last bar on Monday 19 Oct 2026
    assert frame.index[-1] == pd.Timestamp("2026-10-19")
    during = datetime(2026, 10, 19, 8, 30, tzinfo=timezone.utc)                 # 14:00 IST, session open
    p1 = _ScriptedProvider({"__default__": frame}, clock=during)
    ds1 = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=p1, cache_root=tmp_path, now=during)
    assert all(m.partial_last_bar for m in ds1.meta.values())
    assert pd.Timestamp("2026-10-19") in ds1.partial_dates()                    # excluded from detection
    f1 = ds1.freshness(now=during)
    assert f1["latest_bar"] == "2026-10-16" and f1["partial_bar"] == "2026-10-19"   # Friday is the last complete one
    assert f1["session_lag"] == 0 and not f1["is_stale"]
    after = datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc)                  # 16:30 IST, within the 6 h TTL
    p2 = _ScriptedProvider({"__default__": frame}, clock=after)
    ds2 = load_live_dataset(LIVE_UNIVERSE, _settings(), provider=p2, cache_root=tmp_path, now=after)
    assert p2.calls == 1                                                         # refetched despite fresh TTL
    assert not any(m.partial_last_bar for m in ds2.meta.values())
    assert ds2.freshness(now=after)["latest_bar"] == "2026-10-19" and ds2.freshness(now=after)["partial_bar"] is None


@pytest.mark.parametrize("headline,expected", [
    ("Testco Q2 results: net profit falls on higher provisions", "direct"),
    ("Testco bags ₹1,200 crore order from a state metro corporation", "direct"),
    ("SEBI issues show cause notice to Testco over disclosure lapse", "direct"),
    ("Why is Testco share price falling today?", "uncertain"),
    ("Testco shares tank 6% in afternoon trade", "uncertain"),
    ("Stocks to watch: Testco, Peerco and others", "uncertain"),
    ("Testco share price live updates", "unrelated"),
    ("Should you buy Testco shares after the fall?", "unrelated"),
    ("Sensex, Nifty end lower as FIIs sell banking stocks", "indirect"),
    ("Testco Power shares jump after tariff order", "unrelated"),     # a different company with a similar name
])
def test_headline_rules_separate_causes_moves_and_noise(headline, expected):
    from providers.news_data import NewsItem, heuristic_relevance
    item = NewsItem(source_id="x", headline=headline, provider="Google News RSS (India edition)",
                    source_type="news_headline", timing="in_window")
    heuristic_relevance(item, ["Testco Industries", "Testco"], ["Testco Power"])
    assert item.relevance == expected, item.relevance_rationale


def test_failed_live_load_is_not_retried_on_every_click(monkeypatch):
    """A failed live load is reused for a short time; Refresh market data (force) retries at once."""
    import streamlit as st

    from providers.market_data import MarketDataset
    from ui import state

    calls = []

    def failing_load(force):
        calls.append(force)
        return MarketDataset(frames={}, meta={}, universe=state.get_universe("live"), mode="live",
                             provider_label="test", loaded_at="2026-10-20T00:00:00+00:00",
                             failures={"^NSEI": "ConnectionError"})

    monkeypatch.setattr(state, "_load_live", failing_load)
    monkeypatch.setattr(state, "_DATASETS", {})
    monkeypatch.setattr(state, "_FAILED", {})
    st.session_state.mode = "live"
    first = state.get_dataset()
    second = state.get_dataset()
    assert not first.frames and second is first and calls == [False]      # no second network attempt
    state.get_dataset(force=True)
    assert calls == [False, True]                                         # an explicit refresh always retries
