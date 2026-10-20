import math

import numpy as np
import pandas as pd
import pytest

from analytics.returns import (annualised_volatility, cumulative_return, forward_returns, log_returns,
                               period_return, simple_returns)


def test_simple_returns_known_values():
    p = pd.Series([100.0, 110.0, 99.0])
    r = simple_returns(p)
    assert math.isnan(r.iloc[0])
    assert r.iloc[1] == pytest.approx(0.10)
    assert r.iloc[2] == pytest.approx(-0.10)


def test_log_returns_add_up_to_total():
    p = pd.Series([50.0, 55.0, 60.5, 48.4])
    lr = log_returns(p).dropna()
    assert lr.sum() == pytest.approx(math.log(48.4 / 50.0))


def test_non_positive_prices_become_missing_returns():
    p = pd.Series([100.0, 0.0, 105.0, -1.0, 110.0])
    r = simple_returns(p)
    assert r.isna().sum() == 5          # first value, both invalid prices, and the days after them


def test_annualised_volatility_scaling():
    r = pd.Series([0.01, -0.01] * 30)
    vol = annualised_volatility(r, window=20)
    daily = r.iloc[-20:].std(ddof=1)
    assert vol.iloc[-1] == pytest.approx(daily * math.sqrt(252))


def test_cumulative_and_period_return():
    assert cumulative_return(pd.Series([0.1, -0.1])) == pytest.approx(-0.01)
    assert period_return(pd.Series([100.0, 105.0, 110.0]), 2) == pytest.approx(0.10)
    assert math.isnan(period_return(pd.Series([100.0]), 5))


def test_forward_returns_look_forward_only_by_design():
    p = pd.Series([100.0, 101.0, 103.0, 99.0])
    f = forward_returns(p, 2)
    assert f.iloc[0] == pytest.approx(103.0 / 100.0 - 1)
    assert f.iloc[-1] != f.iloc[-1]   # NaN: no future data
