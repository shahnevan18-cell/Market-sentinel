"""Return calculations.

Prices are not comparable across securities (a $900 stock and a $40 stock),
but returns are: a return expresses the change as a fraction of the starting
price. All calculations use the adjusted close, which removes the mechanical
price drops caused by dividends and stock splits.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def clean_prices(prices: pd.Series) -> pd.Series:
    """Non-positive or missing prices are treated as missing values."""
    p = pd.to_numeric(prices, errors="coerce").astype(float)
    return p.where(p > 0)


def simple_returns(prices: pd.Series) -> pd.Series:
    """r_t = P_t / P_{t-1} - 1. The first observation is NaN by construction."""
    p = clean_prices(prices)
    return p / p.shift(1) - 1.0


def log_returns(prices: pd.Series) -> pd.Series:
    """l_t = ln(P_t / P_{t-1}). Log returns add up over time; simple returns compound."""
    p = clean_prices(prices)
    return np.log(p / p.shift(1))


def annualised_volatility(returns: pd.Series, window: int, periods_per_year: int = 252,
                          min_periods: int | None = None) -> pd.Series:
    """Rolling standard deviation of daily returns scaled by sqrt(252).

    This is historical (realised) volatility: a description of the past window,
    not a forecast of future volatility.
    """
    mp = min_periods if min_periods is not None else max(2, int(window * 0.8))
    return returns.rolling(window, min_periods=mp).std(ddof=1) * math.sqrt(periods_per_year)


def cumulative_return(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return float("nan")
    return float((1.0 + r).prod() - 1.0)


def period_return(prices: pd.Series, periods: int) -> float:
    """Return over the last `periods` observations, using the latest available prices."""
    p = clean_prices(prices).dropna()
    if len(p) <= periods:
        return float("nan")
    return float(p.iloc[-1] / p.iloc[-1 - periods] - 1.0)


def forward_returns(prices: pd.Series, horizon: int) -> pd.Series:
    """FUTURE return from t to t+h. Used only for retrospective evaluation, never for detection."""
    p = clean_prices(prices)
    return p.shift(-horizon) / p - 1.0
