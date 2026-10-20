import numpy as np
import pandas as pd
import pytest

from analytics.anomaly_detection import (ROBUST_SCALE, build_panel, compute_stock_features, robust_z,
                                         rolling_market_model, rolling_prior_median_mad, scan_universe)
from config.settings import AnalysisConfig
from config.watchlist import Security, Universe


def test_baseline_excludes_the_current_day():
    values = pd.Series([0.0, 1.0, 2.0, 3.0, 100.0])
    med, mad, n = rolling_prior_median_mad(values, window=4, min_periods=4)
    # The baseline for the last value is built from [0, 1, 2, 3] only.
    assert med.iloc[-1] == pytest.approx(1.5)
    assert mad.iloc[-1] == pytest.approx(1.0)
    assert n.iloc[-1] == 4
    z = robust_z(values, med, mad)
    assert z.iloc[-1] == pytest.approx((100 - 1.5) / (ROBUST_SCALE * 1.0))


def test_insufficient_history_gives_no_score():
    values = pd.Series(np.random.default_rng(1).normal(size=30))
    med, mad, n = rolling_prior_median_mad(values, window=60, min_periods=40)
    assert med.isna().all() and mad.isna().all()


def test_zero_mad_returns_nan_not_infinity():
    values = pd.Series([1.0] * 50 + [5.0])
    med, mad, _ = rolling_prior_median_mad(values, window=40, min_periods=30)
    z = robust_z(values, med, mad)
    assert np.isnan(z.iloc[-1])


def test_missing_values_reduce_count_but_do_not_break():
    vals = pd.Series(np.r_[np.random.default_rng(2).normal(size=60), [np.nan] * 5, [0.0]])
    med, mad, n = rolling_prior_median_mad(vals, window=60, min_periods=40)
    assert n.iloc[-1] == 55
    assert np.isfinite(med.iloc[-1])


def test_market_model_recovers_beta():
    rng = np.random.default_rng(3)
    rm = pd.Series(rng.normal(0, 0.01, 300))
    ri = 0.0002 + 1.5 * rm + pd.Series(rng.normal(0, 0.002, 300))
    mm = rolling_market_model(ri, rm, window=120, min_obs=60)
    assert mm["beta"].iloc[-1] == pytest.approx(1.5, abs=0.06)
    assert mm["r2"].iloc[-1] > 0.9


def test_market_model_for_a_day_ignores_that_days_returns():
    """Alpha, beta and the residual spread used on day t come from days before t only."""
    rng = np.random.default_rng(4)
    rm = pd.Series(rng.normal(0, 0.01, 200))
    ri = 0.8 * rm + pd.Series(rng.normal(0, 0.004, 200))
    base = rolling_market_model(ri, rm, window=120, min_obs=60)
    shocked_ri, shocked_rm = ri.copy(), rm.copy()
    shocked_ri.iloc[-1], shocked_rm.iloc[-1] = -0.25, 0.09        # an extreme event day
    after = rolling_market_model(shocked_ri, shocked_rm, window=120, min_obs=60)
    for col in ("alpha", "beta", "resid_sd", "r2"):
        assert after[col].iloc[-1] == pytest.approx(base[col].iloc[-1])
    direct = np.polyfit(rm.iloc[-121:-1], ri.iloc[-121:-1], 1)[0]   # OLS on the 120 days before the last day
    assert base["beta"].iloc[-1] == pytest.approx(direct)


def _toy_universe():
    return Universe(
        key="toy", label="toy",
        securities=(Security("AAA", "Alpha Co", "Tech", "Alpha"), Security("BBB", "Beta Co", "Tech", "Beta"),
                    Security("CCC", "Gamma Co", "Tech", "Gamma")),
        benchmark="IDX", benchmark_name="Index", sector_indices={"Tech": "SEC"}, sector_index_names={"Tech": "Tech fund"},
    )


def _toy_frames(frame_factory, shock_day=200, shock=-0.12, vol_mult=6.0):
    rng = np.random.default_rng(7)
    n = 260
    rm = rng.normal(0.0003, 0.01, n)
    frames = {"IDX": frame_factory(100 * np.cumprod(1 + rm)),
              "SEC": frame_factory(50 * np.cumprod(1 + rm + rng.normal(0, 0.002, n)))}
    for i, t in enumerate(["AAA", "BBB", "CCC"]):
        r = 1.1 * rm + rng.normal(0, 0.008, n)
        vol = np.exp(np.log(2e6) + rng.normal(0, 0.15, n))
        if t == "AAA":
            r[shock_day] = shock
            vol[shock_day] *= vol_mult
        frames[t] = frame_factory(40 * np.cumprod(1 + r), vol)
    return frames


def test_idiosyncratic_shock_with_volume_is_detected(frame_factory, cfg):
    frames = _toy_frames(frame_factory)
    scan = scan_universe(frames, _toy_universe(), cfg)
    shock_date = frames["AAA"].index[200]
    ev = scan.event(f"AAA:{shock_date:%Y-%m-%d}")
    assert ev is not None
    assert set(ev["event_types"]) >= {"Large price move", "Market-relative move", "Volume spike"}
    assert ev["z_ret"] < -3 and ev["z_abn"] < -3 and ev["z_volume"] > 3
    assert ev["severity"] in ("Critical", "High")
    assert ev["triggers"] and all(isinstance(t, str) for t in ev["triggers"])


def test_zero_volume_is_ignored_by_volume_test(frame_factory, cfg):
    frames = _toy_frames(frame_factory)
    frames["BBB"].iloc[150, frames["BBB"].columns.get_loc("volume")] = 0.0
    scan = scan_universe(frames, _toy_universe(), cfg)
    f = scan.features["BBB"]
    d = frames["BBB"].index[150]
    assert np.isnan(f.loc[d, "z_volume"])
    assert not bool(f.loc[d, "trig_volume"])


def test_missing_benchmark_disables_market_model_but_not_detection(frame_factory, cfg):
    frames = _toy_frames(frame_factory)
    frames.pop("IDX")
    scan = scan_universe(frames, _toy_universe(), cfg)
    f = scan.features["AAA"]
    assert f["beta"].isna().all()
    assert len(scan.events) > 0          # price and volume tests still work


def test_thresholds_change_alert_counts(frame_factory):
    frames = _toy_frames(frame_factory)
    low = scan_universe(frames, _toy_universe(), AnalysisConfig(z_price=2.0, z_abnormal=2.0, z_volume=2.0))
    high = scan_universe(frames, _toy_universe(), AnalysisConfig(z_price=4.0, z_abnormal=4.0, z_volume=4.0))
    assert len(low.events) > len(high.events) >= 1


def test_panel_uses_benchmark_calendar(frame_factory, cfg):
    frames = _toy_frames(frame_factory)
    frames["AAA"] = frames["AAA"].drop(frames["AAA"].index[100])
    panel = build_panel(frames, "IDX", cfg)
    assert len(panel.calendar) == len(frames["IDX"])
    assert np.isnan(panel.returns.loc[frames["IDX"].index[100], "AAA"])
