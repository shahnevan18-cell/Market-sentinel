"""Statistical anomaly detection used by the Sentinel Monitor.

Every baseline is computed from observations strictly BEFORE the day being
tested (a window that ends at t-1). The value on day t is then compared with
that baseline. This is what prevents look-ahead bias: nothing on or after day
t+1 can influence the alert for day t. tests/test_historical_replay.py checks
this property by recomputing features on truncated data.

Methods
-------
Robust z-score (price and volume):
    z_t = (x_t - median(x_{t-L..t-1})) / (1.4826 * MAD(x_{t-L..t-1}))
    MAD is the median absolute deviation. Multiplying by 1.4826 makes it
    comparable to a standard deviation for normally distributed data, while a
    few extreme days in the window barely move it.

Market model (event-study abnormal return):
    r_i,t = alpha + beta * r_m,t + e_t, estimated by OLS on the previous
    `beta_window` days. Abnormal return AR_t = r_i,t - (alpha + beta * r_m,t),
    standardised by the residual standard deviation of the estimation window.

Peer-relative return:
    rel_t = r_i,t - median(peer returns on day t), then a robust z-score of rel.

Volatility regime ratio:
    std(returns over the last 10 days, including t) divided by
    std(returns over the 60 days before that 10-day window).
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from analytics.event_scoring import SEVERITY_ORDER, component_scores_frame, severity_label
from config.settings import AnalysisConfig
from config.watchlist import Universe

ROBUST_SCALE = 1.4826

SHORT_TYPE = {"Large price move": "price", "Market-relative move": "relative", "Volume spike": "volume"}
EVENT_TYPE_LABELS = {
    "trig_price": "Large price move",
    "trig_abnormal": "Market-relative move",
    "trig_volume": "Volume spike",
}


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def rolling_prior_median_mad(values: pd.Series, window: int, min_periods: int):
    """Median, MAD and observation count of the `window` values BEFORE each date.

    Returns three Series aligned to `values.index`. Dates with fewer than
    `min_periods` valid prior observations get NaN (insufficient history).
    """
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    n = len(arr)
    idx = values.index
    if n == 0:
        empty = pd.Series(dtype=float, index=idx)
        return empty, empty.copy(), empty.copy()
    padded = np.concatenate([np.full(window, np.nan), arr])
    windows = sliding_window_view(padded, window)[:n]   # row i holds arr[i-window : i]
    counts = np.sum(~np.isnan(windows), axis=1).astype(float)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        med = np.nanmedian(windows, axis=1)
        mad = np.nanmedian(np.abs(windows - med[:, None]), axis=1)
    insufficient = counts < min_periods
    med[insufficient] = np.nan
    mad[insufficient] = np.nan
    return pd.Series(med, index=idx), pd.Series(mad, index=idx), pd.Series(counts, index=idx)


def robust_z(values: pd.Series, median: pd.Series, mad: pd.Series) -> pd.Series:
    """(x - median) / (1.4826 * MAD). A zero MAD gives NaN instead of infinity."""
    scale = ROBUST_SCALE * mad
    return (values - median) / scale.where(scale > 0)


def rolling_market_model(r_stock: pd.Series, r_market: pd.Series, window: int, min_obs: int) -> pd.DataFrame:
    """OLS market model estimated on the `window` days ending at t-1, for every date t."""
    y = r_stock.shift(1)
    x = r_market.shift(1)
    valid = y.notna() & x.notna()
    y = y.where(valid)
    x = x.where(valid)
    mean_x = x.rolling(window, min_periods=min_obs).mean()
    mean_y = y.rolling(window, min_periods=min_obs).mean()
    var_x = x.rolling(window, min_periods=min_obs).var()
    var_y = y.rolling(window, min_periods=min_obs).var()
    cov_xy = x.rolling(window, min_periods=min_obs).cov(y)
    n = valid.astype(float).rolling(window, min_periods=1).sum()
    beta = cov_xy / var_x.where(var_x > 0)
    alpha = mean_y - beta * mean_x
    resid_var = (var_y - beta * cov_xy) * (n - 1) / (n - 2).where(n > 2)
    resid_sd = np.sqrt(resid_var.where(resid_var > 0))
    r2 = (cov_xy ** 2 / (var_x * var_y)).clip(0, 1)
    return pd.DataFrame({"alpha": alpha, "beta": beta, "resid_sd": resid_sd, "r2": r2, "beta_n": n})


# ---------------------------------------------------------------------------
# Panel of aligned prices
# ---------------------------------------------------------------------------

@dataclass
class Panel:
    calendar: pd.DatetimeIndex
    closes: pd.DataFrame
    volumes: pd.DataFrame
    returns: pd.DataFrame
    zscores: pd.DataFrame

    def has(self, symbol: str) -> bool:
        return symbol in self.closes.columns and self.closes[symbol].notna().any()


def build_panel(frames: dict[str, pd.DataFrame], benchmark: str, cfg: AnalysisConfig,
                drop_dates: list | None = None) -> Panel:
    """Align every symbol on the benchmark's trading calendar."""
    usable = {s: f for s, f in frames.items() if f is not None and not f.empty}
    if benchmark in usable:
        calendar = usable[benchmark].index
    elif usable:
        calendar = pd.DatetimeIndex(sorted(set().union(*[f.index for f in usable.values()])))
    else:
        calendar = pd.DatetimeIndex([])
    calendar = pd.DatetimeIndex(calendar).sort_values().unique()
    if drop_dates:
        calendar = calendar.difference(pd.DatetimeIndex(drop_dates))
    closes = pd.DataFrame({s: f["adj_close"] for s, f in usable.items()}).reindex(calendar)
    volumes = pd.DataFrame({s: f["volume"] for s, f in usable.items()}).reindex(calendar)
    closes = closes.where(closes > 0)
    returns = closes / closes.shift(1) - 1.0
    z = {}
    for sym in returns.columns:
        med, mad, _ = rolling_prior_median_mad(returns[sym], cfg.lookback, cfg.min_obs)
        z[sym] = robust_z(returns[sym], med, mad)
    zscores = pd.DataFrame(z, index=calendar)
    return Panel(calendar=calendar, closes=closes, volumes=volumes, returns=returns, zscores=zscores)


# ---------------------------------------------------------------------------
# Features per stock
# ---------------------------------------------------------------------------

def compute_stock_features(ticker: str, panel: Panel, universe: Universe, cfg: AnalysisConfig) -> pd.DataFrame:
    close = panel.closes[ticker]
    r = panel.returns[ticker]
    df = pd.DataFrame(index=panel.calendar)
    df["close"] = close
    df["ret"] = r
    df["log_ret"] = np.log(close / close.shift(1))

    med, mad, count = rolling_prior_median_mad(r, cfg.lookback, cfg.min_obs)
    df["ret_median"] = med
    df["ret_mad"] = mad
    df["baseline_n"] = count
    df["z_ret"] = robust_z(r, med, mad)

    vol = panel.volumes[ticker] if ticker in panel.volumes else pd.Series(np.nan, index=panel.calendar)
    v = vol.where(vol > 0)
    log_v = np.log(v)
    lv_med, lv_mad, _ = rolling_prior_median_mad(log_v, cfg.lookback, cfg.min_obs)
    v_med, _, _ = rolling_prior_median_mad(v, cfg.lookback, cfg.min_obs)
    df["volume"] = vol
    df["volume_median"] = v_med
    df["volume_ratio"] = v / v_med
    df["z_volume"] = robust_z(log_v, lv_med, lv_mad)

    bench = universe.benchmark
    if panel.has(bench):
        rm = panel.returns[bench]
        df["mkt_ret"] = rm
        df["z_mkt"] = panel.zscores[bench]
        mm = rolling_market_model(r, rm, cfg.beta_window, cfg.beta_min_obs)
        for col in mm.columns:
            df[col] = mm[col]
        df["expected_ret"] = df["alpha"] + df["beta"] * rm
        df["abnormal_ret"] = r - df["expected_ret"]
        df["z_abn"] = df["abnormal_ret"] / df["resid_sd"]
    else:
        for col in ("mkt_ret", "z_mkt", "alpha", "beta", "resid_sd", "r2", "beta_n",
                    "expected_ret", "abnormal_ret", "z_abn"):
            df[col] = np.nan

    index_sym = universe.sector_index_for(ticker)
    if index_sym and panel.has(index_sym):
        df["sector_ret"] = panel.returns[index_sym]
        df["z_sector"] = panel.zscores[index_sym]
    else:
        df["sector_ret"] = np.nan
        df["z_sector"] = np.nan

    peers = [p for p in universe.peers_of(ticker) if panel.has(p)]
    if peers:
        peer_r = panel.returns[peers]
        peer_count = peer_r.notna().sum(axis=1)
        peer_med = peer_r.median(axis=1, skipna=True).where(peer_count > 0)
        rel = r - peer_med
        rel_med, rel_mad, _ = rolling_prior_median_mad(rel, cfg.lookback, cfg.min_obs)
        df["peer_median_ret"] = peer_med
        df["peer_count"] = peer_count
        df["rel_peer_ret"] = rel
        df["z_rel_peer"] = robust_z(rel, rel_med, rel_mad)
    else:
        df["peer_median_ret"] = np.nan
        df["peer_count"] = 0
        df["rel_peer_ret"] = np.nan
        df["z_rel_peer"] = np.nan

    short_min = max(2, int(round(cfg.vol_short * 0.8)))
    long_min = max(2, int(round(cfg.vol_long * 0.67)))
    vol_short = r.rolling(cfg.vol_short, min_periods=short_min).std()
    vol_long = r.shift(cfg.vol_short).rolling(cfg.vol_long, min_periods=long_min).std()
    df["vol_short_ann"] = vol_short * math.sqrt(cfg.annualisation)
    df["vol_long_ann"] = vol_long * math.sqrt(cfg.annualisation)
    df["vol_ratio"] = vol_short / vol_long.where(vol_long > 0)

    df = df.join(component_scores_frame(df, cfg))
    df["trig_price"] = df["z_ret"].abs() >= cfg.z_price
    df["trig_abnormal"] = df["z_abn"].abs() >= cfg.z_abnormal
    df["trig_volume"] = df["z_volume"] >= cfg.z_volume
    df["is_event"] = df["trig_price"] | df["trig_abnormal"] | df["trig_volume"]
    return df


# ---------------------------------------------------------------------------
# Event objects
# ---------------------------------------------------------------------------

def _fmt_pct(x: float) -> str:
    return "n/a" if x is None or pd.isna(x) else f"{x:+.2%}"


def describe_triggers(row: pd.Series, cfg: AnalysisConfig, benchmark: str) -> list[str]:
    reasons = []
    if bool(row.get("trig_price")):
        reasons.append(
            f"Daily return of {_fmt_pct(row['ret'])} is {row['z_ret']:+.1f} robust SD from its "
            f"{cfg.lookback}-day median of {_fmt_pct(row['ret_median'])} (alert threshold |z| >= {cfg.z_price:.1f})."
        )
    if bool(row.get("trig_abnormal")):
        reasons.append(
            f"After adjusting for the market ({benchmark} returned {_fmt_pct(row['mkt_ret'])}, "
            f"beta {row['beta']:.2f} over {cfg.beta_window} days), the abnormal return of "
            f"{_fmt_pct(row['abnormal_ret'])} equals {row['z_abn']:+.1f} residual SD "
            f"(threshold |z| >= {cfg.z_abnormal:.1f})."
        )
    if bool(row.get("trig_volume")):
        reasons.append(
            f"Volume of {row['volume']:,.0f} shares is {row['volume_ratio']:.1f}x the {cfg.lookback}-day "
            f"median (robust z of log volume {row['z_volume']:+.1f}; threshold z >= {cfg.z_volume:.1f})."
        )
    return reasons


def event_types_of(row: pd.Series) -> list[str]:
    return [label for col, label in EVENT_TYPE_LABELS.items() if bool(row.get(col))]


def _num(x):
    return None if x is None or pd.isna(x) else float(x)


def build_event_record(ticker: str, date: pd.Timestamp, row: pd.Series, universe: Universe,
                       cfg: AnalysisConfig) -> dict:
    sec = universe.get(ticker)
    score = float(row["priority_score"])
    ret = _num(row["ret"])
    direction = "Flat" if not ret else ("Up" if ret > 0 else "Down")
    return {
        "event_id": f"{ticker}:{date:%Y-%m-%d}",
        "ticker": ticker,
        "name": sec.name if sec else ticker,
        "sector": sec.sector if sec else None,
        "date": pd.Timestamp(date),
        "direction": direction,
        "ret": _num(row["ret"]),
        "z_ret": _num(row["z_ret"]),
        "ret_median": _num(row["ret_median"]),
        "abnormal_ret": _num(row["abnormal_ret"]),
        "z_abn": _num(row["z_abn"]),
        "beta": _num(row["beta"]),
        "mkt_ret": _num(row["mkt_ret"]),
        "z_mkt": _num(row["z_mkt"]),
        "sector_index": universe.sector_index_for(ticker),
        "sector_ret": _num(row["sector_ret"]),
        "z_sector": _num(row["z_sector"]),
        "peer_median_ret": _num(row["peer_median_ret"]),
        "rel_peer_ret": _num(row["rel_peer_ret"]),
        "z_rel_peer": _num(row["z_rel_peer"]),
        "volume": _num(row["volume"]),
        "volume_median": _num(row["volume_median"]),
        "volume_ratio": _num(row["volume_ratio"]),
        "z_volume": _num(row["z_volume"]),
        "vol_ratio": _num(row["vol_ratio"]),
        "vol_short_ann": _num(row["vol_short_ann"]),
        "priority_score": score,
        "severity": severity_label(score, cfg),
        "event_types": event_types_of(row),
        "triggers": describe_triggers(row, cfg, universe.short_label(universe.benchmark)),
        "s_price": _num(row["s_price"]),
        "s_abnormal": _num(row["s_abnormal"]),
        "s_volume": _num(row["s_volume"]),
        "s_regime": _num(row["s_regime"]),
    }


def collect_events(features: dict[str, pd.DataFrame], universe: Universe, cfg: AnalysisConfig) -> pd.DataFrame:
    records = []
    for ticker, df in features.items():
        hits = df[df["is_event"]]
        for date, row in hits.iterrows():
            records.append(build_event_record(ticker, date, row, universe, cfg))
    columns = ["event_id", "ticker", "name", "sector", "date", "direction", "ret", "z_ret", "ret_median",
               "abnormal_ret", "z_abn", "beta", "mkt_ret", "z_mkt", "sector_index", "sector_ret", "z_sector",
               "peer_median_ret", "rel_peer_ret", "z_rel_peer", "volume", "volume_median", "volume_ratio",
               "z_volume", "vol_ratio", "vol_short_ann", "priority_score", "severity", "event_types",
               "triggers", "s_price", "s_abnormal", "s_volume", "s_regime"]
    events = pd.DataFrame(records, columns=columns)
    if events.empty:
        return events
    events["event_type"] = events["event_types"].apply(lambda t: " + ".join(t))
    events["event_type_short"] = events["event_types"].apply(
        lambda t: " + ".join(SHORT_TYPE.get(x, x) for x in t).capitalize())
    events["severity_rank"] = events["severity"].map(SEVERITY_ORDER)
    return events.sort_values(["date", "priority_score"], ascending=[False, False]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Universe scan
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    universe: Universe
    config: AnalysisConfig
    panel: Panel
    features: dict[str, pd.DataFrame]
    events: pd.DataFrame
    breadth: pd.Series
    excluded_dates: list = field(default_factory=list)
    missing_symbols: list = field(default_factory=list)

    @property
    def last_date(self) -> pd.Timestamp | None:
        return self.panel.calendar[-1] if len(self.panel.calendar) else None

    def event(self, event_id: str) -> dict | None:
        if self.events.empty:
            return None
        hit = self.events[self.events["event_id"] == event_id]
        return None if hit.empty else hit.iloc[0].to_dict()

    def market_context(self, date) -> dict:
        """Cross-sectional picture of one day across the whole watchlist."""
        date = pd.Timestamp(date)
        stocks = [t for t in self.universe.tickers if t in self.panel.returns.columns]
        if date not in self.panel.returns.index or not stocks:
            return {"available": False}
        day = self.panel.returns.loc[date, stocks].dropna()
        day_z = self.panel.zscores.loc[date, stocks].dropna()
        events_today = self.events[self.events["date"] == date] if not self.events.empty else self.events
        bench = self.universe.benchmark
        sectors = {}
        for sector, index_sym in self.universe.sector_indices.items():
            if index_sym in self.panel.returns.columns:
                sectors[sector] = {
                    "index": index_sym,
                    "name": self.universe.short_label(index_sym),
                    "ret": _num(self.panel.returns.loc[date, index_sym]),
                    "z": _num(self.panel.zscores.loc[date, index_sym]),
                }
        return {
            "available": True,
            "date": date,
            "n_stocks": int(len(day)),
            "share_up": float((day > 0).mean()) if len(day) else None,
            "share_down": float((day < 0).mean()) if len(day) else None,
            "median_ret": float(day.median()) if len(day) else None,
            "share_abs_z_above_2": float((day_z.abs() >= 2).mean()) if len(day_z) else None,
            "n_events": int(len(events_today)),
            "benchmark": bench,
            "benchmark_name": self.universe.short_label(bench),
            "benchmark_ret": _num(self.panel.returns.loc[date, bench]) if bench in self.panel.returns else None,
            "benchmark_z": _num(self.panel.zscores.loc[date, bench]) if bench in self.panel.zscores else None,
            "sectors": sectors,
        }


def scan_universe(frames: dict[str, pd.DataFrame], universe: Universe, cfg: AnalysisConfig,
                  drop_dates: list | None = None) -> ScanResult:
    panel = build_panel(frames, universe.benchmark, cfg, drop_dates=drop_dates)
    features = {}
    missing = []
    for ticker in universe.tickers:
        if panel.has(ticker):
            features[ticker] = compute_stock_features(ticker, panel, universe, cfg)
        else:
            missing.append(ticker)
    events = collect_events(features, universe, cfg)
    stocks = [t for t in universe.tickers if t in panel.returns.columns]
    if stocks:
        up = (panel.returns[stocks] > 0).sum(axis=1)
        total = panel.returns[stocks].notna().sum(axis=1)
        breadth = (up / total.where(total > 0)).rename("share_up")
    else:
        breadth = pd.Series(dtype=float)
    return ScanResult(universe=universe, config=cfg, panel=panel, features=features, events=events,
                      breadth=breadth, excluded_dates=list(drop_dates or []), missing_symbols=missing)


def threshold_sensitivity(scan: ScanResult, thresholds: list[float], start=None, end=None) -> pd.DataFrame:
    """How many stock-days would trigger at each threshold (same threshold for all three tests)."""
    rows = []
    for thr in thresholds:
        total = 0
        price_only = 0
        for df in scan.features.values():
            sub = df
            if start is not None:
                sub = sub[sub.index >= pd.Timestamp(start)]
            if end is not None:
                sub = sub[sub.index <= pd.Timestamp(end)]
            hit = (sub["z_ret"].abs() >= thr) | (sub["z_abn"].abs() >= thr) | (sub["z_volume"] >= thr)
            total += int(hit.sum())
            price_only += int((sub["z_ret"].abs() >= thr).sum())
        rows.append({"threshold": thr, "alerts_any_test": total, "alerts_price_test_only": price_only})
    return pd.DataFrame(rows)
