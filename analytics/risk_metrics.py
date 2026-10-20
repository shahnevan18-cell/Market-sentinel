"""Risk measures and what-if scenario calculations.

Observed inputs (betas, volatilities, historical returns) are computed from
market data up to a stated date. Scenario inputs (shocks, new weights,
volatility multipliers) are assumptions typed in by the user. ScenarioResult
keeps the two apart so a hypothetical number is never displayed as an
observation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import NormalDist

import numpy as np
import pandas as pd

from analytics.anomaly_detection import ScanResult
from config.market import CURRENCY


def _num(x):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    return float(x)


# ---------------------------------------------------------------------------
# Single-security risk
# ---------------------------------------------------------------------------

def historical_var(returns: pd.Series, confidence: float = 0.95, min_obs: int = 30) -> float | None:
    """One-day historical Value at Risk, reported as a positive loss fraction.

    VaR = -quantile(returns, 1 - confidence). With 95% confidence, roughly one
    day in twenty in the sample lost more than this amount.
    """
    r = pd.Series(returns).dropna()
    if len(r) < min_obs:
        return None
    return float(-np.quantile(r.to_numpy(), 1.0 - confidence))


def historical_es(returns: pd.Series, confidence: float = 0.95, min_obs: int = 30) -> float | None:
    """Expected shortfall: average loss on the days beyond the VaR cut-off."""
    r = pd.Series(returns).dropna()
    if len(r) < min_obs:
        return None
    cutoff = np.quantile(r.to_numpy(), 1.0 - confidence)
    tail = r[r <= cutoff]
    return float(-tail.mean()) if len(tail) else None


def parametric_var(sigma_daily: float | None, confidence: float = 0.95, mean_daily: float = 0.0) -> float | None:
    """Normal-distribution VaR: z * sigma - mean. Assumes normal returns, which understates tail risk."""
    if sigma_daily is None or (isinstance(sigma_daily, float) and math.isnan(sigma_daily)):
        return None
    z = NormalDist().inv_cdf(confidence)
    return float(z * sigma_daily - mean_daily)


def max_drawdown(prices: pd.Series) -> float | None:
    p = pd.Series(prices).dropna()
    if len(p) < 2:
        return None
    return float((p / p.cummax() - 1.0).min())


def risk_snapshot(scan: ScanResult, ticker: str, date) -> dict:
    """Risk measures for one stock using only data up to and including `date`."""
    cfg = scan.config
    df = scan.features.get(ticker)
    date = pd.Timestamp(date)
    if df is None or date not in df.index:
        return {"available": False, "reason": "No data for that date."}
    hist = df.loc[:date]
    r = hist["ret"].dropna()
    r_var = r.iloc[-cfg.var_window:]
    r_pre = r.iloc[:-1]  # excludes the event day
    sigma60 = r.iloc[-60:].std() if len(r) >= 40 else None
    row = hist.iloc[-1]
    var_pre = historical_var(r_pre.iloc[-cfg.var_window:], cfg.var_confidence)
    event_ret = _num(row["ret"])
    loss_multiple = None
    if event_ret is not None and var_pre:
        loss_multiple = float(abs(event_ret) / var_pre)
    return {
        "available": True,
        "ticker": ticker,
        "as_of": f"{date:%Y-%m-%d}",
        "observations_used": int(len(r_var)),
        "lookback_window_days": cfg.var_window,
        "method": "historical simulation (empirical quantile of daily returns)",
        "units": "fraction of position value (currency-independent)",
        "vol_10d_annualised": _num(row["vol_short_ann"]),
        "vol_prior_60d_annualised": _num(row["vol_long_ann"]),
        "vol_regime_ratio": _num(row["vol_ratio"]),
        "hist_var_1d": historical_var(r_var, cfg.var_confidence),
        "hist_es_1d": historical_es(r_var, cfg.var_confidence),
        "hist_var_1d_before_event": var_pre,
        "param_var_1d_60d_sigma": parametric_var(_num(sigma60), cfg.var_confidence),
        "confidence": cfg.var_confidence,
        "max_drawdown_120d": max_drawdown(hist["close"].iloc[-120:]),
        "beta": _num(row["beta"]),
        "event_day_return": event_ret,
        "event_move_as_multiple_of_prior_var": loss_multiple,
        "notes": [
            "Value at Risk figures are one-day, historical, at the stated confidence level, "
            f"using up to {cfg.var_window} trading days ending on the event date.",
            "Parametric VaR assumes normally distributed returns, which usually understates tail losses.",
        ],
    }


# ---------------------------------------------------------------------------
# Portfolio helpers (illustrative, hypothetical portfolio)
# ---------------------------------------------------------------------------

def normalise_weights(weights: dict[str, float]) -> dict[str, float]:
    clean = {k: max(float(v), 0.0) for k, v in weights.items() if v is not None}
    total = sum(clean.values())
    if total <= 0:
        return {k: 0.0 for k in clean}
    return {k: v / total for k, v in clean.items()}


def hhi(weights: dict[str, float]) -> float:
    w = normalise_weights(weights)
    return float(sum(v * v for v in w.values()))


def concentration_summary(weights: dict[str, float], sectors: dict[str, str] | None = None) -> dict:
    w = normalise_weights(weights)
    if not w:
        return {"hhi": None, "effective_n": None, "top_ticker": None, "top_weight": None, "sector_weights": {}}
    h = hhi(w)
    top = max(w, key=w.get)
    sector_w: dict[str, float] = {}
    if sectors:
        for t, v in w.items():
            sector_w[sectors.get(t, "Unclassified")] = sector_w.get(sectors.get(t, "Unclassified"), 0.0) + v
    return {
        "hhi": h,
        "effective_n": 1.0 / h if h > 0 else None,
        "top_ticker": top,
        "top_weight": w[top],
        "sector_weights": dict(sorted(sector_w.items(), key=lambda kv: -kv[1])),
    }


def reweight(weights: dict[str, float], ticker: str, new_weight: float) -> dict[str, float]:
    """Set one position to `new_weight` and scale the others so the total stays 1."""
    w = normalise_weights(weights)
    new_weight = min(max(float(new_weight), 0.0), 1.0)
    others = {k: v for k, v in w.items() if k != ticker}
    rest = sum(others.values())
    out = {ticker: new_weight}
    for k, v in others.items():
        out[k] = (1.0 - new_weight) * (v / rest) if rest > 0 else 0.0
    return out


def portfolio_returns(scan: ScanResult, weights: dict[str, float], end=None, window: int | None = None) -> pd.Series:
    """Daily returns of a fixed-weight portfolio (daily rebalanced) from observed stock returns."""
    w = normalise_weights({k: v for k, v in weights.items() if k in scan.panel.returns.columns})
    if not w:
        return pd.Series(dtype=float)
    rets = scan.panel.returns[list(w)]
    if end is not None:
        rets = rets.loc[: pd.Timestamp(end)]
    rets = rets.dropna(how="any")
    port = rets.mul(pd.Series(w), axis=1).sum(axis=1)
    if window:
        port = port.iloc[-window:]
    return port


@dataclass
class ScenarioResult:
    name: str
    formula: str
    observed_inputs: dict = field(default_factory=dict)   # computed from market data, with provenance
    assumptions: dict = field(default_factory=dict)       # typed in by the user, hypothetical
    outputs: dict = field(default_factory=dict)           # hypothetical results
    table: pd.DataFrame | None = None
    is_hypothetical: bool = True


def stress_single_holding(weights: dict[str, float], value: float, ticker: str, shock: float) -> ScenarioResult:
    w = normalise_weights(weights)
    wi = w.get(ticker, 0.0)
    pnl = value * wi * shock
    return ScenarioResult(
        name=f"{ticker} moves {shock:+.0%}",
        formula="Change in portfolio value = portfolio value x weight of holding x shock",
        assumptions={"shock": shock, "portfolio_value": value, "currency": CURRENCY,
                     "weights": "illustrative, user-editable"},
        outputs={
            "weight": wi,
            "pnl": pnl,
            "portfolio_return": wi * shock,
            "new_value": value + pnl,
        },
    )


def stress_market(weights: dict[str, float], betas: dict[str, float | None], value: float,
                  market_shock: float, beta_as_of: str = "") -> ScenarioResult:
    """Market shock propagated through each holding's estimated beta (a linear, one-factor assumption)."""
    w = normalise_weights(weights)
    rows = []
    for t, wi in w.items():
        b = betas.get(t)
        b_used = 1.0 if b is None else b
        move = b_used * market_shock
        rows.append({
            "ticker": t, "weight": wi, "beta": b, "beta_used": b_used,
            "assumed_move": move, "contribution": wi * move, "pnl": value * wi * move,
        })
    table = pd.DataFrame(rows).sort_values("pnl")
    port_ret = float(table["contribution"].sum()) if not table.empty else 0.0
    return ScenarioResult(
        name=f"Benchmark moves {market_shock:+.0%}",
        formula="Holding move = beta x market shock; portfolio return = sum(weight x holding move)",
        observed_inputs={"betas": "OLS market-model betas, 120 trading days", "as_of": beta_as_of},
        assumptions={"market_shock": market_shock, "portfolio_value": value, "currency": CURRENCY,
                     "missing_beta_rule": "beta treated as 1.0 when it could not be estimated"},
        outputs={"portfolio_return": port_ret, "pnl": value * port_ret, "new_value": value * (1 + port_ret)},
        table=table,
    )


def stress_sector(weights: dict[str, float], sectors: dict[str, str], value: float,
                  sector: str, shock: float) -> ScenarioResult:
    w = normalise_weights(weights)
    exposure = sum(v for t, v in w.items() if sectors.get(t) == sector)
    return ScenarioResult(
        name=f"{sector} holdings move {shock:+.0%}",
        formula="Change in value = portfolio value x (sum of weights in the sector) x shock",
        assumptions={"sector_shock": shock, "portfolio_value": value, "currency": CURRENCY},
        outputs={"sector_weight": exposure, "portfolio_return": exposure * shock,
                 "pnl": value * exposure * shock, "new_value": value * (1 + exposure * shock)},
    )


def volatility_scenario(port_returns: pd.Series, vol_multiplier: float, value: float,
                        confidence: float = 0.95, as_of: str = "") -> ScenarioResult:
    """Scale the observed return history by k = vol_multiplier.

    Scaling every daily return by k scales the standard deviation by k, so both
    historical and parametric VaR scale linearly with k (a simplifying
    assumption: the shape of the distribution is unchanged).
    """
    base_hist = historical_var(port_returns, confidence)
    base_sigma = float(port_returns.std()) if len(port_returns.dropna()) > 2 else None
    base_param = parametric_var(base_sigma, confidence)
    new_hist = None if base_hist is None else base_hist * vol_multiplier
    new_param = None if base_param is None else base_param * vol_multiplier
    return ScenarioResult(
        name=f"Volatility x {vol_multiplier:.2f}",
        formula="VaR(new) = k x VaR(observed), where k is the volatility multiplier",
        observed_inputs={
            "observations": int(port_returns.dropna().shape[0]),
            "as_of": as_of,
            "observed_daily_sigma": base_sigma,
            "observed_hist_var_1d": base_hist,
            "observed_param_var_1d": base_param,
        },
        assumptions={"vol_multiplier": vol_multiplier, "confidence": confidence, "portfolio_value": value,
                     "currency": CURRENCY},
        outputs={
            "hist_var_1d": new_hist,
            "param_var_1d": new_param,
            "hist_var_1d_value": None if new_hist is None else new_hist * value,
            "param_var_1d_value": None if new_param is None else new_param * value,
        },
    )


def event_portfolio_exposure(weights: dict[str, float], sectors: dict[str, str], ticker: str,
                             event_return: float | None, value: float) -> dict:
    w = normalise_weights(weights)
    wi = w.get(ticker, 0.0)
    sector = sectors.get(ticker)
    sector_w = sum(v for t, v in w.items() if sectors.get(t) == sector)
    conc = concentration_summary(w, sectors)
    contribution = None if event_return is None else wi * event_return
    return {
        "portfolio_is_illustrative": True,
        "holding_weight": wi,
        "sector": sector,
        "sector_weight": sector_w,
        "event_day_contribution_to_portfolio_return": contribution,
        "event_day_pnl_on_illustrative_value": None if contribution is None else contribution * value,
        "illustrative_portfolio_value": value,
        "currency": CURRENCY,
        "hhi": conc["hhi"],
        "effective_number_of_holdings": conc["effective_n"],
    }
