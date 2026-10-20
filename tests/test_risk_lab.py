"""What-if calculations and the separation of observed and hypothetical values."""
import numpy as np
import pandas as pd
import pytest

from analytics import risk_metrics as rm


W = {"A": 0.5, "B": 0.3, "C": 0.2}


def test_single_holding_stress_formula():
    res = rm.stress_single_holding(W, 1_000_000, "A", -0.10)
    assert res.outputs["pnl"] == pytest.approx(-50_000)
    assert res.outputs["new_value"] == pytest.approx(950_000)
    assert res.is_hypothetical and "weight" in res.formula


def test_market_stress_uses_beta_and_default_for_missing():
    res = rm.stress_market(W, {"A": 1.2, "B": 0.8, "C": None}, 1_000_000, -0.05)
    expected = 0.5 * 1.2 * -0.05 + 0.3 * 0.8 * -0.05 + 0.2 * 1.0 * -0.05
    assert res.outputs["portfolio_return"] == pytest.approx(expected)
    assert "missing_beta_rule" in res.assumptions


def test_concentration_and_reweight():
    assert rm.hhi(W) == pytest.approx(0.25 + 0.09 + 0.04)
    new = rm.reweight(W, "C", 0.6)
    assert sum(new.values()) == pytest.approx(1.0)
    assert new["C"] == pytest.approx(0.6)
    assert new["A"] / new["B"] == pytest.approx(0.5 / 0.3)
    summary = rm.concentration_summary(new, {"A": "S1", "B": "S1", "C": "S2"})
    assert summary["top_ticker"] == "C" and summary["sector_weights"]["S2"] == pytest.approx(0.6)


def test_volatility_scenario_scales_var_linearly():
    r = pd.Series(np.random.default_rng(5).normal(0, 0.01, 500))
    base = rm.volatility_scenario(r, 1.0, 1_000_000)
    double = rm.volatility_scenario(r, 2.0, 1_000_000)
    assert double.outputs["hist_var_1d"] == pytest.approx(2 * base.outputs["hist_var_1d"])
    assert double.outputs["param_var_1d"] == pytest.approx(2 * base.outputs["param_var_1d"])


def test_historical_var_and_es_on_known_sample():
    r = pd.Series(np.linspace(-0.05, 0.05, 101))
    var = rm.historical_var(r, 0.95)
    assert var == pytest.approx(0.045, abs=1e-3)
    assert rm.historical_es(r, 0.95) >= var
    assert rm.historical_var(pd.Series([0.01] * 10)) is None       # too few observations


def test_observed_and_hypothetical_values_are_kept_apart():
    r = pd.Series(np.random.default_rng(6).normal(0, 0.01, 300))
    res = rm.volatility_scenario(r, 1.5, 1_000_000, as_of="2026-09-30")
    assert set(res.observed_inputs) & set(res.outputs) == set()
    assert "observed_hist_var_1d" in res.observed_inputs and "hist_var_1d" in res.outputs
    assert res.assumptions["vol_multiplier"] == 1.5 and res.is_hypothetical


def test_risk_snapshot_uses_only_data_to_the_event(demo_monitor):
    scan = demo_monitor.scan
    date = pd.Timestamp("2026-09-17")
    snap = rm.risk_snapshot(scan, "IRONBRG.DEMO", date)
    assert snap["as_of"] == "2026-09-17"
    assert snap["lookback_window_days"] == 250 and snap["confidence"] == 0.95 and "currency" in snap["units"]
    r = scan.features["IRONBRG.DEMO"].loc[:date, "ret"].dropna().iloc[:-1].iloc[-250:]
    assert snap["hist_var_1d_before_event"] == pytest.approx(rm.historical_var(r, 0.95))
    assert snap["event_move_as_multiple_of_prior_var"] > 2


def test_stress_results_are_labelled_in_rupees():
    w = {"A.NS": 0.6, "B.NS": 0.4}
    res = rm.stress_single_holding(w, 1_00_00_000, "A.NS", -0.10)
    assert res.assumptions["currency"] == "INR" and res.outputs["pnl"] == pytest.approx(-6_00_000)
    from config.market import fmt_inr, fmt_inr_short
    assert fmt_inr(res.outputs["pnl"]) == "-₹6,00,000" and fmt_inr_short(res.outputs["new_value"]) == "₹94.00 lakh"
