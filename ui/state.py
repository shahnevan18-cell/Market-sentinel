"""Session state, data loading and the sidebar controls shared by every page."""
from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone

import streamlit as st

from agents.sentinel_monitor import MonitorOutput, SentinelMonitor
from config.settings import AUTHORS, AnalysisConfig, Settings, load_settings
from config.watchlist import get_universe
from providers.llm import LLMBackend, make_backend
from providers.market_data import MarketDataset, YFinanceProvider, load_demo_dataset, load_live_dataset, make_provider

MODE_LABELS = {"live": "Live NSE market data", "demo": "Demonstration data (synthetic)"}
_DATASETS: dict[str, MarketDataset] = {}   # in-memory cache shared by sessions of this server process
_FAILED: dict[str, tuple[float, MarketDataset]] = {}   # a failed live load is reused briefly instead of refetched
FAILED_RETRY_SECONDS = 120
THRESHOLD_KEYS = ("lookback", "z_price", "z_abnormal", "z_volume")


def _secrets_to_env() -> None:
    """On hosted deployments, copy top-level Streamlit secrets into environment variables."""
    try:
        for key, value in st.secrets.items():
            if isinstance(value, (str, int, float)) and key not in os.environ:
                os.environ[key] = str(value)
    except Exception:
        pass


def init_state() -> None:
    _secrets_to_env()
    ss = st.session_state
    if "mode" not in ss:
        ss.mode = "demo" if load_settings().data.default_mode == "demo" else "live"
    ss.setdefault("thresholds", {})
    ss.setdefault("selected_event", None)
    ss.setdefault("selected_event_historical", False)
    ss.setdefault("use_llm", True)
    ss.setdefault("current_record", None)


def analysis_config() -> AnalysisConfig:
    overrides = {k: v for k, v in st.session_state.get("thresholds", {}).items() if k in THRESHOLD_KEYS}
    cfg = AnalysisConfig(**overrides)
    if cfg.min_obs > cfg.lookback:
        cfg = replace(cfg, min_obs=max(20, int(cfg.lookback * 0.67)))
    return cfg


def get_settings() -> Settings:
    return load_settings(analysis_config())


def get_backend() -> LLMBackend | None:
    s = get_settings()
    if not st.session_state.get("use_llm", True):
        return None
    return make_backend(s.llm)


def _load_live(force: bool) -> MarketDataset:
    settings = get_settings()
    universe = get_universe("live")
    provider = make_provider(settings)
    symbols = universe.all_symbols
    with st.status("Loading market data", expanded=False) as box:
        bar = st.progress(0.0, text="Checking the local cache")
        if isinstance(provider, YFinanceProvider):
            def on_progress(done, total, symbol, error):
                text = f"{symbol}: {'failed' if error else 'received'} ({done} of {total} requested)"
                bar.progress(min(done / max(total, 1), 1.0), text=text)
            provider.progress_callback = on_progress
        ds = load_live_dataset(universe, settings, force_refresh=force, provider=provider)
        n_ok = len(ds.frames)
        bar.progress(1.0, text=f"Received {n_ok} of {len(symbols)} symbols")
        if n_ok == 0:
            box.update(label="Market data could not be loaded", state="error", expanded=True)
        elif ds.failures or ds.freshness()["stale_symbols"]:
            box.update(label=f"Loaded {n_ok} of {len(symbols)} symbols, with warnings", state="complete")
        else:
            box.update(label=f"Loaded {n_ok} of {len(symbols)} symbols", state="complete")
    return ds


def get_dataset(force: bool = False) -> MarketDataset:
    mode = st.session_state.mode
    if not force and mode in _DATASETS:
        return _DATASETS[mode]
    failed = _FAILED.get(mode)
    if not force and failed and time.monotonic() - failed[0] < FAILED_RETRY_SECONDS:
        # Every click reruns the page; retrying an unreachable provider each time would be slow and could
        # trigger throttling. The failure is shown again; Refresh market data retries at once.
        return failed[1]
    ds = load_demo_dataset(get_universe("demo")) if mode == "demo" else _load_live(force)
    if ds.frames:
        _DATASETS[mode] = ds
        _FAILED.pop(mode, None)
    else:
        _FAILED[mode] = (time.monotonic(), ds)
    return ds


@st.cache_resource(max_entries=8, show_spinner=False)
def _run_monitor(key: str, cfg_items: tuple, _dataset: MarketDataset) -> MonitorOutput:
    return SentinelMonitor(AnalysisConfig(**dict(cfg_items))).run(_dataset)


def get_monitor(ds: MarketDataset) -> MonitorOutput:
    cfg = analysis_config()
    key = f"{ds.mode}|{ds.loaded_at}|{len(ds.frames)}"
    return _run_monitor(key, tuple(sorted(cfg.as_dict().items())), ds)


def app_data() -> tuple[MarketDataset, MonitorOutput | None]:
    ds = get_dataset()
    if not ds.frames:
        return ds, None
    return ds, get_monitor(ds)


ASSETS = Path(__file__).resolve().parent / "assets"


def _brand() -> None:
    st.logo(str(ASSETS / "logo.svg"), size="large", icon_image=str(ASSETS / "icon.svg"))


def sidebar_controls() -> None:
    ss = st.session_state
    _brand()
    with st.sidebar:
        st.markdown("**Data source**")
        choice = st.radio("Data source", options=["live", "demo"], format_func=lambda m: MODE_LABELS[m],
                          index=0 if ss.mode == "live" else 1, label_visibility="collapsed", key="mode_radio")
        if choice != ss.mode:
            ss.mode = choice
            ss.selected_event = None
            ss.current_record = None
            st.rerun()
        if ss.mode == "live":
            st.caption("Daily NSE prices (25 NIFTY 50 stocks, NIFTY 50, sector indices, SENSEX) from Yahoo Finance "
                       "via yfinance: unofficial and possibly delayed. Prices in ₹, sessions in IST. Cached on disk.")
            if st.button("Refresh market data", width="stretch", help="Ignore the cache and fetch again."):
                _DATASETS.pop("live", None)
                get_dataset(force=True)
                st.rerun()
        else:
            st.caption("Fictional India-themed securities generated with a fixed seed (SYNTHETIC DEMONSTRATION DATA). "
                       "Use this when the network is unavailable.")

        with st.expander("Alert thresholds"):
            defaults = AnalysisConfig()
            lb = st.slider("Baseline window (trading days)", 40, 120, defaults.lookback, 5, key="thr_lookback")
            zp = st.slider("Price test: |robust z| at least", 2.0, 5.0, float(defaults.z_price), 0.25, key="thr_z_price")
            za = st.slider("Market-relative test: |z| at least", 2.0, 5.0, float(defaults.z_abnormal), 0.25,
                           key="thr_z_abnormal")
            zv = st.slider("Volume test: z at least", 2.0, 5.0, float(defaults.z_volume), 0.25, key="thr_z_volume")
            new = {"lookback": lb, "z_price": zp, "z_abnormal": za, "z_volume": zv}
            ss.thresholds = {k: v for k, v in new.items() if v != getattr(defaults, k)}
            if ss.thresholds:
                st.caption("Custom thresholds are active. Scores and alerts are recalculated.")
                if st.button("Reset to defaults", width="stretch"):
                    for k in ("thr_lookback", "thr_z_price", "thr_z_abnormal", "thr_z_volume"):
                        ss.pop(k, None)
                    ss.thresholds = {}
                    st.rerun()

        st.markdown("**Reasoning engine**")
        s = get_settings()
        if s.llm.enabled:
            ss.use_llm = st.toggle("Use the LLM for investigations", value=ss.get("use_llm", True))
            st.caption(f"Configured: {s.llm.describe()}. Numbers always come from Python tools.")
        else:
            ss.use_llm = False
            st.caption("No LLM key found, so investigations use the rule-based engine. Add ANTHROPIC_API_KEY "
                       "(or LLM_API_KEY) to .env, or to the app's secrets when hosted, to enable it.")

        if st.button("Reset session", width="stretch",
                     help="Clear the selected event and the open investigation. Cached data is kept."):
            for k in ("selected_event", "current_record", "selected_event_historical", "replay_result"):
                ss.pop(k, None)
            st.rerun()
        st.divider()
        st.caption("Business Analytics project, Theme 4: Agentic AI. "
                   + " and ".join(f"{n} ({r})" for n, r, _ in AUTHORS) + ".")
        st.caption("Educational analysis only. Not investment advice.")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
