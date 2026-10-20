"""Sentinel grid: colour meaning, missing data, ordering, legend and page controls (UI fixes of 20 Oct 2026)."""
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from analytics.anomaly_detection import scan_universe
from ui.components import priority_bands, sentinel_grid

HARNESS = str(Path(__file__).parent / "page_harness.py")


@pytest.fixture(scope="module")
def scan(demo_monitor):
    return demo_monitor.scan


def test_priority_colour_is_the_alert_priority_and_quiet_days_are_neutral(scan):
    cal = scan.panel.calendar[-21:]
    fig, alerts = sentinel_grid(scan, cal, metric="priority", order="group")
    hm = fig.data[0]
    z = np.array(hm.z, dtype=float)
    rows, cols = list(hm.y), list(hm.x)
    assert len(alerts) > 0
    for _, a in alerts.iterrows():
        i = rows.index(a["ticker"].replace(".DEMO", ""))
        j = cols.index(a["date"].strftime("%d %b %y"))
        assert z[i, j] == pytest.approx(a["priority_score"])           # the cell is the alert's own score
    alert_cells = {(a["ticker"].replace(".DEMO", ""), a["date"].strftime("%d %b %y")) for _, a in alerts.iterrows()}
    quiet = [z[i, j] for i, r in enumerate(rows) for j, c in enumerate(cols) if (r, c) not in alert_cells]
    assert set(np.unique(quiet)) == {-1.0}                               # neutral, not a fake low priority
    assert hm.zmin == -1 and hm.zmax == 100
    assert "Alert priority band" in hm.colorbar.title.text


def test_legend_uses_the_configured_thresholds(scan):
    fig, _ = sentinel_grid(scan, scan.panel.calendar[-21:], metric="priority")
    cfg = scan.config
    text = " ".join(fig.data[0].colorbar.ticktext)
    assert f"Low (under {cfg.severity_moderate:.0f})" in text
    assert f"Moderate ({cfg.severity_moderate:.0f} to {cfg.severity_high:.0f})" in text
    assert f"Critical ({cfg.severity_critical:.0f}+)" in text
    assert [b[0] for b in priority_bands(cfg)] == ["Low", "Moderate", "High", "Critical"]


def test_missing_sessions_are_marked_not_coloured_as_zero(demo_ds, cfg):
    frames = {k: v.copy() for k, v in demo_ds.frames.items()}
    gap_day = frames["SAFFRON.DEMO"].index[-5]
    frames["SAFFRON.DEMO"] = frames["SAFFRON.DEMO"].drop(index=gap_day)
    scan = scan_universe(frames, demo_ds.universe, cfg)
    fig, _ = sentinel_grid(scan, scan.panel.calendar[-10:], metric="priority")
    hm = fig.data[0]
    i = list(hm.y).index("SAFFRON")
    j = list(hm.x).index(gap_day.strftime("%d %b %y"))
    assert np.isnan(np.array(hm.z, dtype=float)[i, j])
    crosses = [t for t in fig.data if getattr(t, "mode", None) == "text" and "×" in (t.text or [])]
    assert crosses and ("SAFFRON", gap_day.strftime("%d %b %y")) in set(zip(crosses[0].y, crosses[0].x))


def test_rows_are_ordered_by_highest_priority_in_the_window(scan):
    cal = scan.panel.calendar[-21:]
    fig, alerts = sentinel_grid(scan, cal, metric="priority", order="priority")
    top = alerts.sort_values("priority_score", ascending=False).iloc[0]["ticker"].replace(".DEMO", "")
    assert list(fig.data[0].y)[0] == top


def test_intensity_view_is_labelled_as_a_different_measure(scan):
    fig, _ = sentinel_grid(scan, scan.panel.calendar[-21:], metric="intensity")
    hm = fig.data[0]
    assert "Anomaly intensity" in hm.colorbar.title.text and hm.zmid == 0
    assert "priority" not in hm.colorbar.title.text.lower()


def test_alert_cells_carry_direction_score_and_ids_for_clicking(scan):
    cal = scan.panel.calendar[-21:]
    fig, alerts = sentinel_grid(scan, cal)
    marks = [t for t in fig.data if getattr(t, "name", None) == "alerts"][0]
    assert all(t.replace("<b>", "")[0] in "▲▼" for t in marks.text)      # direction without relying on colour
    assert {row[0] for row in marks.customdata} == set(alerts["event_id"])
    assert "Priority" in marks.hovertemplate and "Daily return" in fig.data[0].hovertemplate
    wide, _ = sentinel_grid(scan, scan.panel.calendar[-63:])
    assert all(len(t.replace("<b>", "").replace("</b>", "")) == 1 for t in [m for m in wide.data if getattr(m, "name", None) == "alerts"][0].text)


def test_overview_grid_controls_work(monkeypatch):
    monkeypatch.setenv("MS_TEST_PAGE", "overview")
    monkeypatch.setenv("MS_DEFAULT_MODE", "demo")
    at = AppTest.from_file(HARNESS, default_timeout=180)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    html = " ".join(str(getattr(h.proto, "body", "")) for h in at.get("html"))
    assert "prioritise analyst review" in html and "good or bad investment" in html
    at.radio(key="grid_metric").set_value("Anomaly intensity").run()
    at.radio(key="grid_order").set_value("Peer group").run()
    assert not at.exception, [e.value for e in at.exception]
    [b for b in at.button if b.label == "Reset view"][0].click().run()
    assert not at.exception
    assert at.session_state["grid_metric"] == "Alert priority" and at.session_state["grid_window"] == "1 month"
    pick = at.selectbox(key="grid_pick")
    assert pick.options and " · Priority " in pick.format_func(pick.options[0])
