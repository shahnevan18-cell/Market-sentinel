"""Market Sentinel (India): agentic market-anomaly investigation and risk intelligence for NSE-listed shares.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Market Sentinel", page_icon=str(ROOT / "ui" / "assets" / "icon.svg"),
                   layout="wide", initial_sidebar_state="expanded")

from ui import nav  # noqa: E402
from ui.pages import investigate, methodology, monitor, overview, replay, risk_lab  # noqa: E402
from ui.state import init_state, sidebar_controls  # noqa: E402
from ui.theme import inject_css, register_plotly_template  # noqa: E402

inject_css()
register_plotly_template()
init_state()

pages = {
    "overview": st.Page(overview.render, title="Market overview", icon=":material/monitoring:",
                        url_path="overview", default=True),
    "monitor": st.Page(monitor.render, title="Anomaly monitor", icon=":material/radar:", url_path="anomalies"),
    "investigate": st.Page(investigate.render, title="Investigation workspace", icon=":material/manage_search:",
                           url_path="investigate"),
    "replay": st.Page(replay.render, title="Historical replay", icon=":material/history:", url_path="replay"),
    "risk_lab": st.Page(risk_lab.render, title="Risk scenario lab", icon=":material/tune:", url_path="risk-lab"),
    "methodology": st.Page(methodology.render, title="Methodology and data", icon=":material/menu_book:",
                           url_path="methodology"),
}
nav.PAGES.clear()
nav.PAGES.update(pages)

navigation = st.navigation({
    "Monitor": [pages["overview"], pages["monitor"]],
    "Investigate": [pages["investigate"], pages["replay"]],
    "Analyse": [pages["risk_lab"], pages["methodology"]],
})
sidebar_controls()
navigation.run()
