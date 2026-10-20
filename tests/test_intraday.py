"""Intraday 5-minute bars: normalisation, market clock, refresh status, cache policy and time-of-day detection.

All bars here are synthetic test data (tests/intraday_fakes.py); no provider is called.
"""
import ast
import threading
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analytics.intraday import MIN_SESSIONS, bar_measures, scan_intraday
from config.market import MARKET_TZ
from providers import intraday as pi
from providers.intraday import (IntradayStore, describe_data_state, expected_latest_bar, market_phase,
                                normalise_intraday)
from tests.intraday_fakes import SESSIONS, Clock, FakeFetcher, market_path, synth_raw, u_shape, utc

ROOT = Path(__file__).resolve().parents[1]
BENCH = "^NSEI"


def _ts(ist):
    return pd.Timestamp(ist, tz=MARKET_TZ)


# --- Normalisation -----------------------------------------------------------------------------------------

def test_bars_are_read_in_ist_and_irregular_rows_are_dropped_not_repaired():
    idx = pd.DatetimeIndex(["2026-10-19 03:45:00", "2026-10-19 03:50:00", "2026-10-19 03:50:00",   # 09:15, 09:20 x2
                            "2026-10-19 03:57:43",                                                  # off the grid
                            "2026-10-19 03:40:00",                                                  # 09:10, pre-open
                            "2026-10-19 10:00:00",                                                  # 15:30, after close
                            "2026-10-19 04:00:00"], tz="UTC")                                       # 09:30, no price
    raw = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": [10, 11, 12, 13, 9, 14, np.nan],
                        "Volume": [100, 0, 50, 7, 5, 5, 5]}, index=idx)
    frame, notes = normalise_intraday(raw, 5, utc("2026-10-19 18:00"))
    assert [f"{t:%H:%M}" for t in frame.index] == ["09:15", "09:20"]
    assert str(frame.index.tz) == "Asia/Kolkata" and list(frame["slot"]) == [0, 1]
    assert frame["close"].tolist() == [10, 12]                       # the later duplicate wins
    assert notes == {"rows_received": 7, "outside_session": 2, "off_grid": 1, "duplicates": 1, "no_price": 1,
                     "volume_missing": 0}
    assert len(frame) <= len(raw)                                     # nothing is ever added


def test_forming_bar_is_flagged_and_missing_volume_is_not_zero():
    idx = pd.DatetimeIndex([_ts("2026-10-21 11:00"), _ts("2026-10-21 11:05")])
    raw = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": [100.0, 101.0], "Volume": [0.0, 900.0]},
                       index=idx)
    frame, notes = normalise_intraday(raw, 5, utc("2026-10-21 11:07"))
    assert frame["partial"].tolist() == [False, True]                 # 11:05 to 11:10 has not finished at 11:07
    assert np.isnan(frame["volume"].iloc[0]) and notes["volume_missing"] == 1
    index_frame, index_notes = normalise_intraday(raw, 5, utc("2026-10-21 11:07"), is_index=True)
    assert np.isnan(index_frame["volume"].iloc[0]) and index_notes["volume_missing"] == 0
    naive = raw.set_axis(pd.DatetimeIndex(["2026-10-21 05:30", "2026-10-21 05:35"]), axis=0)   # naive means UTC
    assert [f"{t:%H:%M}" for t in normalise_intraday(naive, 5, utc("2026-10-21 12:00"))[0].index] == ["11:00", "11:05"]


# --- Market clock ------------------------------------------------------------------------------------------

def test_market_phase_on_a_holiday_evening():
    ph = market_phase(utc("2026-10-20 22:21"))                        # Dussehra
    assert not ph.trading_day and ph.holiday == "Dussehra" and not ph.requests_useful
    assert str(ph.last_session) == "2026-10-19" and f"{ph.next_open:%Y-%m-%d %H:%M}" == "2026-10-21 09:15"
    assert f"{expected_latest_bar(ph, 5):%Y-%m-%d %H:%M}" == "2026-10-19 15:25"


@pytest.mark.parametrize("ist,expected", [("2026-10-21 11:07", "11:00"), ("2026-10-21 09:20", "09:15"),
                                          ("2026-10-21 09:17", None), ("2026-10-21 15:33", "15:25")])
def test_expected_latest_bar_during_the_session(ist, expected):
    bar = expected_latest_bar(market_phase(utc(ist)), 5)
    assert (None if bar is None else f"{bar:%H:%M}") == expected


def test_weekend_and_pre_open():
    sat = market_phase(utc("2026-10-24 12:00"))
    assert not sat.trading_day and sat.holiday is None and str(sat.last_session) == "2026-10-23"
    early = market_phase(utc("2026-10-21 08:30"))
    assert early.trading_day and not early.is_open and f"{early.next_open:%d %H:%M}" == "21 09:15"


# --- Status wording ----------------------------------------------------------------------------------------

def test_status_fresh_waiting_and_closed():
    open_ph = market_phase(utc("2026-10-21 11:07"))
    assert describe_data_state(open_ph, _ts("2026-10-21 11:00"), _ts("2026-10-21 10:55"), 5)[0] == "fresh"
    st_, text = describe_data_state(open_ph, _ts("2026-10-21 11:00"), _ts("2026-10-21 11:00"), 5)
    assert st_ == "waiting" and "No newer bar since the last refresh" in text and "11:10 IST" in text
    st_, text = describe_data_state(open_ph, _ts("2026-10-21 10:30"), None, 5)
    assert st_ == "waiting" and "30 minutes behind the clock" in text
    st_, text = describe_data_state(market_phase(utc("2026-10-20 22:21")), _ts("2026-10-19 15:25"), None, 5)
    assert st_ == "waiting" and "NSE holiday (Dussehra)" in text and "complete session of Mon 19 Oct" in text
    assert "Wed 21 Oct at 09:15 IST" in text
    st_, text = describe_data_state(market_phase(utc("2026-10-21 09:17")), None, None, 5)
    assert st_ == "waiting" and "after 09:20 IST" in text


# --- Store and cache policy --------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def raw_bars():
    mkt = market_path()
    return {BENCH: synth_raw(1, index=True, market=mkt, beta=1.0),
            "AAA.NS": synth_raw(2, market=mkt, beta=1.1), "BBB.NS": synth_raw(3, market=mkt, beta=0.8)}


def _store(raw_bars, ist, **kw):
    clock = Clock(ist)
    fetcher = FakeFetcher(raw_bars, clock, **kw)
    return IntradayStore(fetcher, clock=clock), fetcher, clock


SYMS = [BENCH, "AAA.NS", "BBB.NS"]


def test_peek_never_requests_and_says_nothing_is_loaded(raw_bars):
    store, fetcher, _ = _store(raw_bars, "2026-10-21 11:07")
    view = store.get(SYMS, benchmark=BENCH, mode="peek")
    assert view.status == "unavailable" and "Press Refresh now" in view.explanation and not fetcher.calls


def test_first_refresh_loads_history_then_only_the_latest_window(raw_bars):
    store, fetcher, clock = _store(raw_bars, "2026-10-21 11:07")
    first = store.get(SYMS, benchmark=BENCH, mode="manual")
    assert first.requested and first.status == "fresh" and fetcher.calls == [(tuple(SYMS), "60d")]
    assert f"{first.latest_bar:%H:%M}" == "11:00"
    hist = first.history[BENCH]
    assert hist["partial"].sum() == 1 and f"{hist.index[-1]:%H:%M}" == "11:05"      # forming bar kept, flagged
    clock.set("2026-10-21 11:09")
    cached = store.get(SYMS, benchmark=BENCH, mode="auto")
    assert cached.status == "cached" and not cached.requested and len(fetcher.calls) == 1
    assert "Shown from memory" in cached.explanation
    clock.set("2026-10-21 11:13")
    later = store.get(SYMS, benchmark=BENCH, mode="auto")
    assert later.requested and fetcher.calls[-1] == (tuple(SYMS), "5d") and later.status == "fresh"
    assert f"{later.latest_bar:%H:%M}" == "11:05"
    assert len(later.history[BENCH]) > len(store._latest.frames[BENCH])            # history = baseline + latest


def test_manual_refresh_bypasses_the_cache_but_not_a_request_seconds_old(raw_bars):
    store, fetcher, clock = _store(raw_bars, "2026-10-21 11:07")
    store.get(SYMS, benchmark=BENCH, mode="manual")
    clock.set("2026-10-21 11:07:10")
    again = store.get(SYMS, benchmark=BENCH, mode="manual")
    assert len(fetcher.calls) == 1 and "finished 10 s ago" in again.explanation
    clock.set("2026-10-21 11:08")
    forced = store.get(SYMS, benchmark=BENCH, mode="manual")
    assert len(fetcher.calls) == 2 and forced.requested
    assert forced.status == "waiting" and "No newer bar since the last refresh" in forced.explanation


def test_failure_keeps_the_last_good_bars_with_their_age(raw_bars):
    store, fetcher, clock = _store(raw_bars, "2026-10-21 11:07")
    store.get(SYMS, benchmark=BENCH, mode="manual")
    fetcher.fail = set(SYMS)
    clock.set("2026-10-21 11:20")
    view = store.get(SYMS, benchmark=BENCH, mode="manual")
    assert view.status == "stale" and "failed (Simulated provider error (3 of 3 symbols))" in view.explanation
    assert "13 min old" in view.explanation and f"{view.latest_bar:%H:%M}" == "11:00"
    peek = store.get(SYMS, benchmark=BENCH, mode="peek")
    assert peek.status == "stale"


def test_first_failure_is_unavailable(raw_bars):
    store, fetcher, _ = _store(raw_bars, "2026-10-21 11:07", fail=set(SYMS))
    view = store.get(SYMS, benchmark=BENCH, mode="auto")
    assert view.status == "unavailable" and view.snapshot is None and "could not be retrieved" in view.explanation


def test_one_failing_symbol_keeps_its_earlier_bars_and_says_so(raw_bars):
    store, fetcher, clock = _store(raw_bars, "2026-10-21 11:07")
    store.get(SYMS, benchmark=BENCH, mode="manual")
    fetcher.fail = {"BBB.NS"}
    clock.set("2026-10-21 11:20")
    view = store.get(SYMS, benchmark=BENCH, mode="manual")
    assert "BBB.NS" in view.snapshot.carried and "1 symbol(s) failed this time" in view.explanation
    assert f"{pi.latest_complete_bar(view.snapshot.frames['BBB.NS']):%H:%M}" == "11:00"      # older, labelled
    assert f"{pi.latest_complete_bar(view.snapshot.frames['AAA.NS']):%H:%M}" == "11:15"


def test_auto_refresh_sends_no_requests_while_the_market_is_closed(raw_bars):
    store, fetcher, clock = _store(raw_bars, "2026-10-20 22:21")             # holiday evening
    first = store.get(SYMS, benchmark=BENCH, mode="auto")                     # nothing loaded: one request
    assert first.requested and first.status == "waiting" and "Dussehra" in first.explanation
    assert f"{first.latest_bar:%d %b %H:%M}" == "19 Oct 15:25"
    for minute in ("22:40", "23:10", "23:55"):
        clock.set(f"2026-10-20 {minute}")
        v = store.get(SYMS, benchmark=BENCH, mode="auto")
        assert not v.requested and "sends no requests while the market is closed" in v.explanation
    assert len(fetcher.calls) == 1
    store.get(SYMS, benchmark=BENCH, mode="manual")                           # a person can still ask
    assert len(fetcher.calls) == 2


def test_concurrent_sessions_cause_one_request(raw_bars):
    store, fetcher, _ = _store(raw_bars, "2026-10-21 11:07", delay=0.3)
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.get(SYMS, benchmark=BENCH, mode="auto")))
               for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fetcher.calls) == 1 and sum(v.requested for v in results) == 1
    assert sorted(v.status for v in results).count("cached") == 3


def test_history_is_requested_again_on_a_new_day(raw_bars):
    store, fetcher, clock = _store(raw_bars, "2026-10-21 15:50")
    store.get(SYMS, benchmark=BENCH, mode="manual")
    clock.set("2026-10-22 09:40")
    store.get(SYMS, benchmark=BENCH, mode="auto")
    assert [p for _, p in fetcher.calls] == ["60d", "60d"]


# --- Detection -----------------------------------------------------------------------------------------------

def _scan(raw, ist):
    clock = Clock(ist)
    store = IntradayStore(FakeFetcher(raw, clock), clock=clock)
    view = store.get(list(raw), benchmark=BENCH, mode="manual")
    return scan_intraday(view.history, BENCH, 5, {BENCH: "NIFTY 50"})


def _row(scan, sym):
    return scan.rows[scan.rows["symbol"] == sym].iloc[0]


def test_a_stock_specific_jump_is_flagged_against_the_same_time_of_day():
    mkt = market_path()
    day = pd.Timestamp("2026-10-21").date()
    raw = {BENCH: synth_raw(1, index=True, market=mkt), "AAA.NS": synth_raw(2, market=mkt, shocks={(day, 21): 0.02}),
           "BBB.NS": synth_raw(3, market=mkt)}
    scan = _scan(raw, "2026-10-21 11:07")                     # slot 21 is 11:00 to 11:05, the latest complete bar
    assert str(scan.session) == "2026-10-21"
    a, b = _row(scan, "AAA.NS"), _row(scan, "BBB.NS")
    assert f"{a['bar_time']:%H:%M}" == "11:00" and a["flagged"] and a["z_return"] > 8 and a["z_relative"] > 8
    assert "5-minute return +1." in a["reasons"] and a["n_sessions"] >= MIN_SESSIONS
    assert not b["flagged"] and abs(b["z_return"]) < 3.5
    assert scan.rows.iloc[0]["symbol"] == BENCH and scan.rows.iloc[1]["symbol"] == "AAA.NS"   # flagged rows first


def test_volume_is_judged_against_its_own_time_of_day():
    """A volume that is ordinary for the opening bar is unusual at 13:00."""
    day = pd.Timestamp("2026-10-21").date()
    opening_volume = u_shape(0) / u_shape(45)          # the opening bar's usual volume, as a multiple of 13:00's
    raw = {BENCH: synth_raw(1, index=True),
           "AAA.NS": synth_raw(2, vol_sd=0.15, vol_shocks={(day, 45): opening_volume})}
    a = _row(_scan(raw, "2026-10-21 13:07"), "AAA.NS")
    assert f"{a['bar_time']:%H:%M}" == "13:00" and a["z_volume"] > 3.5 and a["flagged"]
    assert 2.0 < a["volume_ratio"] < 3.2 and "times usual for this time" in a["reasons"]
    first = _row(_scan({BENCH: synth_raw(1, index=True), "AAA.NS": synth_raw(2, vol_sd=0.15)}, "2026-10-21 09:20"),
                 "AAA.NS")
    assert f"{first['bar_time']:%H:%M}" == "09:15" and abs(first["z_volume"]) < 3.5 and not first["flagged"]


def test_a_market_wide_move_is_not_a_relative_anomaly():
    day = pd.Timestamp("2026-10-21").date()
    mkt = market_path()
    shock_time = pd.Timestamp("2026-10-21 11:00", tz=MARKET_TZ)
    mkt = mkt.copy()
    mkt[shock_time] += 0.015
    raw = {BENCH: synth_raw(1, index=True, market=mkt, noise=0.0002),       # an index is mostly the market itself
           "AAA.NS": synth_raw(2, market=mkt, beta=1.0)}
    a = _row(_scan(raw, "2026-10-21 11:07"), "AAA.NS")
    assert abs(a["z_return"]) > 3.5 and abs(a["z_relative"]) < 3.5 and 0.6 < a["beta"] < 1.4
    assert "move relative to NIFTY 50" not in a["reasons"]
    assert day == shock_time.date()


def test_short_history_is_display_only():
    raw = {BENCH: synth_raw(1, index=True), "AAA.NS": synth_raw(2, shocks={(pd.Timestamp("2026-10-21").date(), 21): 0.05})}
    cut = SESSIONS[-12]
    short = {k: v[v.index >= pd.Timestamp(cut, tz=MARKET_TZ)] for k, v in raw.items()}
    a = _row(_scan(short, "2026-10-21 11:07"), "AAA.NS")
    assert not a["flagged"] and a["n_sessions"] < MIN_SESSIONS and a["note"].startswith("Display only")


def test_forming_bar_and_missing_bars_are_never_used_or_filled():
    day = pd.Timestamp("2026-10-21").date()
    raw = {BENCH: synth_raw(1, index=True), "AAA.NS": synth_raw(2, shocks={(day, 21): 0.08})}   # 11:00 bar, forming
    a = _row(_scan(raw, "2026-10-21 11:03"), "AAA.NS")
    assert a["partial_excluded"] and not a["flagged"] and f"{a['bar_time']:%H:%M}" == "10:55"
    gap = {k: v.drop(pd.Timestamp("2026-10-21 10:50", tz=MARKET_TZ)) if k == "AAA.NS" else v for k, v in raw.items()}
    clock = Clock("2026-10-21 11:07")
    hist = IntradayStore(FakeFetcher(gap, clock), clock=clock).get(list(gap), benchmark=BENCH, mode="manual").history
    meas = bar_measures(hist["AAA.NS"], 5)
    after_gap = meas.loc[pd.Timestamp("2026-10-21 10:55", tz=MARKET_TZ)]
    assert np.isnan(after_gap["ret"])                                     # no return across the missing bar
    assert pd.Timestamp("2026-10-21 10:50", tz=MARKET_TZ) not in hist["AAA.NS"].index   # and no invented bar
    behind = {k: v[v.index < pd.Timestamp("2026-10-21 10:45", tz=MARKET_TZ)] if k == "AAA.NS" else v
              for k, v in raw.items()}
    b = _row(_scan(behind, "2026-10-21 11:07"), "AAA.NS")
    assert b["bars_behind"] == 4 and "behind NIFTY 50" in b["note"]


def test_table_shows_missing_values_as_na_never_zero_or_none():
    from ui.intraday_panel import display_table
    raw = {BENCH: synth_raw(1, index=True), "AAA.NS": synth_raw(2), "BBB.NS": synth_raw(3)}
    raw["BBB.NS"] = raw["BBB.NS"].assign(Volume=np.nan)                    # a stock whose volume never arrived
    table = display_table(_scan(raw, "2026-10-21 11:07"))
    bench = table[table["Stock"] == "NIFTY 50"].iloc[0]
    assert bench["z vs NIFTY 50"] == "n/a" and bench["Volume vs usual"] == "n/a"   # an index has no volume on Yahoo
    no_vol = table[table["Stock"] == "BBB.NS"].iloc[0]
    assert no_vol["Volume vs usual"] == "n/a" and no_vol["z, volume"] == "n/a"
    cells = [str(v) for v in table.drop(columns=["Flag", "Note"]).to_numpy().ravel()]
    assert "None" not in cells and "nan" not in cells
    assert not any(c.rstrip("%") in ("-0.00", "-0.0") for c in cells)                 # no negative zero
    assert all(c == "n/a" or c[0] in "+-0123456789" for c in table["z, time of day"])


# --- No LLM, and the page ----------------------------------------------------------------------------------------

def test_intraday_code_never_imports_the_llm():
    for rel in ("providers/intraday.py", "analytics/intraday.py", "ui/intraday_panel.py"):
        tree = ast.parse((ROOT / rel).read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | \
               {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any(m and ("llm" in m or "orchestrator" in m or "agents" in m) for m in mods), rel


HARNESS = str(Path(__file__).parent / "intraday_harness.py")


@pytest.fixture
def fake_store(raw_bars, monkeypatch):
    clock = Clock("2026-10-21 11:07")
    from config.watchlist import get_universe
    uni = get_universe("live")
    raw = {BENCH: raw_bars[BENCH]}
    for i, t in enumerate(uni.tickers):
        raw[t] = synth_raw(10 + i)
    fetcher = FakeFetcher(raw, clock)
    store = IntradayStore(fetcher, clock=clock)
    monkeypatch.setattr(pi, "_STORE", store)
    from providers import llm

    def boom(*a, **k):
        raise AssertionError("the LLM must not be called by an intraday refresh")

    monkeypatch.setattr(llm, "make_backend", boom)
    monkeypatch.setattr(llm, "probe", boom)
    return store, fetcher, clock


def _texts(at):
    out = [str(getattr(e, "value", "")) for k in ("caption", "markdown") for e in at.get(k)]
    out += [str(getattr(h.proto, "body", "")) for h in at.get("html")]
    return " ".join(out)


def test_panel_controls_status_and_manual_refresh(fake_store, monkeypatch):
    store, fetcher, clock = fake_store
    monkeypatch.setenv("MS_TEST_DS_MODE", "live")
    at = AppTest.from_file(HARNESS, default_timeout=120)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    assert not fetcher.calls                                              # opening the page sends nothing
    text = _texts(at)
    assert "Status <b>Unavailable</b>" in text and "Press Refresh now" in text
    assert at.selectbox(key="intraday_every").value == 10 and at.selectbox(key="intraday_every").disabled
    assert "only while this page is open" in text and "not a real-time exchange feed" in text
    [b for b in at.button if b.label == "Refresh now"][0].click().run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(fetcher.calls) == 1
    text = _texts(at)
    assert "Status <b>Fresh</b>" in text and "Latest complete bar <b>Wed 21 Oct, 11:00 to 11:05 IST</b>" in text
    assert "This view <b>sent a request</b>" in text and "Last request <b>11:07:00 IST</b>" in text
    at.toggle(key="intraday_auto").set_value(True).run()
    assert not at.exception and not at.selectbox(key="intraday_every").disabled
    assert len(fetcher.calls) == 1                                        # within the cache life: no new request
    assert "Status <b>Cached</b>" in _texts(at)


def test_panel_in_demo_mode_does_not_simulate_intraday(fake_store, monkeypatch):
    store, fetcher, _ = fake_store
    monkeypatch.setenv("MS_TEST_DS_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=60)
    at.run()
    assert not at.exception
    assert "live data only" in _texts(at) and "no intraday bars are simulated" in _texts(at)
    assert not fetcher.calls


def test_intraday_check_script_reports_bars_and_failures(monkeypatch, raw_bars):
    import importlib.util
    import yfinance as yf
    spec = importlib.util.spec_from_file_location("intraday_check", ROOT / "scripts" / "intraday_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeTicker:
        def __init__(self, sym):
            self.sym = sym

        def history(self, period, interval, **kw):
            if interval == "1m":
                raise RuntimeError("1m data not available for this range")
            raw = raw_bars[BENCH]
            return raw[raw.index < pd.Timestamp("2026-10-20", tz=MARKET_TZ)]   # sessions up to Mon 19 Oct

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    good = module.check_one("^NSEI", "5m", "60d")
    assert good["ok"] and good["bars_per_session"] == 75 == good["expected_per_session"]
    assert good["last"] == "19 Oct 15:25" and good["missing_in_last_full"] == 0 and not good["forming_bar"]
    bad = module.check_one("^NSEI", "1m", "5d")
    assert not bad["ok"] and "1m data not available" in bad["error"]
