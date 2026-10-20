"""Synthetic 5-minute bars and a scripted fetcher for the intraday tests.

Everything here is generated test data with a fixed seed. It exists only for tests and is never shown in the app
as market data.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config.market import MARKET_TZ, trading_days
from providers.intraday import FetchOutcome, INTERVAL_MINUTES, normalise_intraday

SESSIONS = trading_days("2026-08-03", "2026-10-23")


def u_shape(k: int) -> float:
    """Intraday activity pattern: busy after the open and before the close."""
    return 1.0 + 1.5 * np.exp(-k / 6) + 0.8 * np.exp(-(74 - k) / 6)


def synth_raw(seed: int, *, index: bool = False, shocks: dict | None = None, market: pd.Series | None = None,
              beta: float = 1.0, vol_shocks: dict | None = None, noise: float = 0.0010,
              vol_sd: float = 0.25) -> pd.DataFrame:
    """Yahoo-shaped frame (Open/High/Low/Close/Volume, IST index) covering SESSIONS. `shocks` and `vol_shocks`
    map (session date, slot) to an added log return or a volume multiple; `market` adds beta times a market path."""
    rng = np.random.default_rng(seed)
    rows, price = [], 1000.0
    for d in SESSIONS:
        for k in range(75):
            t = pd.Timestamp(datetime.combine(d.date(), datetime.min.time()), tz=MARKET_TZ) + pd.Timedelta(
                hours=9, minutes=15 + 5 * k)
            r = rng.normal(0, noise * u_shape(k))
            if market is not None:
                r += beta * float(market.get(t, 0.0))
            r += (shocks or {}).get((d.date(), k), 0.0)
            o = price
            price = price * np.exp(r)
            vol = 0.0 if index else rng.lognormal(np.log(40_000 * u_shape(k)), vol_sd) * (vol_shocks or {}).get(
                (d.date(), k), 1.0)
            rows.append((t, o, max(o, price), min(o, price), price, vol))
    return pd.DataFrame(rows, columns=["t", "Open", "High", "Low", "Close", "Volume"]).set_index("t")


def market_path(seed: int = 99) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = []
    for d in SESSIONS:
        base = pd.Timestamp(datetime.combine(d.date(), datetime.min.time()), tz=MARKET_TZ)
        idx += [base + pd.Timedelta(hours=9, minutes=15 + 5 * k) for k in range(75)]
    return pd.Series(rng.normal(0, 0.0008, len(idx)), index=pd.DatetimeIndex(idx))


class Clock:
    def __init__(self, ist: str):
        self.now = pd.Timestamp(ist, tz=MARKET_TZ).tz_convert("UTC").to_pydatetime()

    def set(self, ist: str) -> None:
        self.now = pd.Timestamp(ist, tz=MARKET_TZ).tz_convert("UTC").to_pydatetime()

    def __call__(self) -> datetime:
        return self.now


class FakeFetcher:
    """Serves the synthetic frames as Yahoo would at the clock's time: bars that have started, the current one
    still forming, the period trimmed to the last 5 or 60 calendar days. Every call is recorded."""

    label = "Synthetic test bars"

    def __init__(self, raw: dict[str, pd.DataFrame], clock: Clock, fail: set | None = None, delay: float = 0.0):
        self.raw, self.clock, self.fail, self.delay = raw, clock, set(fail or ()), delay
        self.calls: list[tuple[tuple, str]] = []
        self._lock = threading.Lock()

    def fetch(self, symbols, *, period, interval):
        with self._lock:
            self.calls.append((tuple(symbols), period))
        if self.delay:
            time.sleep(self.delay)
        now = self.clock()
        now_ist = pd.Timestamp(now).tz_convert(MARKET_TZ)
        days = int(period.rstrip("d"))
        out = FetchOutcome({}, {}, {}, now, now, period, interval)
        for sym in symbols:
            if sym in self.fail or sym not in self.raw:
                out.failures[sym] = "Simulated provider error" if sym in self.fail else "Unknown symbol"
                continue
            raw = self.raw[sym]
            visible = raw[(raw.index <= now_ist) & (raw.index > now_ist - pd.Timedelta(days=days))]
            frame, notes = normalise_intraday(visible, INTERVAL_MINUTES[interval], now, is_index=sym.startswith("^"))
            out.notes[sym] = notes
            if frame.empty:
                out.failures[sym] = "Provider returned no intraday rows."
            else:
                out.frames[sym] = frame
        out.received_at = now
        return out


def utc(ist: str) -> datetime:
    return pd.Timestamp(ist, tz=MARKET_TZ).tz_convert(timezone.utc).to_pydatetime()
