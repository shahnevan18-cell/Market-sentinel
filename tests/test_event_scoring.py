import pytest

from analytics.event_scoring import score_components, severity_label
from config.settings import AnalysisConfig


def test_default_weights_are_valid(cfg):
    assert cfg.validate() == []
    assert sum(cfg.weights().values()) == pytest.approx(1.0)


def test_invalid_configuration_is_reported():
    bad = AnalysisConfig(w_price=0.5, w_abnormal=0.5, w_volume=0.5, w_vol_regime=0.1, min_obs=200)
    problems = bad.validate()
    assert any("weights" in p for p in problems)
    assert any("min_obs" in p for p in problems)


def test_score_bounds(cfg):
    assert score_components(0, 0, 0, 1.0, cfg)["score"] == pytest.approx(0.0)
    assert score_components(10, -10, 10, 5.0, cfg)["score"] == pytest.approx(100.0)


def test_score_is_monotonic_and_symmetric_in_return_z(cfg):
    s3 = score_components(3, 0, 0, 1.0, cfg)["score"]
    s4 = score_components(4, 0, 0, 1.0, cfg)["score"]
    s_neg = score_components(-4, 0, 0, 1.0, cfg)["score"]
    assert s4 > s3 > 0
    assert s4 == pytest.approx(s_neg)


def test_low_volume_does_not_add_points(cfg):
    assert score_components(0, 0, -5, 1.0, cfg)["score"] == pytest.approx(0.0)


def test_missing_component_contributes_zero_and_is_flagged(cfg):
    out = score_components(3, None, 3, None, cfg)
    assert out["components"]["abnormal"]["missing"] is True
    assert out["components"]["abnormal"]["points"] == 0
    expected = 100 * (cfg.w_price * 0.5 + cfg.w_volume * 0.5)
    assert out["score"] == pytest.approx(expected)


def test_severity_bands(cfg):
    assert severity_label(85, cfg) == "Critical"
    assert severity_label(55, cfg) == "High"
    assert severity_label(35, cfg) == "Moderate"
    assert severity_label(10, cfg) == "Low"
    assert severity_label(float("nan"), cfg) == "Unscored"
