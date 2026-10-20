"""Shared fixtures. All fixtures are deterministic and synthetic; none is presented as a market observation."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import os  # noqa: E402
import tempfile  # noqa: E402

# Tests never touch the real cache or investigation history.
_TMP = Path(tempfile.mkdtemp(prefix="ms_tests_"))
os.environ["MS_CACHE_DIR"] = str(_TMP / "cache")
os.environ["MS_HISTORY_DIR"] = str(_TMP / "investigations")
os.environ.setdefault("MS_DEFAULT_MODE", "demo")
os.environ["MS_DISABLE_DOTENV"] = "1"          # never read a developer's real API keys during tests
for _k in ("ANTHROPIC_API_KEY", "LLM_API_KEY", "LLM_PROVIDER"):
    os.environ.pop(_k, None)

from config.settings import AnalysisConfig, DataConfig, LLMConfig, Settings  # noqa: E402
from providers.market_data import STANDARD_COLUMNS, load_demo_dataset  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def cfg() -> AnalysisConfig:
    return AnalysisConfig()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(analysis=AnalysisConfig(), data=DataConfig(news_enabled=True), llm=LLMConfig(provider="none"))


@pytest.fixture(scope="session")
def demo_ds():
    return load_demo_dataset()


@pytest.fixture(scope="session")
def demo_monitor(demo_ds, cfg):
    from agents.sentinel_monitor import SentinelMonitor
    return SentinelMonitor(cfg).run(demo_ds)


def make_frame(prices, volumes=None, start="2025-01-02") -> pd.DataFrame:
    prices = np.asarray(prices, dtype=float)
    idx = pd.bdate_range(start=start, periods=len(prices))
    vol = np.full(len(prices), 1_000_000.0) if volumes is None else np.asarray(volumes, dtype=float)
    df = pd.DataFrame({"open": prices, "high": prices * 1.01, "low": prices * 0.99, "close": prices,
                       "adj_close": prices, "volume": vol, "dividends": 0.0, "splits": 0.0}, index=idx)
    df.index.name = "date"
    return df[STANDARD_COLUMNS]


@pytest.fixture
def frame_factory():
    return make_frame


class FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Stands in for `requests`: maps URL substrings to responses, or raises for unknown URLs."""

    def __init__(self, routes: dict | None = None, error: Exception | None = None):
        self.routes = routes or {}
        self.error = error
        self.calls = []

    def get(self, url, headers=None, timeout=None, params=None):
        self.calls.append(url)
        if self.error:
            raise self.error
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise ConnectionError(f"No route for {url}")


@pytest.fixture
def fake_session_cls():
    return FakeSession


@pytest.fixture
def fake_response_cls():
    return FakeResponse
