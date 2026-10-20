"""Registry of page objects so pages can link to each other with st.switch_page."""
from __future__ import annotations

import streamlit as st

PAGES: dict = {}


def go_to(name: str) -> None:
    page = PAGES.get(name)
    if page is not None:
        st.switch_page(page)


def open_investigation(event_id: str, historical: bool = False) -> None:
    st.session_state.selected_event = event_id
    st.session_state.selected_event_historical = historical
    st.session_state.current_record = None
    go_to("investigate")
