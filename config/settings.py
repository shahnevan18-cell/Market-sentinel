"""Central configuration for Market Sentinel.

Every threshold, window and weight used by the analytics lives here, so the
same values can be shown in the interface, written into reports and changed
in one place. Secrets are read from environment variables (or a local .env
file) and are never written to disk by the application.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:  # python-dotenv is optional; the app still works without a .env file
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if load_dotenv is not None and os.environ.get("MS_DISABLE_DOTENV") != "1":
    load_dotenv(PROJECT_ROOT / ".env", override=False)

DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = Path(os.environ.get("MS_CACHE_DIR") or (DATA_DIR / "cache"))
HISTORY_DIR = Path(os.environ.get("MS_HISTORY_DIR") or (DATA_DIR / "investigations"))

APP_NAME = "Market Sentinel"
APP_VERSION = "2.0.0-india"
AUTHORS = (
    ("Darshil Mittal", "A016", "74052400181"),
    ("Nevan Shah", "A043", "74052400240"),
)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(_env(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = _env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AnalysisConfig:
    """Statistical settings. Window lengths are in trading days."""

    lookback: int = 60            # rolling baseline for robust z-scores
    min_obs: int = 40             # baseline observations needed before a z-score is produced
    beta_window: int = 120        # estimation window for the market model (alpha, beta)
    beta_min_obs: int = 60
    vol_short: int = 10           # recent window for the volatility-regime ratio (includes event day)
    vol_long: int = 60            # earlier baseline window for the volatility-regime ratio
    z_price: float = 3.0          # |robust z| of the raw return that triggers an alert
    z_abnormal: float = 3.0       # |z| of the market-model abnormal return that triggers an alert
    z_volume: float = 3.0         # robust z of log volume that triggers an alert (one-sided)
    z_cap: float = 6.0            # z level that earns a full component score
    vol_ratio_cap: float = 3.0    # volatility ratio that earns a full component score
    w_price: float = 0.35
    w_abnormal: float = 0.30
    w_volume: float = 0.25
    w_vol_regime: float = 0.10
    severity_critical: float = 70.0
    severity_high: float = 50.0
    severity_moderate: float = 30.0
    var_window: int = 250
    var_confidence: float = 0.95
    annualisation: int = 252
    large_gap_threshold: float = 0.25

    def weights(self) -> dict[str, float]:
        return {
            "price": self.w_price,
            "abnormal": self.w_abnormal,
            "volume": self.w_volume,
            "vol_regime": self.w_vol_regime,
        }

    def validate(self) -> list[str]:
        problems = []
        total = sum(self.weights().values())
        if abs(total - 1.0) > 1e-6:
            problems.append(f"Score weights must add up to 1.0 (currently {total:.3f}).")
        if self.min_obs > self.lookback:
            problems.append("min_obs cannot exceed lookback.")
        if self.beta_min_obs > self.beta_window:
            problems.append("beta_min_obs cannot exceed beta_window.")
        for name in ("z_price", "z_abnormal", "z_volume", "z_cap"):
            if getattr(self, name) <= 0:
                problems.append(f"{name} must be positive.")
        if not (self.severity_critical > self.severity_high > self.severity_moderate > 0):
            problems.append("Severity bands must be ordered critical > high > moderate > 0.")
        return problems

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DataConfig:
    provider: str = "yfinance"          # Yahoo Finance via yfinance (NSE symbols ending in .NS)
    history_days: int = 760             # calendar days requested (roughly two years)
    cache_ttl_hours: float = 6.0
    request_timeout: float = 15.0
    max_retries: int = 2
    throttle_seconds: float = 0.35
    max_workers: int = 3
    news_enabled: bool = True
    news_timeout: float = 10.0
    default_mode: str = "live"          # live | demo


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "none"              # none | anthropic | openai_compatible
    model: str = ""
    api_key: str | None = None
    base_url: str | None = None
    max_tool_calls: int = 14
    max_turns: int = 10
    timeout: float = 240.0
    max_tokens: int = 8000
    rate_limit_retries: int = 2         # retries after HTTP 429/503, waiting as long as the provider asks
    rate_limit_max_wait: float = 65.0   # longest single wait in seconds; a longer requested wait fails the step

    @property
    def enabled(self) -> bool:
        return self.provider in {"anthropic", "openai_compatible"} and bool(self.api_key) and bool(self.model)

    def describe(self) -> str:
        if not self.enabled:
            return "No LLM configured (rule-based reasoning engine)"
        label = "Anthropic API" if self.provider == "anthropic" else f"OpenAI-compatible API ({self.base_url})"
        return f"{self.model} via {label}"


@dataclass(frozen=True)
class Settings:
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    data: DataConfig = field(default_factory=DataConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)


def load_llm_config() -> LLMConfig:
    provider = (_env("LLM_PROVIDER") or "").lower()
    anthropic_key = _env("ANTHROPIC_API_KEY")
    generic_key = _env("LLM_API_KEY")
    if not provider:
        provider = "anthropic" if anthropic_key else ("openai_compatible" if generic_key else "none")
    retries = _env_int("LLM_RATE_LIMIT_RETRIES", 2)
    max_wait = _env_float("LLM_RATE_LIMIT_MAX_WAIT", 65.0)
    if provider == "anthropic":
        return LLMConfig(
            provider="anthropic",
            model=_env("LLM_MODEL", "claude-sonnet-5-5"),
            api_key=anthropic_key or generic_key,
            base_url=_env("ANTHROPIC_API_URL", "https://api.anthropic.com"),
            max_tool_calls=_env_int("LLM_MAX_TOOL_CALLS", 14),
            timeout=_env_float("LLM_TIMEOUT", 240.0),
            rate_limit_retries=retries, rate_limit_max_wait=max_wait,
        )
    if provider in {"openai", "openai_compatible", "gemini", "groq"}:
        return LLMConfig(
            provider="openai_compatible",
            model=_env("LLM_MODEL", ""),
            api_key=generic_key,
            base_url=_env("LLM_BASE_URL", "https://api.openai.com/v1"),
            max_tool_calls=_env_int("LLM_MAX_TOOL_CALLS", 14),
            timeout=_env_float("LLM_TIMEOUT", 240.0),
            rate_limit_retries=retries, rate_limit_max_wait=max_wait,
        )
    return LLMConfig(provider="none")


def load_settings(analysis: AnalysisConfig | None = None) -> Settings:
    data = DataConfig(
        provider=(_env("MS_DATA_PROVIDER", "yfinance") or "yfinance").lower(),
        history_days=_env_int("MS_HISTORY_DAYS", 760),
        cache_ttl_hours=_env_float("MS_CACHE_TTL_HOURS", 6.0),
        request_timeout=_env_float("MS_REQUEST_TIMEOUT", 15.0),
        news_enabled=_env_bool("MS_NEWS_ENABLED", True),
        default_mode=(_env("MS_DEFAULT_MODE", "live") or "live").lower(),
    )
    return Settings(analysis=analysis or AnalysisConfig(), data=data, llm=load_llm_config())
