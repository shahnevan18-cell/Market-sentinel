"""Market data providers, cache and the demonstration dataset.

Providers share one small interface (`fetch`) so the source can be swapped
without touching the analytics:

* YFinanceProvider: the yfinance library, an unofficial open-source client
  for publicly available Yahoo Finance data (NSE symbols end in ".NS"). It is
  not an official Yahoo or NSE feed, data can be delayed, and Yahoo may
  throttle or change it without notice. Each result carries the currency,
  exchange and time zone Yahoo reports, which the data-quality checks validate.
* Demo data: a deterministic synthetic dataset of fictional India-themed
  ".DEMO" securities. It is only used when the user explicitly selects
  demonstration mode and is never substituted for real prices.

The US-only Tiingo provider of the earlier version was removed: it does not
cover NSE-listed shares.

Every fetched series is cached on disk with its original retrieval time. If a
later fetch fails, the cached copy is used and marked as stale.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from analytics.data_quality import QualityReport, check_frame, clean_frame
from config.market import (CURRENCY, MARKET_TZ, TZ_NAME, expected_latest_session, is_partial_session,
                           sessions_between, trading_days_ending)
from config.settings import CACHE_DIR, Settings
from config.watchlist import DEMO_UNIVERSE, Universe

STANDARD_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume", "dividends", "splits"]
DEMO_END_DATE = "2026-09-30"
DEMO_SESSIONS = 520


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(ts: datetime | None) -> str | None:
    return None if ts is None else ts.astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


@dataclass
class SymbolMeta:
    symbol: str
    provider: str
    status: str                       # live | cache | cache-stale | demo | unavailable
    retrieved_at: str | None = None   # ISO UTC time the provider returned this data
    currency: str | None = None
    exchange: str | None = None
    timezone: str | None = None
    instrument_type: str | None = None
    first_date: str | None = None
    last_date: str | None = None
    partial_last_bar: bool = False
    note: str = ""
    requested_start: str | None = None   # start date requested from the provider (for cache coverage checks)


@dataclass
class FetchResult:
    frames: dict[str, pd.DataFrame] = field(default_factory=dict)
    meta: dict[str, dict] = field(default_factory=dict)
    failures: dict[str, str] = field(default_factory=dict)
    retrieved_at: datetime = field(default_factory=utcnow)


class MarketDataProvider:
    key = "base"
    label = "Base provider"

    def fetch(self, symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> FetchResult:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# yfinance
# ---------------------------------------------------------------------------

YF_RENAME = {
    "Open": "open", "High": "high", "Low": "low", "Close": "close", "Adj Close": "adj_close",
    "Volume": "volume", "Dividends": "dividends", "Stock Splits": "splits",
}


def normalise_ohlcv(df: pd.DataFrame, rename: dict | None = None, tz=None) -> pd.DataFrame:
    """Return a frame with STANDARD_COLUMNS and a tz-naive, date-only index named 'date'.

    Yahoo stamps NSE daily bars at midnight India time (for example 2026-10-19 00:00+05:30). The date must be
    read in the exchange's own time zone: converting that stamp to New York time, as the US version did, moves
    every Indian bar to the previous calendar day.
    """
    out = df.rename(columns=rename or YF_RENAME).copy()
    idx = pd.DatetimeIndex(out.index)
    if idx.tz is not None:
        idx = idx.tz_convert(tz or MARKET_TZ).tz_localize(None)
    out.index = idx.normalize()
    out.index.name = "date"
    if "adj_close" not in out.columns and "close" in out.columns:
        out["adj_close"] = out["close"]
    for col in STANDARD_COLUMNS:
        if col not in out.columns:
            out[col] = 0.0 if col in ("dividends", "splits") else np.nan
    out = out[STANDARD_COLUMNS].apply(pd.to_numeric, errors="coerce").astype(float)
    return out


def _zone(name: str | None):
    """ZoneInfo for a provider time-zone name, falling back to India time."""
    if not name:
        return MARKET_TZ
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return MARKET_TZ


class _Throttle:
    def __init__(self, seconds: float):
        self.seconds = seconds
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            gap = time.monotonic() - self._last
            if gap < self.seconds:
                time.sleep(self.seconds - gap)
            self._last = time.monotonic()


class YFinanceProvider(MarketDataProvider):
    key = "yfinance"
    label = "Yahoo Finance via yfinance (unofficial, possibly delayed)"

    def __init__(self, timeout: float = 15.0, max_retries: int = 2, throttle: float = 0.35, max_workers: int = 3):
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_workers = max_workers
        self._throttle = _Throttle(throttle)
        self._rate_limited = threading.Event()
        self._unreachable = threading.Event()
        self._lock = threading.Lock()
        self._conn_failures = 0
        self._successes = 0
        self.progress_callback = None   # optional: called as (done, total, symbol, error) from the main thread

    @staticmethod
    def _is_connection_error(message: str) -> bool:
        m = message.lower()
        return any(k in m for k in ("connectionerror", "curl: (", "timed out", "timeout", "name resolution",
                                    "failed to establish", "connection refused", "proxy"))

    def _note_result(self, ok: bool, message: str = "") -> None:
        with self._lock:
            if ok:
                self._successes += 1
            elif self._is_connection_error(message):
                self._conn_failures += 1
                if self._conn_failures >= 4 and self._successes == 0:
                    self._unreachable.set()

    def _fetch_one(self, symbol: str, start: pd.Timestamp, end: pd.Timestamp):
        import yfinance as yf
        try:
            yf.config.debug.hide_exceptions = False  # surface real errors instead of silent empty frames
        except Exception:  # older yfinance versions
            pass
        rate_limit_error = getattr(getattr(yf, "exceptions", None), "YFRateLimitError", None)
        last_error = "unknown error"
        for attempt in range(self.max_retries + 1):
            if self._rate_limited.is_set():
                return None, None, "Skipped: Yahoo Finance rate-limited an earlier request in this run."
            if self._unreachable.is_set():
                return None, None, ("Skipped: Yahoo Finance was unreachable (the first requests failed with "
                                    "connection errors).")
            self._throttle.wait()
            try:
                ticker = yf.Ticker(symbol)
                raw = ticker.history(start=f"{start:%Y-%m-%d}", end=f"{end:%Y-%m-%d}", interval="1d",
                                     auto_adjust=False, actions=True, timeout=self.timeout)
                if raw is None or raw.empty:
                    self._note_result(False, "empty")
                    return None, None, "Provider returned no rows (symbol may be invalid or delisted)."
                self._note_result(True)
                meta = {}
                try:
                    meta = dict(ticker.history_metadata or {})
                except Exception:
                    meta = {}
                return normalise_ohlcv(raw, tz=_zone(meta.get("exchangeTimezoneName"))), meta, None
            except Exception as exc:  # noqa: BLE001 - provider errors are reported, not raised
                if rate_limit_error is not None and isinstance(exc, rate_limit_error):
                    self._rate_limited.set()
                    return None, None, "Rate limited by Yahoo Finance (too many requests). Try again later."
                last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                if "No data found" in str(exc) or "delisted" in str(exc).lower():
                    return None, None, last_error
                if self._is_connection_error(last_error):
                    self._note_result(False, last_error)
                    if attempt >= 1 or self._unreachable.is_set():
                        return None, None, last_error
                time.sleep(0.6 * (2 ** attempt))
        return None, None, last_error

    def fetch(self, symbols, start, end) -> FetchResult:
        result = FetchResult()
        self._rate_limited.clear()
        self._unreachable.clear()
        self._conn_failures = 0
        self._successes = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {sym: pool.submit(self._fetch_one, sym, start, end) for sym in symbols}
            for i, (sym, fut) in enumerate(futures.items(), start=1):
                frame, meta, error = fut.result()
                if self.progress_callback is not None:
                    try:
                        self.progress_callback(i, len(futures), sym, error)
                    except Exception:
                        pass
                if error or frame is None:
                    result.failures[sym] = error or "No data returned."
                    continue
                result.frames[sym] = frame
                result.meta[sym] = {
                    "currency": meta.get("currency"),
                    "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
                    "timezone": meta.get("exchangeTimezoneName"),
                    "instrument_type": meta.get("instrumentType"),
                }
        result.retrieved_at = utcnow()
        return result


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------

def _safe_name(symbol: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", symbol)


class MarketCache:
    def __init__(self, provider_key: str, root: Path | None = None):
        self.dir = (root or CACHE_DIR) / "market" / provider_key
        self.manifest_path = self.dir / "manifest.json"

    def _manifest(self) -> dict:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def read(self, symbol: str) -> tuple[pd.DataFrame, dict] | None:
        path = self.dir / f"{_safe_name(symbol)}.csv"
        meta = self._manifest().get(symbol)
        if not path.exists() or not meta:
            return None
        try:
            df = pd.read_csv(path, index_col="date", parse_dates=["date"])
        except Exception:
            return None
        if df.empty:
            return None
        return normalise_ohlcv(df, rename={}), meta

    def write(self, symbol: str, df: pd.DataFrame, meta: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self.dir / f"{_safe_name(symbol)}.csv"
        tmp = path.with_suffix(".tmp")
        df.to_csv(tmp, index_label="date")
        tmp.replace(path)
        manifest = self._manifest()
        manifest[symbol] = meta
        tmp_m = self.manifest_path.with_suffix(".tmp")
        tmp_m.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        tmp_m.replace(self.manifest_path)

    def clear(self) -> int:
        removed = 0
        if self.dir.exists():
            for p in self.dir.iterdir():
                if p.is_file():
                    p.unlink()
                    removed += 1
        return removed


# ---------------------------------------------------------------------------
# Dataset returned to the app
# ---------------------------------------------------------------------------

@dataclass
class MarketDataset:
    frames: dict[str, pd.DataFrame]
    meta: dict[str, SymbolMeta]
    universe: Universe
    mode: str                                   # live | demo
    provider_label: str
    loaded_at: str
    failures: dict[str, str] = field(default_factory=dict)
    quality: dict[str, QualityReport] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    as_of: str | None = None                    # set when truncated for a historical investigation

    @property
    def is_demo(self) -> bool:
        return self.mode == "demo"

    @property
    def symbols(self) -> list[str]:
        return list(self.frames)

    def latest_bar(self, symbol: str | None = None) -> pd.Timestamp | None:
        sym = symbol or self.universe.benchmark
        frame = self.frames.get(sym)
        if frame is None or frame.empty:
            dates = [f.index[-1] for f in self.frames.values() if not f.empty]
            return max(dates) if dates else None
        return frame.index[-1]

    def partial_dates(self) -> list[pd.Timestamp]:
        dates = set()
        for sym, m in self.meta.items():
            if m.partial_last_bar and m.last_date:
                dates.add(pd.Timestamp(m.last_date))
        return sorted(dates)

    def latest_complete_bar(self) -> pd.Timestamp | None:
        """Latest session whose bar was complete when retrieved (the last session the analysis uses)."""
        latest = self.latest_bar()
        if latest is None or latest not in set(self.partial_dates()):
            return latest
        frame = self.frames.get(self.universe.benchmark)
        index = frame.index if frame is not None and not frame.empty else pd.DatetimeIndex(
            sorted({d for f in self.frames.values() for d in f.index}))
        earlier = index[index < latest]
        return earlier[-1] if len(earlier) else None

    def truncated(self, date) -> "MarketDataset":
        """Copy containing only rows up to and including `date` (used for as-of investigations)."""
        cutoff = pd.Timestamp(date)
        frames = {s: f.loc[:cutoff] for s, f in self.frames.items()}
        frames = {s: f for s, f in frames.items() if not f.empty}
        meta = {}
        for s, m in self.meta.items():
            if s in frames:
                meta[s] = replace(m, last_date=f"{frames[s].index[-1]:%Y-%m-%d}", partial_last_bar=False)
        return replace(self, frames=frames, meta=meta, as_of=f"{cutoff:%Y-%m-%d}",
                       notes=self.notes + [f"Data truncated at {cutoff:%Y-%m-%d} for an as-of investigation."])

    def freshness(self, now: datetime | None = None) -> dict:
        now = now or utcnow()
        statuses: dict[str, int] = {}
        for m in self.meta.values():
            statuses[m.status] = statuses.get(m.status, 0) + 1
        retrieved = [parse_iso(m.retrieved_at) for m in self.meta.values() if m.retrieved_at]
        retrieved = [r for r in retrieved if r]
        latest = self.latest_complete_bar()
        newest = self.latest_bar()
        partial_bar = newest if (newest is not None and latest is not None and newest > latest) else None
        expected = None if self.is_demo else expected_latest_session(now)
        lag = None if (self.is_demo or latest is None) else sessions_between(latest, expected)
        stale_symbols = [s for s, m in self.meta.items() if m.status == "cache-stale"]
        currencies = sorted({(m.currency or "unknown") for s, m in self.meta.items()})
        return {
            "mode": self.mode,
            "provider": self.provider_label,
            "latest_bar": None if latest is None else f"{latest:%Y-%m-%d}",
            "partial_bar": None if partial_bar is None else f"{partial_bar:%Y-%m-%d}",
            "expected_session": None if expected is None else f"{expected:%Y-%m-%d}",
            "session_lag": lag,
            "currencies": currencies,
            "oldest_retrieval": iso(min(retrieved)) if retrieved else None,
            "newest_retrieval": iso(max(retrieved)) if retrieved else None,
            "loaded_at": self.loaded_at,
            "status_counts": statuses,
            "stale_symbols": stale_symbols,
            "failed_symbols": dict(self.failures),
            "partial_dates": [f"{d:%Y-%m-%d}" for d in self.partial_dates()],
            "is_stale": bool(stale_symbols) or (lag is not None and lag >= 2),
        }


def _attach_quality(ds: MarketDataset, cfg_min_required: int, large_gap: float, actions: dict[str, list[str]]):
    """Data-quality report per symbol. Every live symbol is checked against the universe currency (INR):
    a symbol reported in another currency is flagged, never relabelled."""
    bench = ds.universe.benchmark
    calendar = ds.frames[bench].index if bench in ds.frames else None
    expected_ccy = ds.universe.currency or CURRENCY
    indices = set(ds.universe.index_symbols)
    for sym, frame in ds.frames.items():
        m = ds.meta.get(sym)
        ds.quality[sym] = check_frame(
            sym, frame, calendar=calendar, currency=m.currency if m else None,
            expected_currency=expected_ccy, min_required=cfg_min_required, large_gap=large_gap,
            retrieved_at=parse_iso(m.retrieved_at) if m else None, is_demo=ds.is_demo,
            actions=actions.get(sym), is_index=sym in indices,
        )
    for sym, err in ds.failures.items():
        rep = QualityReport(symbol=sym)
        rep.add("error", "unavailable", f"Not available: {err}")
        ds.quality[sym] = rep


def make_provider(settings: Settings) -> MarketDataProvider:
    d = settings.data
    if d.provider not in ("yfinance", "yahoo"):
        raise ValueError(f"Unknown market data provider '{d.provider}'. Only 'yfinance' (Yahoo Finance, NSE "
                         "symbols ending in .NS) is supported in the India version.")
    return YFinanceProvider(timeout=d.request_timeout, max_retries=d.max_retries,
                            throttle=d.throttle_seconds, max_workers=d.max_workers)


def load_live_dataset(universe: Universe, settings: Settings, force_refresh: bool = False,
                      provider: MarketDataProvider | None = None, cache_root: Path | None = None,
                      now: datetime | None = None) -> MarketDataset:
    """Cache-first loading with honest fallbacks. Never substitutes synthetic prices."""
    now = now or utcnow()
    provider = provider or make_provider(settings)
    cache = MarketCache(provider.key, cache_root)
    ttl = timedelta(hours=settings.data.cache_ttl_hours)
    end = pd.Timestamp(now.date()) + pd.Timedelta(days=1)          # yfinance 'end' is exclusive
    start = end - pd.Timedelta(days=settings.data.history_days)
    symbols = universe.all_symbols

    frames: dict[str, pd.DataFrame] = {}
    meta: dict[str, SymbolMeta] = {}
    actions: dict[str, list[str]] = {}
    failures: dict[str, str] = {}
    notes: list[str] = []
    to_fetch = []

    for sym in symbols:
        cached = None if force_refresh else cache.read(sym)
        if cached is not None:
            df, m = cached
            retrieved = parse_iso(m.get("retrieved_at"))
            req = m.get("requested_start")
            covers = req is not None and pd.Timestamp(req) <= start + pd.Timedelta(days=10)
            # A bar cached while its session was open becomes outdated once that session closes.
            session_closed_since = bool(m.get("partial_last_bar")) and not is_partial_session(m.get("last_date"), now)
            if retrieved and now - retrieved < ttl and covers and not session_closed_since:
                frames[sym] = df
                meta[sym] = SymbolMeta(**{**m, "status": "cache", "symbol": sym})
                continue
        to_fetch.append(sym)

    if to_fetch:
        result = provider.fetch(to_fetch, start, end)
        for sym, raw in result.frames.items():
            df, acts = clean_frame(raw)
            last = df.index[-1] if len(df) else None
            m = SymbolMeta(
                symbol=sym, provider=provider.label, status="live", retrieved_at=iso(result.retrieved_at),
                currency=result.meta.get(sym, {}).get("currency"),
                exchange=result.meta.get(sym, {}).get("exchange"),
                timezone=result.meta.get(sym, {}).get("timezone"),
                instrument_type=result.meta.get(sym, {}).get("instrument_type"),
                first_date=f"{df.index[0]:%Y-%m-%d}" if len(df) else None,
                last_date=f"{last:%Y-%m-%d}" if last is not None else None,
                partial_last_bar=is_partial_session(last, result.retrieved_at),
                requested_start=f"{start:%Y-%m-%d}",
            )
            frames[sym] = df
            meta[sym] = m
            actions[sym] = acts
            try:
                cache.write(sym, df, {k: v for k, v in asdict(m).items() if k != "status"})
            except OSError as exc:
                notes.append(f"Could not write cache for {sym}: {exc}")
        for sym, err in result.failures.items():
            cached = cache.read(sym)
            if cached is not None:
                df, m = cached
                frames[sym] = df
                meta[sym] = SymbolMeta(**{**m, "status": "cache-stale", "symbol": sym,
                                          "note": f"Live fetch failed ({err}); using cached copy."})
            else:
                failures[sym] = err

    if failures:
        notes.append(f"{len(failures)} symbol(s) unavailable from {provider.label} and not in the cache.")
    stale = [s for s, m in meta.items() if m.status == "cache-stale"]
    if stale:
        notes.append(f"{len(stale)} symbol(s) shown from an older cached copy because the live fetch failed.")

    ds = MarketDataset(frames=frames, meta=meta, universe=universe, mode="live", provider_label=provider.label,
                       loaded_at=iso(now), failures=failures, notes=notes)
    _attach_quality(ds, 100, 0.25, actions)
    return ds


# ---------------------------------------------------------------------------
# Deterministic demonstration data (fictional securities)
# ---------------------------------------------------------------------------

DEMO_SCENARIOS = [
    # (trading sessions before the last session, kind, target, size, volume multiplier)
    (0, "idio", "SAFFRON.DEMO", -0.075, 3.4),        # bank falls after its quarterly results (announcement)
    (3, "volume", "MONSOON.DEMO", 0.012, 7.0),       # IT company: 7x normal volume, small price move, no news
    (9, "idio", "IRONBRG.DEMO", 0.095, 4.2),         # industrial company wins a large order (announcement)
    (22, "idio", "CURELINE.DEMO", -0.09, 3.6),       # isolated move, no supporting news
    (41, "sector", "Oil, gas & power", 0.055, 2.3),  # sector-wide move
    (63, "market", None, -0.045, 2.2),               # broad market fall affecting most stocks
    (150, "idio", "LOTUSSW.DEMO", 0.08, 3.0),        # IT guidance raised after market hours the evening before
    (200, "market", None, -0.035, 1.9),
    (260, "idio", "MANGO.DEMO", -0.09, 3.6),
    (300, "sector", "Financials", -0.04, 2.0),
]

DEMO_SCENARIO_NOTES = {
    0: "Bank falls after quarterly results declared the previous evening (fictional announcement)",
    3: "IT company trades about seven times its normal volume with a small price move; no announcement",
    9: "Engineering company wins a large order (fictional announcement during market hours)",
    22: "Pharma company falls sharply with no supporting news",
    41: "Oil, gas and power stocks rise together (sector-wide move)",
    63: "Broad market fall affecting almost every stock",
    150: "IT company jumps after raising guidance the previous evening (fictional announcement)",
    200: "Broad market fall",
    260: "FMCG company falls sharply with no supporting news",
    300: "Financials fall together (sector-wide move)",
}


def demo_scenarios(end: str = DEMO_END_DATE) -> pd.DataFrame:
    """The planted scenarios with their session dates and the stocks they affect (demonstration data only)."""
    cal = demo_calendar(end)
    rows = []
    for d, kind, target, size, vm in DEMO_SCENARIOS:
        if kind == "market":
            affected = list(DEMO_UNIVERSE.tickers)
        elif kind == "sector":
            affected = [s.ticker for s in DEMO_UNIVERSE.securities if s.sector == target]
        else:
            affected = [target]
        rows.append({"date": cal[-1 - d], "kind": kind, "target": target or "All stocks", "affected": affected,
                     "shock": size, "volume_multiplier": vm, "description": DEMO_SCENARIO_NOTES.get(d, "")})
    return pd.DataFrame(rows)


def demo_planted_sessions(stock_specific_only: bool = False) -> dict[str, list[pd.Timestamp]]:
    """Ticker -> sessions on which the generator planted a shock for that stock."""
    out: dict[str, list[pd.Timestamp]] = {}
    for row in demo_scenarios().itertuples():
        if stock_specific_only and row.kind not in ("idio", "volume"):
            continue
        for t in row.affected:
            out.setdefault(t, []).append(pd.Timestamp(row.date))
    return out


DEMO_ANNOUNCEMENTS = [
    # (sessions before last session, ticker, publication time IST, headline, days from event to publication, event)
    (1, "SAFFRON.DEMO", "18:05",
     "Saffron Bank (fictional) Q2 results: net profit falls as provisions for bad loans rise sharply",
     0, "Board meeting that approved the results, held after market hours"),
    (9, "IRONBRG.DEMO", "11:20",
     "Ironbridge Engineering (fictional) wins ₹4,200 crore metro rail order",
     1, "Letter of award received"),
    (151, "LOTUSSW.DEMO", "18:30",
     "Lotus Softworks (fictional) raises full-year revenue growth guidance after market hours",
     0, "Guidance revision announced the same evening"),
]


def demo_calendar(end: str = DEMO_END_DATE, n_days: int = DEMO_SESSIONS) -> pd.DatetimeIndex:
    """NSE trading days (weekdays minus listed holidays) ending at the demo's last session."""
    return trading_days_ending(end, n_days)


def _demo_frames(universe: Universe = DEMO_UNIVERSE, end: str = DEMO_END_DATE, n_days: int = DEMO_SESSIONS,
                 seed: int = 20) -> dict[str, pd.DataFrame]:
    """Fixed seed 20 was chosen because no unplanned alert in the last 120 sessions reaches High or Critical,
    so the designed scenarios are the ones a presenter sees first. The scenarios are listed in
    DEMO_SCENARIOS and their fictional announcements in DEMO_ANNOUNCEMENTS."""
    rng = np.random.default_rng(seed)
    dates = demo_calendar(end, n_days)
    n = len(dates)
    t_last = n - 1
    df_t = 5.0
    unit_t = math.sqrt((df_t - 2) / df_t)

    market_override = {t_last - d: size for d, kind, _, size, _ in DEMO_SCENARIOS if kind == "market"}
    market_volmult = {t_last - d: vm for d, kind, _, _, vm in DEMO_SCENARIOS if kind == "market"}

    # Market factor with GARCH(1,1)-style volatility clustering.
    mu, omega, a, b = 0.0003, 2.0e-6, 0.08, 0.90
    sig2 = omega / (1 - a - b)
    shocks = rng.standard_t(df_t, size=n) * unit_t
    r_m = np.zeros(n)
    for t in range(n):
        r = market_override.get(t, mu + math.sqrt(sig2) * shocks[t])
        r_m[t] = r
        sig2 = omega + a * (r - mu) ** 2 + b * sig2

    sectors = universe.sectors
    f_sector = {s: rng.standard_t(df_t, size=n) * unit_t * 0.006 for s in sectors}
    sector_volmult = {s: np.ones(n) for s in sectors}
    for d, kind, target, size, vm in DEMO_SCENARIOS:
        if kind == "sector":
            f_sector[target][t_last - d] = size
            sector_volmult[target][t_last - d] = vm

    frames: dict[str, pd.DataFrame] = {}

    def make_frame(returns: np.ndarray, base_price: float, base_volume: float, idio_sd: float,
                   vol_mult: np.ndarray) -> pd.DataFrame:
        close = base_price * np.cumprod(1 + returns)
        prev = np.concatenate([[base_price], close[:-1]])
        gap = rng.normal(0, idio_sd * 0.3, n)
        open_ = prev * (1 + gap)
        spread_hi = np.abs(rng.normal(0, idio_sd * 0.5, n))
        spread_lo = np.abs(rng.normal(0, idio_sd * 0.5, n))
        high = np.maximum(open_, close) * (1 + spread_hi)
        low = np.minimum(open_, close) * (1 - spread_lo)
        persist = np.zeros(n)
        e = rng.normal(0, 0.12, n)
        for t in range(1, n):
            persist[t] = 0.7 * persist[t - 1] + e[t]
        typical = max(float(np.std(returns)), 1e-4)
        log_v = (np.log(base_volume) + persist + rng.normal(0, 0.15, n)
                 + 0.22 * np.minimum(np.abs(returns) / typical, 6))
        volume = np.round(np.exp(log_v) * vol_mult)
        return pd.DataFrame({
            "open": open_, "high": high, "low": low, "close": close, "adj_close": close,
            "volume": volume, "dividends": 0.0, "splits": 0.0,
        }, index=pd.DatetimeIndex(dates, name="date"))

    market_vm = np.ones(n)
    for t, vm in market_volmult.items():
        market_vm[t] = vm
    frames[universe.benchmark] = make_frame(r_m, 20_000.0, 300_000_000, 0.004, market_vm)

    for j, (sector, idx) in enumerate(universe.sector_indices.items()):
        r_idx = r_m + f_sector[sector] + rng.normal(0, 0.0015, n)
        frames[idx] = make_frame(r_idx, 9_000.0 + 6_500.0 * j, 120_000_000, 0.004,
                                 market_vm * sector_volmult[sector])

    for i, sec in enumerate(universe.securities):
        beta = 0.75 + 0.75 * rng.random()
        gamma = 0.6 + 0.6 * rng.random()
        idio_sd = 0.008 + 0.008 * rng.random()
        alpha = rng.normal(0.0002, 0.0002)
        eps = rng.standard_t(df_t, size=n) * unit_t * idio_sd
        vol_mult = market_vm * sector_volmult[sec.sector]
        for d, kind, target, size, vm in DEMO_SCENARIOS:
            t = t_last - d
            if kind == "idio" and target == sec.ticker:
                eps[t] = size
                vol_mult = vol_mult.copy()
                vol_mult[t] *= vm
            elif kind == "volume" and target == sec.ticker:
                eps[t] = size
                vol_mult = vol_mult.copy()
                vol_mult[t] *= vm
        r = alpha + beta * r_m + gamma * f_sector[sec.sector] + eps
        frames[sec.ticker] = make_frame(r, 150.0 + 380.0 * (i % 9), 2_000_000 + 1_800_000 * (i % 7), idio_sd,
                                        vol_mult)
    return frames


def load_demo_dataset(universe: Universe = DEMO_UNIVERSE) -> MarketDataset:
    frames = _demo_frames(universe)
    meta = {}
    for sym, f in frames.items():
        meta[sym] = SymbolMeta(
            symbol=sym, provider="Synthetic demonstration generator (fictional securities)", status="demo",
            retrieved_at=None, currency=f"{CURRENCY} (synthetic)", exchange="None (synthetic, NSE-style calendar)",
            timezone=TZ_NAME, instrument_type="Synthetic",
            first_date=f"{f.index[0]:%Y-%m-%d}", last_date=f"{f.index[-1]:%Y-%m-%d}",
            note="SYNTHETIC DEMONSTRATION DATA generated with a fixed random seed. Not a market observation.",
        )
    ds = MarketDataset(
        frames=frames, meta=meta, universe=universe, mode="demo",
        provider_label="Synthetic demonstration data (fictional India-themed securities, fixed seed)",
        loaded_at=iso(utcnow()),
        notes=["SYNTHETIC DEMONSTRATION DATA: every price, volume and announcement is synthetic and refers to "
               "fictional securities. Nothing here is a real market observation or a real company announcement."],
    )
    _attach_quality(ds, 100, 0.25, {})
    return ds


def load_market_data(mode: str, universe: Universe, settings: Settings, force_refresh: bool = False) -> MarketDataset:
    if mode == "demo":
        return load_demo_dataset(universe)
    return load_live_dataset(universe, settings, force_refresh=force_refresh)
