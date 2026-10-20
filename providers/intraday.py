"""Intraday 5-minute bars for the live NSE watchlist, kept apart from the daily analytics.

What this module does
* Requests 5-minute bars from Yahoo Finance through yfinance. That source is unofficial and may be delayed; it does
  not promise when a bar appears. Nothing is retrieved from NSE's own website.
* Keeps the bars in memory in this server process only. The daily path (alerts, priority scores, investigations)
  keeps its own daily bars and 6-hour disk cache; nothing here changes it.
* Reports for every refresh what was requested and when, the newest complete bar, and one status: Fresh, Waiting
  for new data, Cached, Stale or Unavailable, with a sentence explaining it.

What it does not do
* It never fills a missing interval, never invents a bar and never relabels daily bars as intraday.
* It does not run in the background. A refresh happens only while someone has the page open (a Streamlit timed
  fragment) or presses Refresh now; when nobody has the app open, no bars are collected.
* It never calls the LLM.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from config.market import (MARKET_TZ, SESSION_CLOSE, SESSION_OPEN, holiday_name, is_trading_day, next_trading_day,
                           previous_trading_day)

INTERVAL_MINUTES = {"1m": 1, "2m": 2, "5m": 5, "15m": 15, "30m": 30, "60m": 60}
DEFAULT_INTERVAL = "5m"
LATEST_PERIOD = "5d"          # each refresh: the last few sessions, small
BASELINE_PERIOD = "60d"       # once a day: history for time-of-day baselines (Yahoo keeps 5-minute bars ~60 days)
REFRESH_CHOICES = (5, 10, 15)
DEFAULT_REFRESH_MINUTES = 10
CLOSE_GRACE = timedelta(minutes=10)   # the 15:25 to 15:30 bar can appear a few minutes after the close
MIN_REPEAT = timedelta(seconds=15)    # a request that finished this recently is reused, not repeated
SESSION_MINUTES = (SESSION_CLOSE.hour * 60 + SESSION_CLOSE.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
SOURCE_LABEL = "Yahoo Finance via yfinance (unofficial; may be delayed)"
STATUS_LABELS = {"fresh": "Fresh", "waiting": "Waiting for new data", "cached": "Cached", "stale": "Stale",
                 "unavailable": "Unavailable"}
COLUMNS = ["open", "high", "low", "close", "volume", "partial", "session", "slot"]
_RENAME = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(MARKET_TZ)


def bars_per_session(minutes: int) -> int:
    return -(-SESSION_MINUTES // minutes)


def slot_start(session: date, slot: int, minutes: int) -> pd.Timestamp:
    """Start time (IST) of bar number `slot` of a session."""
    open_ = pd.Timestamp(datetime.combine(session, SESSION_OPEN), tz=MARKET_TZ)
    return open_ + pd.Timedelta(minutes=slot * minutes)


def bar_end(start: pd.Timestamp, minutes: int) -> pd.Timestamp:
    close = pd.Timestamp(datetime.combine(start.date(), SESSION_CLOSE), tz=MARKET_TZ)
    return min(start + pd.Timedelta(minutes=minutes), close)


def empty_frame() -> pd.DataFrame:
    out = pd.DataFrame(columns=COLUMNS)
    out.index = pd.DatetimeIndex([], tz=MARKET_TZ, name="time")
    return out


def normalise_intraday(raw: pd.DataFrame | None, minutes: int, received_at: datetime,
                       is_index: bool = False) -> tuple[pd.DataFrame, dict]:
    """Regular-session bars indexed by their start time in IST, with a `partial` flag and the session slot.

    Rows outside 09:15 to 15:30 IST, rows not on the bar grid (a live quote stamped at the current minute),
    duplicates and rows without a price are dropped and counted. A bar whose end lies after `received_at` is still
    forming: it is kept for display with partial=True and excluded from every statistic. Zero or missing volume is
    stored as missing, never as zero (Yahoo reports no volume for indices).
    """
    notes = {"rows_received": 0, "outside_session": 0, "off_grid": 0, "duplicates": 0, "no_price": 0,
             "volume_missing": 0}
    if raw is None or raw.empty:
        return empty_frame(), notes
    notes["rows_received"] = int(len(raw))
    df = raw.rename(columns=_RENAME)
    idx = pd.DatetimeIndex(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    df = df.set_axis(idx.tz_convert(MARKET_TZ), axis=0)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = np.nan
    df = df[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce").astype(float)
    dup = df.index.duplicated(keep="last")
    notes["duplicates"] = int(dup.sum())
    df = df[~dup].sort_index()
    mins = (df.index.hour * 60 + df.index.minute) - (SESSION_OPEN.hour * 60 + SESSION_OPEN.minute)
    in_session = (mins >= 0) & (mins < SESSION_MINUTES)
    on_grid = (df.index.second == 0) & (df.index.microsecond == 0) & (np.asarray(mins) % minutes == 0)
    notes["outside_session"] = int((~in_session).sum())
    notes["off_grid"] = int((in_session & ~on_grid).sum())
    keep = in_session & on_grid
    df, mins = df[keep], np.asarray(mins)[keep]
    no_price = df["close"].isna() | (df["close"] <= 0)
    notes["no_price"] = int(no_price.sum())
    df, mins = df[~no_price.to_numpy()], mins[~no_price.to_numpy()]
    vol = df["volume"]
    missing = vol.isna() | (vol <= 0)
    notes["volume_missing"] = 0 if is_index else int(missing.sum())
    df = df.assign(volume=vol.where(~missing))
    starts = pd.Series(df.index, index=df.index)
    closes = starts.dt.normalize() + pd.Timedelta(hours=SESSION_CLOSE.hour, minutes=SESSION_CLOSE.minute)
    ends = (starts + pd.Timedelta(minutes=minutes)).where(lambda e: e <= closes, closes)
    df["partial"] = (ends > pd.Timestamp(to_ist(received_at))).to_numpy()
    df["session"] = df.index.date
    df["slot"] = (mins // minutes).astype(int)
    df.index.name = "time"
    return df[COLUMNS], notes


def complete(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[~frame["partial"].astype(bool)] if len(frame) else frame


def latest_complete_bar(frame: pd.DataFrame | None) -> pd.Timestamp | None:
    if frame is None or frame.empty:
        return None
    done = complete(frame)
    return done.index.max() if len(done) else None


# --- Market clock ------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MarketPhase:
    now_ist: datetime
    trading_day: bool
    holiday: str | None
    is_open: bool            # 09:15 <= now < 15:30 on a trading day
    in_grace: bool           # the ten minutes after the close, while the last bar may still arrive
    last_session: date       # the newest session whose bars can exist now
    next_open: datetime      # next regular open, IST

    @property
    def requests_useful(self) -> bool:
        return self.is_open or self.in_grace


def market_phase(now_utc: datetime) -> MarketPhase:
    now = to_ist(now_utc)
    today = now.date()
    trading = is_trading_day(today)
    open_dt = datetime.combine(today, SESSION_OPEN, tzinfo=MARKET_TZ)
    close_dt = datetime.combine(today, SESSION_CLOSE, tzinfo=MARKET_TZ)
    is_open = trading and open_dt <= now < close_dt
    in_grace = trading and close_dt <= now < close_dt + CLOSE_GRACE
    if trading and now >= open_dt:
        last_session = today
    else:
        last_session = previous_trading_day(today).date()
    if trading and now < open_dt:
        nxt = open_dt
    else:
        nxt = datetime.combine(next_trading_day(today).date(), SESSION_OPEN, tzinfo=MARKET_TZ)
    return MarketPhase(now, trading, holiday_name(today), is_open, in_grace, last_session, nxt)


def expected_latest_bar(phase: MarketPhase, minutes: int) -> pd.Timestamp | None:
    """Start of the newest bar that has finished by now (None just after the open, before the first bar ends)."""
    if phase.is_open:
        elapsed = (phase.now_ist - datetime.combine(phase.now_ist.date(), SESSION_OPEN, tzinfo=MARKET_TZ))
        done = int(elapsed.total_seconds() // (minutes * 60)) - 1
        return None if done < 0 else slot_start(phase.now_ist.date(), done, minutes)
    return slot_start(phase.last_session, bars_per_session(minutes) - 1, minutes)


def _closed_reason(phase: MarketPhase) -> str:
    if phase.holiday:
        return f"today is an NSE holiday ({phase.holiday})"
    if not phase.trading_day:
        return "it is a weekend"
    if phase.now_ist.time() < SESSION_OPEN:
        return "the session has not opened yet"
    return "the session has closed"


# --- Fetching ----------------------------------------------------------------------------------------------

@dataclass
class FetchOutcome:
    frames: dict[str, pd.DataFrame]
    failures: dict[str, str]
    notes: dict[str, dict]
    requested_at: datetime
    received_at: datetime
    period: str
    interval: str


class YahooIntradayFetcher:
    """yfinance intraday requests with a small worker pool, a throttle and a stop on rate limits or outages."""

    label = SOURCE_LABEL

    def __init__(self, timeout: float = 15.0, throttle: float = 0.25, max_workers: int = 4):
        self.timeout, self.throttle, self.max_workers = timeout, throttle, max_workers
        self._gate = threading.Lock()
        self._last = 0.0

    def _wait_turn(self) -> None:
        with self._gate:
            gap = time.monotonic() - self._last
            if gap < self.throttle:
                time.sleep(self.throttle - gap)
            self._last = time.monotonic()

    def fetch(self, symbols: list[str], *, period: str, interval: str) -> FetchOutcome:
        import yfinance as yf
        minutes = INTERVAL_MINUTES[interval]
        requested = utcnow()
        stop, lock = threading.Event(), threading.Lock()
        counts = {"ok": 0, "conn": 0}
        rate_error = getattr(getattr(yf, "exceptions", None), "YFRateLimitError", None)

        def one(sym: str):
            if stop.is_set():
                return sym, None, {}, "Skipped: Yahoo Finance was unreachable or rate-limited earlier in this refresh."
            self._wait_turn()
            try:
                raw = yf.Ticker(sym).history(period=period, interval=interval, auto_adjust=False, actions=False,
                                             prepost=False, timeout=self.timeout)
            except Exception as exc:  # noqa: BLE001 - reported per symbol, never raised into the page
                msg = f"{type(exc).__name__}: {str(exc)[:200]}"
                if rate_error is not None and isinstance(exc, rate_error):
                    stop.set()
                    return sym, None, {}, "Rate limited by Yahoo Finance (too many requests)."
                if any(k in msg.lower() for k in ("timed out", "timeout", "connection", "name resolution", "proxy")):
                    with lock:
                        counts["conn"] += 1
                        if counts["conn"] >= 3 and counts["ok"] == 0:
                            stop.set()
                return sym, None, {}, msg
            with lock:
                counts["ok"] += 1
            if raw is None or raw.empty:
                return sym, None, {}, "Provider returned no intraday rows."
            frame, notes = normalise_intraday(raw, minutes, utcnow(), is_index=sym.startswith("^"))
            if frame.empty:
                return sym, None, notes, "No regular-session bars in the response."
            return sym, frame, notes, None

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            results = list(pool.map(one, symbols))
        out = FetchOutcome({}, {}, {}, requested, utcnow(), period, interval)
        for sym, frame, notes, error in results:
            out.notes[sym] = notes
            if error or frame is None:
                out.failures[sym] = error or "No data returned."
            else:
                out.frames[sym] = frame
        return out


# --- Store -------------------------------------------------------------------------------------------------

@dataclass
class IntradaySnapshot:
    frames: dict[str, pd.DataFrame]               # latest window per symbol
    failures: dict[str, str]
    notes: dict[str, dict]
    requested_at: datetime
    received_at: datetime
    interval: str
    source: str
    carried: dict[str, datetime] = field(default_factory=dict)   # symbols kept from an earlier refresh, and when

    def latest_bar(self, prefer: str | None = None) -> pd.Timestamp | None:
        if prefer and prefer in self.frames:
            hit = latest_complete_bar(self.frames[prefer])
            if hit is not None:
                return hit
        bars = [b for b in (latest_complete_bar(f) for f in self.frames.values()) if b is not None]
        return max(bars) if bars else None


@dataclass
class IntradayView:
    status: str
    explanation: str
    snapshot: IntradaySnapshot | None
    history: dict[str, pd.DataFrame]              # baseline and latest bars merged, for the statistics
    requested: bool                               # this call sent a request to the provider
    checked_at: datetime
    last_attempt_at: datetime | None
    last_error: str | None
    interval: str
    latest_bar: pd.Timestamp | None
    phase: MarketPhase

    @property
    def label(self) -> str:
        return STATUS_LABELS[self.status]


def _clock(ts: datetime | pd.Timestamp | None, fmt: str = "%H:%M:%S") -> str:
    return "n/a" if ts is None else to_ist(ts).strftime(fmt) + " IST"


def _age(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{round(seconds / 60)} min"
    return f"{seconds / 3600:.1f} h"


def describe_data_state(phase: MarketPhase, latest: pd.Timestamp | None, previous: pd.Timestamp | None,
                        minutes: int) -> tuple[str, str]:
    """(status, explanation) for data that was just retrieved successfully."""
    if latest is None:
        if phase.is_open:
            first_end = slot_start(phase.now_ist.date(), 0, minutes) + pd.Timedelta(minutes=minutes)
            return "waiting", (f"The session opened at 09:15 IST. The first complete {minutes}-minute bar is "
                               f"expected after {first_end:%H:%M} IST.")
        return "waiting", "The provider returned no complete bars."
    end = bar_end(latest, minutes)
    when = f"{latest:%a %d %b}, {latest:%H:%M} to {end:%H:%M} IST"
    if not phase.requests_useful:
        final = slot_start(phase.last_session, bars_per_session(minutes) - 1, minutes)
        nxt = f"{phase.next_open:%a %d %b} at {phase.next_open:%H:%M} IST"
        if latest >= final:
            return "waiting", (f"No newer bars: {_closed_reason(phase)}. The bars shown are the complete session "
                               f"of {latest:%a %d %b} (last bar {latest:%H:%M} to {end:%H:%M} IST). New bars arrive "
                               f"after the next session opens on {nxt}.")
        return "waiting", (f"No newer bars: {_closed_reason(phase)}. The newest bar the provider returned is {when}; "
                           f"later bars of that session were not returned. The next session opens on {nxt}.")
    expected = expected_latest_bar(phase, minutes)
    behind = 0 if expected is None else max(0, int((expected - latest) / pd.Timedelta(minutes=minutes)))
    if previous is not None and latest <= previous:
        nxt_start = latest + pd.Timedelta(minutes=minutes)
        nxt_end = bar_end(nxt_start, minutes)
        return "waiting", (f"No newer bar since the last refresh. The newest bar is {when}. The next bar "
                           f"({nxt_start:%H:%M} to {nxt_end:%H:%M}) completes at {nxt_end:%H:%M} IST; Yahoo may "
                           "publish it a few minutes later.")
    if behind <= 1:
        return "fresh", f"Up to date: the newest complete bar is {when}."
    return "waiting", (f"New bars arrived, but the newest is {when}, about {behind * minutes} minutes behind the "
                       "clock. The provider may be delayed; the next refresh will check again.")


class IntradayStore:
    """In-memory intraday bars shared by the sessions of one server process.

    Requests are serialised by a lock, so two sessions refreshing at once cause one request, not two. A refresh
    within the cache life (one bar interval less 20 seconds) is served from memory. A failed refresh keeps the last
    good bars and reports their age. History for the time-of-day baselines is requested once per day.
    """

    def __init__(self, fetcher=None, interval: str = DEFAULT_INTERVAL, clock=utcnow):
        self.fetcher = fetcher
        self.interval = interval
        self.minutes = INTERVAL_MINUTES[interval]
        self.clock = clock
        self._lock = threading.Lock()
        self._latest: IntradaySnapshot | None = None
        self._baseline: dict[str, pd.DataFrame] = {}
        self._baseline_day: dict[str, date] = {}
        self._last_attempt: datetime | None = None
        self._last_error: str | None = None
        self._last_view: IntradayView | None = None
        self._benchmark: str | None = None
        self.requests_made = 0

    @property
    def ttl(self) -> timedelta:
        return max(timedelta(seconds=30), timedelta(minutes=self.minutes) - timedelta(seconds=20))

    def _history(self, symbols: list[str]) -> dict[str, pd.DataFrame]:
        out = {}
        latest = self._latest.frames if self._latest else {}
        for sym in symbols:
            parts = [f for f in (self._baseline.get(sym), latest.get(sym)) if f is not None and len(f)]
            if not parts:
                continue
            merged = pd.concat(parts)
            out[sym] = merged[~merged.index.duplicated(keep="last")].sort_index()
        return out

    def _view(self, status, explanation, requested, now, symbols, phase, remember=False) -> IntradayView:
        snap = self._latest
        view = IntradayView(status, explanation, snap, self._history(symbols), requested, now, self._last_attempt,
                            self._last_error, self.interval, snap.latest_bar(self._benchmark) if snap else None, phase)
        if remember:
            self._last_view = view
        return view

    def _closed_and_complete(self, phase: MarketPhase) -> bool:
        """True when the market is closed and the last session's bars are already in memory (or were requested
        after that session's close), so another request cannot bring anything new."""
        snap = self._latest
        if snap is None or phase.requests_useful:
            return False
        final = slot_start(phase.last_session, bars_per_session(self.minutes) - 1, self.minutes)
        latest = snap.latest_bar(self._benchmark)
        after_close = (datetime.combine(phase.last_session, SESSION_CLOSE, tzinfo=MARKET_TZ) + CLOSE_GRACE)
        return (latest is not None and latest >= final) or snap.requested_at >= after_close

    def get(self, symbols: list[str], *, benchmark: str | None = None, mode: str = "peek") -> IntradayView:
        """mode 'peek' never requests; 'auto' requests when the cache has expired and new bars can exist;
        'manual' requests now (a request that finished in the last 15 seconds is reused)."""
        now = self.clock()
        phase = market_phase(now)
        snap = self._latest
        self._benchmark = benchmark or self._benchmark
        if mode == "peek":
            if snap is None:
                return self._view("unavailable", "No intraday bars have been loaded in this server process yet. "
                                  "Press Refresh now, or turn on auto-refresh.", False, now, symbols, phase)
            return self._cached_view(now, phase, symbols)
        with self._lock:
            now = self.clock()
            phase = market_phase(now)
            snap = self._latest
            if snap is not None and mode == "auto":
                if now - snap.received_at < self.ttl:
                    return self._cached_view(now, phase, symbols)
                if self._closed_and_complete(phase):
                    status, text = describe_data_state(phase, snap.latest_bar(benchmark), None, self.minutes)
                    return self._view(status, text + " Automatic refresh sends no requests while the market is "
                                      "closed; Refresh now still does.", False, now, symbols, phase)
            if (mode == "manual" and self._last_attempt is not None and now - self._last_attempt < MIN_REPEAT
                    and self._last_view is not None):
                v = self._last_view
                return self._view(v.status, f"A refresh finished {_age((now - self._last_attempt).total_seconds())} "
                                  "ago; its result is shown instead of sending the same request again. "
                                  + v.explanation, False, now, symbols, phase)
            return self._refresh(symbols, benchmark, now, phase)

    def _cached_view(self, now, phase, symbols) -> IntradayView:
        snap = self._latest
        age = (now - snap.received_at).total_seconds()
        nxt = snap.received_at + self.ttl
        text = (f"Shown from memory: requested at {_clock(snap.requested_at)}, {_age(age)} ago, by this or another "
                f"open session. ")
        if self._last_error and self._last_attempt and self._last_attempt > snap.received_at:
            text = (f"The last refresh at {_clock(self._last_attempt)} failed ({self._last_error}). Showing bars "
                    f"requested at {_clock(snap.requested_at)}, {_age(age)} old.")
            return self._view("stale", text, False, now, symbols, phase)
        if age >= self.ttl.total_seconds():
            text += "Press Refresh now, or turn on auto-refresh, to request newer bars."
        else:
            text += f"A new request is sent after {_clock(nxt)} or when you press Refresh now."
        return self._view("cached", text, False, now, symbols, phase)

    def _refresh(self, symbols, benchmark, now, phase) -> IntradayView:
        today = phase.now_ist.date()
        need_base = [s for s in symbols if self._baseline_day.get(s) != today]
        quick = [s for s in symbols if s not in need_base]
        previous = self._latest.latest_bar(benchmark) if self._latest else None
        outcomes = []
        self._last_attempt = now
        self.requests_made += 1
        if need_base:
            outcomes.append(("base", self.fetcher.fetch(need_base, period=BASELINE_PERIOD, interval=self.interval)))
        if quick:
            outcomes.append(("quick", self.fetcher.fetch(quick, period=LATEST_PERIOD, interval=self.interval)))
        frames, failures, notes = {}, {}, {}
        for kind, out in outcomes:
            frames.update(out.frames)
            failures.update(out.failures)
            notes.update(out.notes)
            if kind == "base":
                for sym, f in out.frames.items():
                    self._baseline[sym] = f
                    self._baseline_day[sym] = today
        received = max(o.received_at for _, o in outcomes) if outcomes else now
        if not frames:
            reason = _first_reason(failures) or "no data returned"
            self._last_error = reason
            if self._latest is not None:
                age = (now - self._latest.received_at).total_seconds()
                return self._view("stale", f"The refresh at {_clock(now)} failed ({reason}). Showing bars requested "
                                  f"at {_clock(self._latest.requested_at)}, {_age(age)} old.", True, now, symbols,
                                  phase, remember=True)
            return self._view("unavailable", f"Intraday bars could not be retrieved ({reason}). The daily analytics "
                              "are not affected.", True, now, symbols, phase, remember=True)
        carried = {}
        if self._latest is not None:
            for sym in failures:
                if sym in self._latest.frames:
                    frames[sym] = self._latest.frames[sym]
                    carried[sym] = self._latest.carried.get(sym, self._latest.received_at)
        self._last_error = None
        self._latest = IntradaySnapshot(frames, failures, notes, now, received, self.interval,
                                        getattr(self.fetcher, "label", SOURCE_LABEL), carried)
        status, text = describe_data_state(phase, self._latest.latest_bar(benchmark), previous, self.minutes)
        missing = [s for s in symbols if s not in frames]
        extras = []
        if missing:
            extras.append(f"{len(missing)} symbol(s) returned no bars")
        if carried:
            extras.append(f"{len(carried)} symbol(s) failed this time and show their earlier bars")
        if extras:
            text += " Note: " + "; ".join(extras) + "."
        return self._view(status, text, True, now, symbols, phase, remember=True)


def _first_reason(failures: dict[str, str]) -> str | None:
    if not failures:
        return None
    reasons = list(failures.values())
    top = max(set(reasons), key=reasons.count)
    return f"{top} ({reasons.count(top)} of {len(reasons)} symbols)" if len(reasons) > 1 else top


_STORE: IntradayStore | None = None
_STORE_LOCK = threading.Lock()


def shared_store() -> IntradayStore:
    """The process-wide store used by the app (one per server process, shared by every open session)."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = IntradayStore(YahooIntradayFetcher())
        return _STORE
