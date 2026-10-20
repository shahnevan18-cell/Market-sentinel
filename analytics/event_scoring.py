"""Transparent event-priority score.

Each component is first normalised to the range 0..1, then combined with fixed
weights:

    s_price    = min(|z_ret| / z_cap, 1)
    s_abnormal = min(|z_abn| / z_cap, 1)
    s_volume   = min(max(z_volume, 0) / z_cap, 1)
    s_regime   = min(max(vol_ratio - 1, 0) / (vol_ratio_cap - 1), 1)

    priority = 100 * (w_price*s_price + w_abnormal*s_abnormal
                      + w_volume*s_volume + w_vol_regime*s_regime)

The score ranks events for analyst attention. It is not the probability that a
headline caused the move, and it is not a forecast of future prices. A missing
component (for example, no beta because history is too short) contributes zero
and is reported as missing.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from config.settings import AnalysisConfig

COMPONENT_LABELS = {
    "price": "Abnormal price move (robust z of return)",
    "abnormal": "Market-relative move (z of market-model abnormal return)",
    "volume": "Abnormal volume (robust z of log volume)",
    "vol_regime": "Volatility regime shift (10-day vs earlier 60-day volatility)",
}


def _clip01(x):
    return np.clip(x, 0.0, 1.0)


def component_scores_frame(df: pd.DataFrame, cfg: AnalysisConfig) -> pd.DataFrame:
    """Vectorised component scores for a feature frame (one row per date)."""
    out = pd.DataFrame(index=df.index)
    out["s_price"] = _clip01(df["z_ret"].abs() / cfg.z_cap).fillna(0.0)
    out["s_abnormal"] = _clip01(df["z_abn"].abs() / cfg.z_cap).fillna(0.0)
    out["s_volume"] = _clip01(df["z_volume"].clip(lower=0) / cfg.z_cap).fillna(0.0)
    regime = (df["vol_ratio"] - 1.0).clip(lower=0) / max(cfg.vol_ratio_cap - 1.0, 1e-9)
    out["s_regime"] = _clip01(regime).fillna(0.0)
    w = cfg.weights()
    out["priority_score"] = 100.0 * (
        w["price"] * out["s_price"]
        + w["abnormal"] * out["s_abnormal"]
        + w["volume"] * out["s_volume"]
        + w["vol_regime"] * out["s_regime"]
    )
    return out


def score_components(z_ret: float | None, z_abn: float | None, z_volume: float | None,
                     vol_ratio: float | None, cfg: AnalysisConfig) -> dict:
    """Scalar version used in reports. Returns each component and its weighted contribution."""

    def safe(v):
        return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

    z_ret, z_abn, z_volume, vol_ratio = map(safe, (z_ret, z_abn, z_volume, vol_ratio))
    raw = {
        "price": None if z_ret is None else min(abs(z_ret) / cfg.z_cap, 1.0),
        "abnormal": None if z_abn is None else min(abs(z_abn) / cfg.z_cap, 1.0),
        "volume": None if z_volume is None else min(max(z_volume, 0.0) / cfg.z_cap, 1.0),
        "vol_regime": None if vol_ratio is None else min(max(vol_ratio - 1.0, 0.0) / (cfg.vol_ratio_cap - 1.0), 1.0),
    }
    weights = cfg.weights()
    parts = {}
    total = 0.0
    for key, value in raw.items():
        contribution = 0.0 if value is None else 100.0 * weights[key] * value
        total += contribution
        parts[key] = {
            "label": COMPONENT_LABELS[key],
            "normalised": value,
            "weight": weights[key],
            "points": contribution,
            "missing": value is None,
        }
    return {"score": total, "components": parts}


def severity_label(score: float, cfg: AnalysisConfig) -> str:
    if score is None or (isinstance(score, float) and math.isnan(score)):
        return "Unscored"
    if score >= cfg.severity_critical:
        return "Critical"
    if score >= cfg.severity_high:
        return "High"
    if score >= cfg.severity_moderate:
        return "Moderate"
    return "Low"


SEVERITY_ORDER = {"Critical": 0, "High": 1, "Moderate": 2, "Low": 3, "Unscored": 4}
