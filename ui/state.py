"""Session state, data loading and the sidebar controls shared by every page."""
from __future__ import annotations

import hmac
import os
import re
import time
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import streamlit as st

from agents.sentinel_monitor import MonitorOutput, SentinelMonitor
from config.settings import AUTHORS, AnalysisConfig, LLMConfig, Settings, load_settings
from config.watchlist import get_universe
from providers.llm import LLMBackend, make_backend, probe, redact
from providers.market_data import MarketDataset, YFinanceProvider, load_demo_dataset, load_live_dataset, make_provider

MODE_LABELS = {"live": "Live NSE market data", "demo": "Demonstration data (synthetic)"}
_DATASETS: dict[str, MarketDataset] = {}   # in-memory cache shared by sessions of this server process
_FAILED: dict[str, tuple[float, MarketDataset]] = {}   # a failed live load is reused briefly instead of refetched
FAILED_RETRY_SECONDS = 120
THRESHOLD_KEYS = ("lookback", "z_price", "z_abnormal", "z_volume")


APP_SETTING = re.compile(r"^(LLM|MS|GEMINI|GOOGLE|ANTHROPIC)_[A-Z0-9_]+$")
_SECRET_COPIES: dict[str, str] = {}   # variables this process set from Streamlit secrets, so an edited secret updates
SECRETS_REPORT: dict = {"read": False, "names": [], "other_count": 0, "notes": [], "error": None}


def _secrets_to_env(secrets: Mapping | None = None) -> dict:
    """Copy Streamlit secrets into environment variables, so a hosted app is configured the same way as .env.

    Top-level values are copied. App settings written in lower case or placed inside a table (for example
    [gemini]) are lifted to their upper-case name. A variable this function set earlier is updated when the secret
    changes; a variable set outside the secrets is left alone. The report lists names, never values.
    """
    report = {"read": False, "names": [], "other_count": 0, "notes": [], "error": None}
    try:
        items = list((st.secrets if secrets is None else secrets).items())
        report["read"] = True
    except FileNotFoundError:
        items = []   # no secrets file: normal when running locally with .env
    except Exception as exc:  # noqa: BLE001 - a broken secrets file must not stop the app
        items = []
        report["error"] = (f"The app's secrets could not be read ({type(exc).__name__}). Check the format in the "
                           'secrets box: each value needs quotes, for example GEMINI_API_KEY = "your-key".')
    found: list[tuple[str, object, str]] = []
    for key, value in items:
        if isinstance(value, Mapping):
            for sub, inner in value.items():
                if isinstance(inner, (str, int, float)) and APP_SETTING.match(str(sub).upper()):
                    found.append((str(sub).upper(), inner, f"{sub} inside [{key}]"))
            continue
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            continue
        name = str(key).upper() if APP_SETTING.match(str(key).upper()) else str(key)
        found.append((name, value, str(key)))
    for name, value, origin in found:
        if not APP_SETTING.match(name):
            report["other_count"] += 1
            continue
        text = str(value).strip()
        report["names"].append(name)
        if origin != name:
            report["notes"].append(f"{origin} was read as {name}.")
        current = os.environ.get(name)
        if current is None or current == _SECRET_COPIES.get(name) or (origin == name and current == str(value)):
            if current != text:
                os.environ[name] = text
            _SECRET_COPIES[name] = text
        elif current != text:
            report["notes"].append(f"{name} is also set outside the secrets; that value is used.")
    SECRETS_REPORT.clear()
    SECRETS_REPORT.update(report)
    return report


def init_state() -> None:
    _secrets_to_env()
    ss = st.session_state
    if "mode" not in ss:
        ss.mode = "demo" if load_settings().data.default_mode == "demo" else "live"
    ss.setdefault("thresholds", {})
    ss.setdefault("selected_event", None)
    ss.setdefault("selected_event_historical", False)
    ss.setdefault("engine_choice", "llm")
    ss.setdefault("current_record", None)


def analysis_config() -> AnalysisConfig:
    overrides = {k: v for k, v in st.session_state.get("thresholds", {}).items() if k in THRESHOLD_KEYS}
    cfg = AnalysisConfig(**overrides)
    if cfg.min_obs > cfg.lookback:
        cfg = replace(cfg, min_obs=max(20, int(cfg.lookback * 0.67)))
    return cfg


def get_settings() -> Settings:
    return load_settings(analysis_config())


def _passcode() -> str:
    return (os.environ.get("MS_LLM_PASSCODE") or "").strip()


def llm_locked() -> bool:
    """True when this deployment asks for a passcode before it calls the model and this session has not given it."""
    return bool(_passcode()) and not st.session_state.get("llm_unlocked", False)


def check_passcode(entered: str) -> bool:
    code = _passcode()
    return bool(code) and hmac.compare_digest((entered or "").strip().encode(), code.encode())


def engine_plan() -> tuple[LLMBackend | None, str | None]:
    """The backend for the next investigation and, when it is None, why the rule-based protocol runs instead."""
    cfg = get_settings().llm
    if not cfg.enabled:
        return None, "switched_off" if cfg.switched_off else "config_problem" if cfg.problem else "no_credentials"
    if st.session_state.get("engine_choice", "llm") == "rules":
        return None, "selected"
    if llm_locked():
        return None, "locked"
    return make_backend(cfg), None


def get_backend() -> LLMBackend | None:
    return engine_plan()[0]


def engine_name(cfg: LLMConfig) -> str:
    return "Gemini" if cfg.is_gemini else "Claude" if cfg.provider == "anthropic" else "LLM"


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

        _engine_controls()

        if st.button("Reset session", width="stretch",
                     help="Clear the selected event and the open investigation. Cached data is kept."):
            for k in ("selected_event", "current_record", "selected_event_historical", "replay_result"):
                ss.pop(k, None)
            st.rerun()
        st.divider()
        st.caption("Business Analytics project, Theme 4: Agentic AI. "
                   + " and ".join(f"{n} ({r})" for n, r, _ in AUTHORS) + ".")
        st.caption("Educational analysis only. Not investment advice.")


def _engine_controls() -> None:
    """Sidebar: which engine the next investigation uses, the passcode lock and a one-request connection test."""
    ss = st.session_state
    cfg = get_settings().llm
    st.markdown("**Reasoning engine**")
    if not cfg.enabled:
        st.caption(cfg.status_text())
    else:
        name = engine_name(cfg)
        labels = {"llm": f"{name} (model-directed)", "rules": "Rule-based protocol"}
        st.radio("Reasoning engine", ["llm", "rules"], format_func=labels.get, key="engine_choice",
                 label_visibility="collapsed",
                 help="Model-directed: the model chooses which tools to run and writes the findings, and every "
                      "number still comes from Python tools. Rule-based: the same tools run in a fixed order.")
        st.caption(cfg.status_text() + " Numbers always come from Python tools.")
        if ss.get("engine_choice") == "llm" and llm_locked():
            st.caption(f"This deployment asks for a passcode before it calls {name}, so a shared link cannot use "
                       "up the daily quota. Until it is entered, investigations use the rule-based protocol.")
            with st.form("llm_unlock", border=False):
                entered = st.text_input("Passcode", type="password", key="llm_passcode_input")
                if st.form_submit_button("Unlock", width="stretch"):
                    if check_passcode(entered):
                        ss.llm_unlocked = True
                        st.rerun()
                    time.sleep(1.0)   # slows guessing
                    st.error("That passcode is not right.")
        if st.button("Test connection", width="stretch", disabled=llm_locked(),
                     help=f"Sends one small request to {name} and reports what happened. It uses one request of "
                          "the daily quota and does not run an investigation."):
            with st.spinner(f"Calling {cfg.model}"):
                result = probe(cfg)
            result["checked_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%H:%M:%S IST")
            result["config"] = (cfg.model, cfg.key_source, cfg.base_url)
            ss.llm_health = result
        health = ss.get("llm_health")
        if health and health.get("config") == (cfg.model, cfg.key_source, cfg.base_url):
            if health["ok"]:
                st.success(f"Connected at {health['checked_at']}: {health['model']} answered with a tool call in "
                           f"{health['latency_ms'] / 1000:.1f} s.")
            else:
                st.error(f"Connection test failed at {health['checked_at']}. "
                         f"{health.get('summary') or health['message']}")
                if health.get("detail"):
                    with st.expander("Provider message (key removed)"):
                        st.caption(health["detail"])
    with st.expander("Engine diagnostics"):
        _engine_diagnostics(cfg)


def _engine_diagnostics(cfg: LLMConfig) -> None:
    """Names and settings only: no key, passcode or other secret value is ever shown."""
    rep = SECRETS_REPORT
    if rep.get("read"):
        names = ", ".join(rep["names"]) or "none of this app's settings"
        extra = f" (plus {rep['other_count']} other secret(s) this app does not use)" if rep.get("other_count") else ""
        st.caption(f"Hosted secrets found: {names}{extra}.")
    else:
        st.caption("No hosted secrets file: settings come from environment variables or .env.")
    if rep.get("error"):
        st.caption(rep["error"])
    for note in rep.get("notes", []):
        st.caption(note)
    key_names = [n for n in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "LLM_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(n)]
    st.caption("Key variables present: " + (", ".join(key_names) or "none") + ".")
    if cfg.enabled:
        st.caption(f"Model {cfg.model} at {urlparse(cfg.base_url or '').netloc or cfg.base_url}; key read from "
                   f"{cfg.key_source}. Passcode lock: {'on' if _passcode() else 'off'}.")
    elif cfg.problem:
        st.caption(redact(cfg.problem))


def engine_preview() -> tuple[str, str]:
    """(kind, text) describing which engine the next investigation will use and why."""
    backend, reason = engine_plan()
    cfg = get_settings().llm
    if backend is not None:
        return "llm", (f"Engine for this run: {engine_name(cfg)} ({cfg.model}) will choose the tools and write the "
                       "findings. Each investigation uses about 9 to 12 model requests. If the provider fails, the "
                       "rule-based protocol finishes the run and the report says so.")
    why = {"selected": "selected in the sidebar.",
           "no_credentials": "no LLM credentials are configured on this deployment.",
           "config_problem": "the LLM settings could not be used (see Engine diagnostics in the sidebar).",
           "switched_off": "the LLM is switched off by LLM_PROVIDER.",
           "locked": "the model is locked until the passcode is entered in the sidebar."}.get(reason, "")
    return "rules", f"Engine for this run: rule-based protocol, because {why}"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
