"""Renders the intraday panel alone for Streamlit AppTest. The test installs a store with a scripted fetcher."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui import intraday_panel  # noqa: E402
from ui.theme import inject_css  # noqa: E402


class _Dataset:
    mode = os.environ.get("MS_TEST_DS_MODE", "live")


inject_css()
intraday_panel.render(_Dataset())
