"""Benchmark, sector and peer comparisons for a single event.

These functions read the feature frames produced by anomaly_detection, so the
same numbers appear in the monitor, the investigation tools and the report.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from analytics.anomaly_detection import ScanResult, robust_z, rolling_prior_median_mad


def _num(x):
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def feature_row(scan: ScanResult, ticker: str, date) -> pd.Series | None:
    df = scan.features.get(ticker)
    date = pd.Timestamp(date)
    if df is None or date not in df.index:
        return None
    return df.loc[date]


def calendar_position(scan: ScanResult, date) -> int | None:
    date = pd.Timestamp(date)
    cal = scan.panel.calendar
    if date not in cal:
        return None
    return int(cal.get_loc(date))


def benchmark_comparison(scan: ScanResult, ticker: str, date) -> dict:
    row = feature_row(scan, ticker, date)
    cfg = scan.config
    bench = scan.universe.benchmark
    if row is None:
        return {"available": False, "reason": f"No feature data for {ticker} on {pd.Timestamp(date):%Y-%m-%d}."}
    pos = calendar_position(scan, date)
    cal = scan.panel.calendar
    est_end = cal[pos - 1] if pos and pos >= 1 else None
    est_start = cal[max(0, pos - cfg.beta_window)] if pos else None
    beta = _num(row["beta"])
    ret = _num(row["ret"])
    expected = _num(row["expected_ret"])
    notes = []
    if beta is None:
        notes.append(f"Beta could not be estimated: fewer than {cfg.beta_min_obs} paired observations "
                     f"in the {cfg.beta_window}-day window or benchmark data missing.")
    r2 = _num(row["r2"])
    if r2 is not None and r2 < 0.10:
        notes.append(f"The market model explains little of this stock's daily variation (R-squared {r2:.2f}), "
                     "so the market-adjusted return should be read with caution.")
    explained = None
    if expected is not None and ret not in (None, 0.0):
        explained = expected / ret
    return {
        "available": beta is not None,
        "benchmark": bench,
        "benchmark_name": scan.universe.short_label(bench),
        "estimation_window_start": None if est_start is None else f"{est_start:%Y-%m-%d}",
        "estimation_window_end": None if est_end is None else f"{est_end:%Y-%m-%d}",
        "estimation_obs": _num(row["beta_n"]),
        "beta": beta,
        "alpha_daily": _num(row["alpha"]),
        "r_squared": r2,
        "residual_sd": _num(row["resid_sd"]),
        "stock_return": ret,
        "benchmark_return": _num(row["mkt_ret"]),
        "benchmark_z": _num(row["z_mkt"]),
        "expected_return": expected,
        "abnormal_return": _num(row["abnormal_ret"]),
        "abnormal_z": _num(row["z_abn"]),
        "market_explained_ratio": explained,
        "notes": notes,
    }


def _relative_z(scan: ScanResult, ticker: str, peers: list[str], date) -> tuple[float | None, float | None, float | None]:
    """Relative return versus the median of a custom peer list, with a robust z from prior days."""
    r = scan.panel.returns[ticker]
    peer_r = scan.panel.returns[peers]
    count = peer_r.notna().sum(axis=1)
    med = peer_r.median(axis=1, skipna=True).where(count > 0)
    rel = r - med
    cfg = scan.config
    m, mad, _ = rolling_prior_median_mad(rel, cfg.lookback, cfg.min_obs)
    z = robust_z(rel, m, mad)
    date = pd.Timestamp(date)
    return _num(med.get(date)), _num(rel.get(date)), _num(z.get(date))


def peer_comparison(scan: ScanResult, ticker: str, date, peers: list[str] | None = None) -> dict:
    date = pd.Timestamp(date)
    universe = scan.universe
    row = feature_row(scan, ticker, date)
    if row is None:
        return {"available": False, "reason": f"No feature data for {ticker} on {date:%Y-%m-%d}."}
    configured = universe.peers_of(ticker)
    requested = peers if peers else configured
    usable = [p for p in requested if p != ticker and scan.panel.has(p)]
    rejected = [p for p in requested if p not in usable and p != ticker]
    stock_ret = _num(row["ret"])
    peer_rows = []
    for p in usable:
        pr = _num(scan.panel.returns.loc[date, p]) if date in scan.panel.returns.index else None
        pz = _num(scan.panel.zscores.loc[date, p]) if date in scan.panel.zscores.index else None
        peer_rows.append({"ticker": p, "name": universe.display_name(p), "return": pr, "robust_z": pz})
    valid = [r for r in peer_rows if r["return"] is not None]
    if stock_ret is not None and valid:
        sign = np.sign(stock_ret)
        same = [r for r in valid if np.sign(r["return"]) == sign]
        strong = [r for r in same if r["robust_z"] is not None and abs(r["robust_z"]) >= 2]
        share_same = len(same) / len(valid)
        share_strong = len(strong) / len(valid)
    else:
        share_same = share_strong = None
    if peers and usable:
        peer_median, rel, z_rel = _relative_z(scan, ticker, usable, date)
    else:
        peer_median, rel, z_rel = _num(row["peer_median_ret"]), _num(row["rel_peer_ret"]), _num(row["z_rel_peer"])
    index_sym = universe.sector_index_for(ticker)
    index_name = universe.short_label(index_sym) if index_sym else None
    notes = []
    if not configured and not peers:
        notes.append("No other stock in the watchlist belongs to this peer group, so no peer comparison was made.")
    elif not usable:
        notes.append("No peer data available; the peer comparison could not be made.")
    elif len(valid) < 3:
        notes.append(f"Only {len(valid)} peer(s) with data on this date, so the peer median is a weak reference.")
    if rejected:
        notes.append("Ignored symbols without data in the monitored universe: " + ", ".join(rejected))
    if index_sym:
        notes.append(f"{index_name} is weighted by free-float market capitalisation, so large constituents "
                     f"(possibly {universe.short_label(ticker)} itself) influence their own sector index.")
    else:
        notes.append("No sector index is configured for this peer group, so no separate sector-index comparison "
                     "was performed; the comparison uses peers only.")
    return {
        "available": bool(usable),
        "ticker": ticker,
        "date": f"{date:%Y-%m-%d}",
        "stock_return": stock_ret,
        "stock_z": _num(row["z_ret"]),
        "peers_source": "requested" if peers else "configured (same peer group in the watchlist)",
        "peers": peer_rows,
        "n_peers": len(valid),
        "peer_median_return": peer_median,
        "relative_return": rel,
        "relative_z": z_rel,
        "share_same_direction": share_same,
        "share_same_direction_z2": share_strong,
        "sector_index": index_sym,
        "sector_index_name": index_name,
        "sector_index_return": _num(row["sector_ret"]),
        "sector_index_z": _num(row["z_sector"]),
        "notes": notes,
    }


def price_volume_history(scan: ScanResult, ticker: str, date, days: int = 15) -> dict:
    df = scan.features.get(ticker)
    date = pd.Timestamp(date)
    if df is None or date not in df.index:
        return {"available": False, "reason": f"No data for {ticker} on {date:%Y-%m-%d}."}
    pos = df.index.get_loc(date)
    window = df.iloc[max(0, pos - days + 1): pos + 1]
    rows = []
    for d, r in window.iterrows():
        rows.append({
            "date": f"{d:%Y-%m-%d}",
            "adj_close": _num(r["close"]),
            "return": _num(r["ret"]),
            "robust_z": _num(r["z_ret"]),
            "volume": _num(r["volume"]),
            "volume_ratio": _num(r["volume_ratio"]),
        })
    full = df.iloc[: pos + 1]
    ret = full["ret"].dropna()
    return {
        "available": True,
        "ticker": ticker,
        "as_of": f"{date:%Y-%m-%d}",
        "observations_available": int(full["close"].notna().sum()),
        "first_date": f"{full.index[0]:%Y-%m-%d}",
        "rows": rows,
        "return_5d_before_event": _num((1 + ret.iloc[-6:-1]).prod() - 1) if len(ret) >= 6 else None,
        "return_20d_before_event": _num((1 + ret.iloc[-21:-1]).prod() - 1) if len(ret) >= 21 else None,
        "event_day_return": _num(df.loc[date, "ret"]),
    }


def returns_and_volatility(scan: ScanResult, ticker: str, date) -> dict:
    row = feature_row(scan, ticker, date)
    cfg = scan.config
    if row is None:
        return {"available": False, "reason": "No data for that date."}
    return {
        "available": True,
        "ticker": ticker,
        "date": f"{pd.Timestamp(date):%Y-%m-%d}",
        "simple_return": _num(row["ret"]),
        "log_return": _num(row["log_ret"]),
        "baseline_window_days": cfg.lookback,
        "baseline_observations": _num(row["baseline_n"]),
        "baseline_median_return": _num(row["ret_median"]),
        "baseline_mad": _num(row["ret_mad"]),
        "robust_z_return": _num(row["z_ret"]),
        "vol_recent_10d_annualised": _num(row["vol_short_ann"]),
        "vol_prior_60d_annualised": _num(row["vol_long_ann"]),
        "vol_regime_ratio": _num(row["vol_ratio"]),
        "volatility_note": "Historical (realised) volatility of daily returns, annualised with sqrt(252). "
                           "It describes the past window and is not a forecast.",
    }


def abnormal_volume(scan: ScanResult, ticker: str, date) -> dict:
    df = scan.features.get(ticker)
    date = pd.Timestamp(date)
    row = feature_row(scan, ticker, date)
    cfg = scan.config
    if row is None:
        return {"available": False, "reason": "No data for that date."}
    pos = df.index.get_loc(date)
    recent = df["volume_ratio"].iloc[max(0, pos - 4): pos + 1]
    vol = _num(row["volume"])
    notes = []
    if vol is None or vol <= 0:
        notes.append("Volume is missing or zero on the event day, so abnormal volume cannot be assessed.")
    return {
        "available": vol is not None and vol > 0,
        "ticker": ticker,
        "date": f"{date:%Y-%m-%d}",
        "volume": vol,
        "baseline_median_volume": _num(row["volume_median"]),
        "volume_ratio": _num(row["volume_ratio"]),
        "robust_z_log_volume": _num(row["z_volume"]),
        "threshold": cfg.z_volume,
        "last_5_days_volume_ratio": [None if pd.isna(v) else round(float(v), 2) for v in recent],
        "notes": notes,
    }


def car_window(scan: ScanResult, ticker: str, date, pre: int = 5, post: int = 20) -> pd.DataFrame:
    """Cumulative abnormal return path around an event, using alpha and beta frozen at the event date.

    Values after the event date are retrospective observations (they were not
    known on the event date) and are used only for evaluation.
    """
    df = scan.features.get(ticker)
    date = pd.Timestamp(date)
    if df is None or date not in df.index:
        return pd.DataFrame()
    pos = df.index.get_loc(date)
    alpha = df.loc[date, "alpha"]
    beta = df.loc[date, "beta"]
    if pd.isna(beta):
        return pd.DataFrame()
    lo = max(0, pos - pre)
    hi = min(len(df) - 1, pos + post)
    seg = df.iloc[lo: hi + 1]
    ar = seg["ret"] - (alpha + beta * seg["mkt_ret"])
    rel = np.arange(lo - pos, hi - pos + 1)
    out = pd.DataFrame({"rel_day": rel, "date": seg.index, "ret": seg["ret"].values, "ar": ar.values})
    out["car_from_pre"] = out["ar"].fillna(0).cumsum()
    post_mask = out["rel_day"] > 0
    out["car_after_event"] = np.where(post_mask, out["ar"].where(post_mask).fillna(0).cumsum(), np.nan)
    return out


def safe_float(x) -> float | None:
    v = _num(x)
    if v is None or math.isinf(v):
        return None
    return v
