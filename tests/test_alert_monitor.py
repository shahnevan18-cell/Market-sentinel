"""Anomaly monitor filters, the alert-table contract and the alert selector (UI fixes of 20 Oct 2026).

The deployed app crashed with KeyError 'priority_score' after the Severity filter was cleared: indexing a frame with
the empty object-dtype mask of an empty frame selected zero columns. These tests pin the repaired behaviour.
"""
import os
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from analytics.alert_view import (ALERT_TYPES, SEVERITIES, AlertFilters, AlertSchemaError, alert_label, check_schema,
                                  filter_alerts, monitor_state, plain_reason)
from analytics.anomaly_detection import EVENT_COLUMNS, empty_events

HARNESS = str(Path(__file__).parent / "page_harness.py")


@pytest.fixture(scope="module")
def events(demo_monitor):
    return demo_monitor.events


def test_normal_populated_alerts_filter_as_selected(events):
    r = filter_alerts(events, AlertFilters(severities=["Critical"], types=list(ALERT_TYPES)))
    assert len(r.view) > 0 and set(r.view["severity"]) == {"Critical"} and r.notes == []
    assert r.total == len(events)
    assert list(r.view["date"]) == sorted(r.view["date"], reverse=True)          # newest first, as before


def test_all_filters_cleared_shows_every_alert(events):
    r = filter_alerts(events, AlertFilters())
    assert len(r.view) == len(events)
    assert len(r.notes) == 2                                                     # both clearings are explained


def test_no_severity_selected_means_all_severities(events):
    """The exact path that crashed: Severity cleared, then the alert-type mask on an empty frame."""
    r = filter_alerts(events, AlertFilters(severities=[], types=["Large price move"]))
    assert len(r.view) > 0 and "priority_score" in r.view.columns
    assert set(r.view["severity"]) == set(events[events["event_types"].map(lambda t: "Large price move" in t)]["severity"])
    assert any("severity" in n for n in r.notes)


def test_no_alert_type_selected_means_all_types(events):
    r = filter_alerts(events, AlertFilters(severities=["High"], types=[]))
    assert len(r.view) == int((events["severity"] == "High").sum())
    assert any("alert type" in n for n in r.notes)


def test_no_rows_match_keeps_every_column(events):
    r = filter_alerts(events, AlertFilters(severities=list(SEVERITIES), types=list(ALERT_TYPES), min_score=100.5))
    assert r.empty and r.total == len(events)
    check_schema(r.view)                                                         # every column survives
    r2 = filter_alerts(events, AlertFilters(tickers=["NOT_A_SYMBOL"], severities=["Low"], types=["Volume spike"]))
    assert r2.empty and list(r2.view.columns) == list(events.columns)


def test_zero_source_alerts_filter_without_errors():
    empty = empty_events()
    for f in (AlertFilters(), AlertFilters(severities=[], types=["Volume spike"], min_score=50)):
        r = filter_alerts(empty, f)
        assert r.empty and r.total == 0
        check_schema(r.view)


def test_expected_columns_present_with_zero_rows(cfg):
    from agents.sentinel_monitor import SentinelMonitor
    from config.watchlist import DEMO_UNIVERSE
    from providers.market_data import MarketDataset
    assert list(empty_events().columns) == EVENT_COLUMNS
    ds = MarketDataset(frames={}, meta={}, universe=DEMO_UNIVERSE, mode="live", provider_label="test",
                       loaded_at="2026-10-20T10:00:00+00:00", failures={"MKT.DEMO": "no data"})
    mon = SentinelMonitor(cfg).run(ds)
    assert mon.events.empty
    check_schema(mon.events)
    assert {"episode_id", "episode_day", "escalate"} <= set(mon.events.columns)
    state, why = monitor_state(mon)
    assert state == "no_data" and "not a sign that nothing unusual happened" in why   # missing data is not "calm"


def test_broken_alert_frame_is_reported_not_hidden(events):
    with pytest.raises(AlertSchemaError, match="priority_score"):
        filter_alerts(events.drop(columns=["priority_score"]), AlertFilters())


def test_monitor_state_tells_no_alerts_apart_from_no_data(demo_monitor):
    assert monitor_state(demo_monitor) == ("ok", "")
    assert monitor_state(None)[0] == "no_data"


def test_alert_label_is_concise_and_comes_from_the_record(events):
    row = events.iloc[0]
    label = alert_label(row)
    parts = label.split(" · ")
    assert parts[0] == row["ticker"].replace(".DEMO", "") and parts[1] == f"{row['date']:%d %b %Y}"
    assert parts[3] == f"Priority {row['priority_score']:.0f}" and len(label) <= 70
    assert ".DEMO" not in label and row["name"] not in label


def test_plain_reason_describes_the_actual_triggers(events):
    saffron = events[events["event_id"] == "SAFFRON.DEMO:2026-09-30"].iloc[0].to_dict()
    text = plain_reason(saffron, "Synthetic broad-market index")
    assert "fell 9.2%" in text and "times its typical level" in text
    assert "Unusual is not the same as explained" in text
    vol_only = dict(saffron, event_types=["Volume spike"])
    assert "fell" not in plain_reason(vol_only, "X") and "volume" in plain_reason(vol_only, "X")


def _monitor_app(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "monitor")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_monitor_page_survives_cleared_filters_and_resets(monkeypatch):
    at = _monitor_app(monkeypatch)
    at.multiselect(key="mon_sev").set_value([]).run()
    at.multiselect(key="mon_types").set_value(["Volume spike"]).run()
    assert not at.exception, [e.value for e in at.exception]            # the reported KeyError path
    at.multiselect(key="mon_types").set_value([]).run()
    assert not at.exception, [e.value for e in at.exception]
    captions = " ".join(str(c.value) for c in at.caption)
    assert "all severities are shown" in captions and "all alert types are shown" in captions
    at.number_input(key="mon_min").set_value(100).run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert "No alerts match these filters" in html
    [b for b in at.button if b.label == "Reset filters"][0].click().run()
    assert not at.exception
    assert at.session_state["mon_sev"] == SEVERITIES and at.session_state["mon_min"] == 0


def test_selected_alert_panel_shows_the_full_details(monkeypatch):
    at = _monitor_app(monkeypatch)
    pick = at.selectbox(key="mon_pick")
    assert all(" · Priority " in pick.format_func(o) for o in pick.options)
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert 'aria-label="Selected alert"' in html and "Flagged because" in html
    assert any(b.label == "Investigate this alert" for b in at.button)
