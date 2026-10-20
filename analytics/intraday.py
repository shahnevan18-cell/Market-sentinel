"""Intraday unusualness on 5-minute bars, judged against the same time of day in earlier sessions.

Why the same time of day: intraday volume and volatility follow a strong daily pattern (busy after the open and
before the close, quieter around midday), so a 09:15 bar and a 13:00 bar cannot share one yardstick. Each measure
of the latest complete bar is compared with the same bar of the day over up to 40 earlier sessions:

* 5-minute return: log change from the previous bar of the same session. The 09:15 bar is measured from the
  previous session's last bar, so its baseline also consists of opening bars with their overnight gaps.
* Return relative to NIFTY 50: stock return minus beta times the NIFTY 50 return of the same bar. Beta is
  estimated from the baseline sessions' 5-minute returns, opening bars excluded.
* Volume: log volume of the bar.

Robust z = (value - median) / (1.4826 x MAD) over the baseline values of that bar of the day. A bar is flagged when
|z| is 4 or more for either return measure, or z is 4 or more for volume. That is stricter than the daily tests:
26 symbols with 75 bars a session give about 2,000 comparisons a day, so a lower cut-off would flag chance
extremes every hour. A measure needs at least 15 baseline sessions with a value; with fewer it is shown for display
only and never flagged. Bars that are
still forming are excluded, missing bars are never filled, and missing volume is never treated as zero.

Intraday flags are prompts for review. They are separate from the daily alert priority, change no daily score and
start no investigation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from config.market import previous_trading_day
from providers.intraday import bars_per_session, complete

BASELINE_SESSIONS = 40
MIN_SESSIONS = 15
MIN_BETA_PAIRS = 300
Z_FLAG = 4.0          # stricter than the daily tests: each stock has 75 bars a session, so chance extremes are common
MAD_SCALE = 1.4826
THRESHOLDS = {"baseline_sessions": BASELINE_SESSIONS, "min_sessions": MIN_SESSIONS, "z_flag": Z_FLAG,
              "min_beta_pairs": MIN_BETA_PAIRS}


def bar_measures(frame: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Complete bars with their log return and log volume. A return is computed only from the immediately preceding
    bar (or, for the opening bar, the previous trading session's last bar); after a gap it stays missing."""
    df = complete(frame)[["close", "volume", "session", "slot"]].sort_index().copy()
    if df.empty:
        return df.assign(ret=pd.Series(dtype=float), log_vol=pd.Series(dtype=float))
    prev_close, prev_slot, prev_session = df["close"].shift(1), df["slot"].shift(1), df["session"].shift(1)
    last_slot = bars_per_session(minutes) - 1
    prior = {s: previous_trading_day(s).date() for s in df["session"].unique()}
    follows = (df["session"] == prev_session) & (df["slot"] == prev_slot + 1)
    opening = ((df["slot"] == 0) & (prev_slot == last_slot)
               & (prev_session == df["session"].map(prior)))
    df["ret"] = np.where(follows | opening, np.log(df["close"] / prev_close), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["log_vol"] = np.log(df["volume"].astype(float))
    return df


def _pivot(meas: pd.DataFrame, col: str) -> pd.DataFrame:
    if meas.empty:
        return pd.DataFrame()
    return meas.pivot_table(index="session", columns="slot", values=col, aggfunc="last", dropna=False)


def same_slot_z(pivot: pd.DataFrame, session: date) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(z, baseline count, baseline median) for every bar of the day of `session`; z is NaN where the baseline is
    too short or has no spread."""
    if pivot.empty or session not in pivot.index:
        empty = pd.Series(dtype=float)
        return empty, empty, empty
    base = pivot[pivot.index < session].tail(BASELINE_SESSIONS)
    med = base.median()
    mad = (base - med).abs().median()
    n = base.count()
    z = (pivot.loc[session] - med) / (MAD_SCALE * mad)
    z[(n < MIN_SESSIONS) | ~(mad > 0)] = np.nan
    return z, n, med


def intraday_beta(stock: pd.DataFrame, bench: pd.DataFrame, session: date) -> tuple[float | None, int]:
    """Beta of the stock's 5-minute returns on NIFTY 50's over the baseline sessions (opening bars excluded)."""
    sessions = sorted(s for s in set(stock["session"]) & set(bench["session"]) if s < session)[-BASELINE_SESSIONS:]
    keep = set(sessions)
    s = stock[stock["session"].isin(keep) & (stock["slot"] > 0)]["ret"]
    b = bench[bench["session"].isin(keep) & (bench["slot"] > 0)]["ret"]
    j = pd.concat([s.rename("s"), b.rename("b")], axis=1, join="inner").dropna()
    if len(j) < MIN_BETA_PAIRS or not j["b"].var() > 0:
        return None, len(j)
    return float(np.clip(j["s"].cov(j["b"]) / j["b"].var(), -1.0, 3.0)), len(j)


@dataclass
class IntradayScan:
    session: date | None
    rows: pd.DataFrame
    benchmark_bars: pd.DataFrame          # every bar of the session for the benchmark, forming bar included
    benchmark_prev_close: float | None
    minutes: int
    thresholds: dict = field(default_factory=lambda: dict(THRESHOLDS))
    notes: list[str] = field(default_factory=list)

    @property
    def flagged(self) -> pd.DataFrame:
        return self.rows[self.rows["flagged"]] if len(self.rows) else self.rows


def _num(x) -> float | None:
    return None if x is None or pd.isna(x) else float(x)


def _fmt_z(z: float) -> str:
    return f"{z:+.1f}"


def scan_intraday(history: dict[str, pd.DataFrame], benchmark: str, minutes: int,
                  names: dict[str, str] | None = None) -> IntradayScan:
    names = names or {}
    bench_frame = history.get(benchmark)
    candidates = [bench_frame] if bench_frame is not None and len(complete(bench_frame)) else \
        [f for f in history.values() if len(complete(f))]
    if not candidates:
        return IntradayScan(None, pd.DataFrame(), pd.DataFrame(), None, minutes,
                            notes=["No complete intraday bars are available."])
    session = max(max(complete(f)["session"]) for f in candidates)
    bench_meas = bar_measures(bench_frame, minutes) if bench_frame is not None else pd.DataFrame()
    bench_latest_slot = None
    if len(bench_meas):
        in_sess = bench_meas[bench_meas["session"] == session]
        bench_latest_slot = int(in_sess["slot"].max()) if len(in_sess) else None

    rows = []
    for sym, frame in history.items():
        meas = bar_measures(frame, minutes)
        today = meas[meas["session"] == session]
        forming = frame[(frame["session"] == session) & frame["partial"].astype(bool)] if len(frame) else frame
        row = {"symbol": sym, "name": names.get(sym, sym), "is_benchmark": sym == benchmark,
               "partial_excluded": bool(len(forming)), "flagged": False, "reasons": "", "note": ""}
        if today.empty:
            row["note"] = "No complete bar in this session yet." if len(forming) else "No bars for this session."
            rows.append(row)
            continue
        last = today.iloc[-1]
        k = int(last["slot"])
        prev = meas[meas["session"] < session]
        prev_close = float(prev["close"].iloc[-1]) if len(prev) else None
        row.update({"last_close": float(last["close"]), "bar_time": today.index[-1],
                    "bar_return": _num(np.expm1(last["ret"])) if pd.notna(last["ret"]) else None,
                    "change_today": (float(last["close"]) / prev_close - 1) if prev_close else None})
        z_ret, n_ret, _ = same_slot_z(_pivot(meas, "ret"), session)
        row["z_return"] = _num(z_ret.get(k))
        row["n_sessions"] = int(n_ret.get(k, 0)) if len(n_ret) else 0
        valid = z_ret.dropna()
        if len(valid):
            peak = valid.abs().idxmax()
            row["today_peak_z"] = float(valid[peak])
            row["today_peak_time"] = today.index[today["slot"] == peak][0] if (today["slot"] == peak).any() else None
        if sym != benchmark:
            z_vol, n_vol, med_vol = same_slot_z(_pivot(meas, "log_vol"), session)
            row["z_volume"] = _num(z_vol.get(k))
            if pd.notna(last["log_vol"]) and k in med_vol.index and pd.notna(med_vol.get(k)):
                row["volume_ratio"] = float(np.exp(last["log_vol"] - med_vol[k]))
            if len(bench_meas):
                beta, pairs = intraday_beta(meas, bench_meas, session)
                row["beta"] = beta
                if beta is not None:
                    joint = meas[["ret", "session", "slot"]].join(bench_meas[["ret"]].rename(columns={"ret": "bret"}),
                                                                  how="inner")
                    joint["rel"] = joint["ret"] - beta * joint["bret"]
                    z_rel, _, _ = same_slot_z(_pivot(joint, "rel"), session)
                    row["z_relative"] = _num(z_rel.get(k))
            if bench_latest_slot is not None:
                row["bars_behind"] = max(0, bench_latest_slot - k)
        reasons = []
        zr, zrel, zv = row.get("z_return"), row.get("z_relative"), row.get("z_volume")
        if zr is not None and abs(zr) >= Z_FLAG:
            reasons.append(f"5-minute return {row['bar_return'] * 100:+.2f}% (z {_fmt_z(zr)} for this time of day)")
        if zrel is not None and abs(zrel) >= Z_FLAG:
            reasons.append(f"move relative to NIFTY 50 (z {_fmt_z(zrel)})")
        if zv is not None and zv >= Z_FLAG:
            ratio = row.get("volume_ratio")
            lead = f"volume {ratio:.1f} times usual for this time" if ratio else "volume high for this time"
            reasons.append(f"{lead} (z {_fmt_z(zv)})")
        row["flagged"] = bool(reasons)
        row["reasons"] = "; ".join(reasons)
        if all(row.get(c) is None for c in ("z_return", "z_relative", "z_volume")):
            have = row["n_sessions"]
            row["note"] = (f"Display only: {have} earlier session(s) have this bar of the day; {MIN_SESSIONS} are "
                           "needed for a baseline.")
        elif row.get("bars_behind"):
            row["note"] = f"Latest bar is {row['bars_behind']} bar(s) behind NIFTY 50 (missing bars are not filled)."
        rows.append(row)
    out = pd.DataFrame(rows)
    for col in ("z_return", "z_relative", "z_volume", "today_peak_z", "bar_return", "change_today", "last_close",
                "volume_ratio", "beta", "n_sessions", "bars_behind"):
        out[col] = pd.to_numeric(out[col], errors="coerce") if col in out.columns else np.nan
    out["max_abs_z"] = out[["z_return", "z_relative", "z_volume"]].abs().max(axis=1, skipna=True)
    out = out.sort_values(["is_benchmark", "flagged", "max_abs_z"], ascending=[False, False, False],
                          na_position="last").reset_index(drop=True)
    bench_bars = bench_frame[bench_frame["session"] == session] if bench_frame is not None else pd.DataFrame()
    bench_prev = None
    if len(bench_meas):
        before = bench_meas[bench_meas["session"] < session]
        bench_prev = float(before["close"].iloc[-1]) if len(before) else None
    notes = []
    if bench_frame is None:
        notes.append("NIFTY 50 bars are missing, so relative moves cannot be measured.")
    return IntradayScan(session, out, bench_bars, bench_prev, minutes, notes=notes)
