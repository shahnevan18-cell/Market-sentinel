"""Look-ahead protection: nothing after a date may change what the system knew on that date."""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from analytics.anomaly_detection import scan_universe
from analytics.historical_replay import label_evaluation, run_replay
from config.market import session_close_utc
from providers.market_data import demo_planted_sessions
from providers.news_data import GoogleNewsRssProvider, NewsService

FEATURE_COLS = ["ret", "z_ret", "ret_median", "ret_mad", "z_volume", "volume_ratio", "beta", "alpha", "resid_sd",
                "abnormal_ret", "z_abn", "z_rel_peer", "z_sector", "vol_ratio", "priority_score"]


def test_features_identical_when_future_data_is_removed(demo_ds, demo_monitor, cfg):
    full = demo_monitor.scan
    cal = full.panel.calendar
    rng = np.random.default_rng(11)
    dates = [cal[i] for i in rng.choice(np.arange(150, len(cal) - 5), size=6, replace=False)]
    for d in dates:
        trunc = demo_ds.truncated(d)
        assert max(f.index.max() for f in trunc.frames.values()) <= d
        part = scan_universe(trunc.frames, demo_ds.universe, cfg)
        for ticker in ["BODHI.DEMO", "SAFFRON.DEMO", "COASTPET.DEMO", "CURELINE.DEMO", "IRONBRG.DEMO"]:
            a = full.features[ticker].loc[d, FEATURE_COLS].astype(float)
            b = part.features[ticker].loc[d, FEATURE_COLS].astype(float)
            np.testing.assert_allclose(a.values, b.values, rtol=1e-9, atol=1e-12, equal_nan=True,
                                       err_msg=f"look-ahead detected for {ticker} on {d:%Y-%m-%d}")


def test_changing_future_prices_does_not_change_past_alerts(demo_ds, demo_monitor, cfg):
    cal = demo_monitor.scan.panel.calendar
    cutoff = cal[-60]
    frames = {}
    for s, f in demo_ds.frames.items():
        g = f.copy()
        later = g.index > cutoff
        g.loc[later, ["close", "adj_close"]] = g.loc[later, ["close", "adj_close"]] * 1.5
        g.loc[later, "volume"] = g.loc[later, "volume"] * 10
        frames[s] = g
    altered = scan_universe(frames, demo_ds.universe, cfg)
    before_a = altered.events[altered.events["date"] <= cutoff]["event_id"].tolist()
    before_o = demo_monitor.scan.events[demo_monitor.scan.events["date"] <= cutoff]["event_id"].tolist()
    assert sorted(before_a) == sorted(before_o)


def test_replay_attaches_future_outcomes_separately(demo_monitor):
    scan = demo_monitor.scan
    cal = scan.panel.calendar
    rr = run_replay(scan, cal[-200], cal[-1])
    assert rr.summary["n_events"] > 0
    ev = rr.events.iloc[-1]
    df = scan.features[ev["ticker"]]
    pos = df.index.get_loc(ev["date"])
    if pos + 1 < len(df):
        assert ev["after_ret_1d"] == pytest.approx(df["close"].iloc[pos + 1] / df["close"].iloc[pos] - 1)
    latest = rr.events[rr.events["date"] == cal[-1]]
    if len(latest):
        assert latest["after_ret_1d"].isna().all()       # no future data exists yet
    assert all(c.startswith("after_") for c in rr.events.columns if "after" in c)


def test_label_evaluation_definitions():
    events = pd.DataFrame({"ticker": ["AAA", "AAA", "BBB"],
                           "date": pd.to_datetime(["2025-03-04", "2025-04-01", "2025-03-05"])})
    days = {"AAA": [pd.Timestamp("2025-03-04"), pd.Timestamp("2025-06-03")], "BBB": [pd.Timestamp("2025-03-06")]}
    res = label_evaluation(events, days, "2025-01-01", "2025-12-31", "test labels")
    assert res["matches"] == 1
    assert res["precision_vs_proxy"] == pytest.approx(1 / 3)
    assert res["recall_vs_proxy"] == pytest.approx(1 / 3)
    assert res["missed_labels"] == ["AAA:2025-06-03", "BBB:2025-03-06"]


def test_detector_recovers_every_planted_stock_specific_shock(demo_monitor):
    """Synthetic data has known labels: every stock-specific shock planted in the demo raises an alert."""
    cal = demo_monitor.scan.panel.calendar
    res = label_evaluation(demo_monitor.events, demo_planted_sessions(stock_specific_only=True), cal[0], cal[-1],
                           "planted stock-specific shocks")
    assert res["labelled_sessions"] == 6 and res["recall_vs_proxy"] == 1.0


def test_news_after_cutoff_is_excluded(settings, fake_session_cls, fake_response_cls, tmp_path):
    from config.watchlist import Security, Universe
    from pathlib import Path
    xml = (Path(__file__).parent / "fixtures" / "google_news_rss.xml").read_text(encoding="utf-8")
    session = fake_session_cls({"news.google.com": fake_response_cls(200, text=xml)})
    uni = Universe(key="t", label="t", securities=(Security("TESTCO.NS", "Testco Industries Ltd. (fictional)", "Tech",
                                                            "Testco Industries"),),
                   benchmark="^NSEI", benchmark_name="NIFTY 50", sector_indices={}, sector_index_names={})
    svc = NewsService(settings, uni, "live", session=session, cache_root=tmp_path)
    event_date = pd.Timestamp("2026-09-30")
    cutoff = session_close_utc(event_date)                    # 15:30 IST = 10:00 UTC
    assert cutoff.isoformat() == "2026-09-30T10:00:00+00:00"
    res = svc.search("TESTCO.NS", event_date, prev_session=pd.Timestamp("2026-09-29"), days_after=1, cutoff=cutoff,
                     include_yahoo=False)
    published = [datetime.fromisoformat(i.published_at) for i in res.items if i.published_at]
    assert published and all(p <= cutoff for p in published)
    assert not any("Sensex, Nifty end lower" in i.headline for i in res.items)   # published after the 15:30 close


def test_google_rss_url_has_date_bounds():
    url = GoogleNewsRssProvider.build_url("Testco stock", "2026-09-24", "2026-10-02")
    assert "after%3A2026-09-24" in url and "before%3A2026-10-02" in url and "ceid=IN:en" in url


def test_orchestrator_historical_mode_uses_truncated_data(demo_ds, demo_monitor, settings):
    from agents.orchestrator import run_investigation
    ev = demo_monitor.events[demo_monitor.events["date"] < demo_monitor.scan.panel.calendar[-30]].iloc[0]
    rec = run_investigation(ev["event_id"], demo_ds, settings, scan=demo_monitor.scan, historical=True, save=False)
    assert rec.historical is True
    assert rec.validation["lookahead_check_passed"] is True
    assert rec.data["prices_used_up_to"] == f"{pd.Timestamp(ev['date']):%Y-%m-%d}"
    assert rec.data["news_cutoff_utc"] is not None
    for entry in rec.audit:
        out = entry.get("output") or {}
        if entry.get("name") == "get_price_history":
            assert max(r["date"] for r in out["rows"]) <= f"{pd.Timestamp(ev['date']):%Y-%m-%d}"
