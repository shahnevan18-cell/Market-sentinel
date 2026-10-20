"""Renders a single page for Streamlit AppTest (the page is chosen with MS_TEST_PAGE)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui.pages import investigate, methodology, monitor, overview, replay, risk_lab  # noqa: E402
from ui.state import init_state, sidebar_controls  # noqa: E402
from ui.theme import inject_css, register_plotly_template  # noqa: E402

inject_css()
register_plotly_template()
init_state()
sidebar_controls()
PAGES = {"overview": overview.render, "monitor": monitor.render, "investigate": investigate.render,
         "replay": replay.render, "risk_lab": risk_lab.render, "methodology": methodology.render}
PAGES[os.environ.get("MS_TEST_PAGE", "overview")]()
