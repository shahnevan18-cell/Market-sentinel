"""Exchange conventions for the monitored market: India, National Stock Exchange (NSE).

Everything that depends on the exchange lives in this one module, so the analytics, news timing, data-quality
checks and the interface all read the same rules:

* Time zone Asia/Kolkata (IST, UTC+05:30, no daylight saving).
* Normal market 09:15 to 15:30 IST. NSE's closing session runs 15:40 to 16:00 and trade modifications are
  allowed until 16:15, after which the final bhavcopy is generated. A daily bar is treated as final only after
  16:15 IST. Source: https://www.nseindia.com/static/market-data/market-timings (checked 20 Oct 2026).
* Trading holidays of the Capital Market segment, copied from NSE circulars (listed below). A weekday on this list
  has no regular session. Weekends have no regular session either, but NSE occasionally holds special sessions
  (Muhurat trading on Diwali, Budget-day sessions), so observed weekend or holiday bars are kept and reported,
  never deleted.
* Prices in Indian rupees (INR, symbol ₹).

Dates outside the holiday table (before 2024 or after 2026) fall back to "every weekday is a possible session";
the data-driven calendar (the NIFTY 50 bars actually returned) still decides which sessions exist.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

import pandas as pd

TZ_NAME = "Asia/Kolkata"
TZ_LABEL = "IST"
try:
    from zoneinfo import ZoneInfo
    MARKET_TZ = ZoneInfo(TZ_NAME)
except Exception:  # pragma: no cover - tzdata missing on some Windows installs
    MARKET_TZ = timezone(timedelta(hours=5, minutes=30), TZ_LABEL)   # India has no daylight saving: exact

SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
BAR_FINAL_AFTER = time(16, 15)
CURRENCY = "INR"
CURRENCY_SYMBOL = "₹"

MARKET_ID = "IN-NSE"
MARKET_NAME = "India (NSE)"
EXCHANGE_NAME = "National Stock Exchange of India (NSE)"
TIMINGS_SOURCE = "https://www.nseindia.com/static/market-data/market-timings"

# NSE Capital Market segment trading holidays falling on weekdays.
NSE_HOLIDAYS: dict[str, str] = {
    # 2024: circular NSE/CMTR/59722 (12 Dec 2023) and NSE/CMTR/64960 (8 Nov 2024)
    "2024-01-26": "Republic Day",
    "2024-03-08": "Mahashivratri",
    "2024-03-25": "Holi",
    "2024-03-29": "Good Friday",
    "2024-04-11": "Id-Ul-Fitr (Ramadan Eid)",
    "2024-04-17": "Shri Ram Navmi",
    "2024-05-01": "Maharashtra Day",
    "2024-06-17": "Bakri Id",
    "2024-07-17": "Moharram",
    "2024-08-15": "Independence Day / Parsi New Year",
    "2024-10-02": "Mahatma Gandhi Jayanti",
    "2024-11-01": "Diwali Laxmi Pujan (Muhurat trading session only)",
    "2024-11-15": "Gurunanak Jayanti",
    "2024-11-20": "Maharashtra assembly elections",
    "2024-12-25": "Christmas",
    # 2025: circular NSE/CMTR/65587 (13 Dec 2024)
    "2025-02-26": "Mahashivratri",
    "2025-03-14": "Holi",
    "2025-03-31": "Id-Ul-Fitr (Ramadan Eid)",
    "2025-04-10": "Shri Mahavir Jayanti",
    "2025-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2025-04-18": "Good Friday",
    "2025-05-01": "Maharashtra Day",
    "2025-08-15": "Independence Day",
    "2025-08-27": "Ganesh Chaturthi",
    "2025-10-02": "Mahatma Gandhi Jayanti / Dussehra",
    "2025-10-21": "Diwali Laxmi Pujan (Muhurat trading session only)",
    "2025-10-22": "Diwali-Balipratipada",
    "2025-11-05": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2025-12-25": "Christmas",
    # 2026: circular NSE/CMTR/71775 (12 Dec 2025) and NSE/CMTR/72260 (12 Jan 2026)
    "2026-01-15": "Municipal Corporation elections in Maharashtra",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb Sri Guru Nanak Dev",
    "2026-12-25": "Christmas",
}
HOLIDAY_YEARS = (2024, 2025, 2026)
HOLIDAY_SOURCE = ("NSE Capital Market circulars NSE/CMTR/59722, 64960, 65587, 71775 and 72260 "
                  "(trading holidays for 2024, 2025 and 2026)")
ANNOUNCED_SPECIAL_SESSIONS = {
    "2026-11-08": "Muhurat trading on Sunday (Diwali Laxmi Pujan); timings to be notified by NSE",
}
_HOLIDAY_DATES = {date.fromisoformat(d) for d in NSE_HOLIDAYS}

# Official pages for manual verification of company disclosures. The app links to them; it does not
# retrieve them automatically (NSE's terms of use, clause 9, prohibit systematic or automated data collection).
OFFICIAL_DISCLOSURE_LINKS = (
    {"label": "NSE corporate announcements", "publisher": "National Stock Exchange of India",
     "url": "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
     "how": "Search by company name or symbol and set the date range around the event."},
    {"label": "NSE financial results", "publisher": "National Stock Exchange of India",
     "url": "https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
     "how": "Quarterly results filed with NSE, searchable by company."},
    {"label": "BSE financial results", "publisher": "BSE Ltd",
     "url": "https://www.bseindia.com/corporates/Comp_Resultsnew.aspx",
     "how": "Results filed with BSE, searchable by company."},
    {"label": "BSE corporate filings", "publisher": "BSE Ltd",
     "url": "https://www.bseindia.com/corporates.html",
     "how": "Entry point to BSE announcements, corporate actions and board meetings."},
    {"label": "SEBI directory of corporate filings", "publisher": "Securities and Exchange Board of India",
     "url": "https://www.sebi.gov.in/curation/corporate_filings.html",
     "how": "SEBI's index of where each filing type is published on NSE and BSE."},
)
DISCLOSURE_TERMS_NOTE = (
    "Official NSE and BSE disclosures are link-only in this app. NSE's website terms of use (clause 9) prohibit "
    "systematic or automated data collection, so the app does not scrape exchange websites or call their "
    "undocumented endpoints. Open the links to check announcements manually."
)


def _as_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return pd.Timestamp(d).date()


def to_market_time(ts: datetime) -> datetime:
    """Convert an aware (or naive UTC) datetime to India time."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(MARKET_TZ)


def holiday_name(d) -> str | None:
    return NSE_HOLIDAYS.get(f"{_as_date(d):%Y-%m-%d}")


def holiday_table_covers(d) -> bool:
    return _as_date(d).year in HOLIDAY_YEARS


def is_trading_day(d) -> bool:
    """Weekday that is not a listed NSE trading holiday (special weekend sessions are not expected in advance)."""
    day = _as_date(d)
    return day.weekday() < 5 and day not in _HOLIDAY_DATES


def previous_trading_day(d) -> pd.Timestamp:
    day = _as_date(d) - timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return pd.Timestamp(day)


def next_trading_day(d) -> pd.Timestamp:
    day = _as_date(d) + timedelta(days=1)
    while not is_trading_day(day):
        day += timedelta(days=1)
    return pd.Timestamp(day)


def shift_trading_days(d, n: int) -> pd.Timestamp:
    """Move n trading days from d (negative = earlier). A non-trading start counts from its neighbouring sessions."""
    out = pd.Timestamp(_as_date(d))
    if n < 0:
        for _ in range(-n):
            out = previous_trading_day(out)
    else:
        for _ in range(n):
            out = next_trading_day(out)
    return out


def trading_days(start, end) -> pd.DatetimeIndex:
    days = pd.date_range(pd.Timestamp(_as_date(start)), pd.Timestamp(_as_date(end)), freq="D")
    return pd.DatetimeIndex([d for d in days if is_trading_day(d)], name="date")


def trading_days_ending(end, periods: int) -> pd.DatetimeIndex:
    """The last `periods` trading days up to and including `end` (if `end` is itself a trading day)."""
    out = []
    day = _as_date(end)
    while len(out) < periods:
        if is_trading_day(day):
            out.append(pd.Timestamp(day))
        day -= timedelta(days=1)
    return pd.DatetimeIndex(sorted(out), name="date")


def sessions_between(a, b) -> int:
    """Number of expected trading sessions after `a` up to and including `b` (0 when a >= b)."""
    if a is None or b is None:
        return 0
    a, b = _as_date(a), _as_date(b)
    if a >= b:
        return 0
    return len(trading_days(a + timedelta(days=1), b))


def _local_to_utc(d, t: time) -> datetime:
    return datetime.combine(_as_date(d), t, tzinfo=MARKET_TZ).astimezone(timezone.utc)


def session_open_utc(d) -> datetime:
    return _local_to_utc(d, SESSION_OPEN)


def session_close_utc(d) -> datetime:
    """15:30 IST on day d, in UTC (10:00 UTC)."""
    return _local_to_utc(d, SESSION_CLOSE)


def bar_final_utc(d) -> datetime:
    """Time after which the daily bar for d is treated as complete (16:15 IST)."""
    return _local_to_utc(d, BAR_FINAL_AFTER)


def expected_latest_session(now_utc: datetime | None = None) -> pd.Timestamp:
    """Most recent trading day whose bar should be final at `now_utc` (holidays and weekends skipped)."""
    now_local = to_market_time(now_utc or datetime.now(timezone.utc))
    today = now_local.date()
    if is_trading_day(today) and now_local.time() >= BAR_FINAL_AFTER:
        return pd.Timestamp(today)
    return previous_trading_day(today)


def is_partial_session(bar_date, retrieved_at_utc: datetime | None) -> bool:
    """True when the bar's date is the India date of retrieval and the bar was not yet final (before 16:15 IST).

    This also covers a special session (for example Muhurat trading) retrieved while it was running.
    """
    if bar_date is None or retrieved_at_utc is None:
        return False
    local = to_market_time(retrieved_at_utc)
    return _as_date(bar_date) == local.date() and local.time() < BAR_FINAL_AFTER


def fmt_market_time(value, with_date: bool = True) -> str:
    """'30 Sep 2026, 07:40 IST' for an ISO string or datetime (n/a when missing)."""
    if value is None or value == "":
        return "n/a"
    try:
        ts = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    local = to_market_time(ts)
    return local.strftime("%d %b %Y, %H:%M IST" if with_date else "%H:%M IST")


def fmt_market_clock(value) -> str:
    """'18:05:12' in India time for an ISO string or datetime ('' when missing)."""
    if value is None or value == "":
        return ""
    try:
        ts = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    return to_market_time(ts).strftime("%H:%M:%S")


def group_indian(n: int) -> str:
    """Indian digit grouping: 12345678 -> 1,23,45,678."""
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        pairs = []
        while len(head) > 2:
            pairs.insert(0, head[-2:])
            head = head[:-2]
        out = ",".join(([head] if head else []) + pairs) + "," + tail
    return ("-" if n < 0 else "") + out


def _missing(x) -> bool:
    try:
        return x is None or bool(pd.isna(x))
    except (TypeError, ValueError):
        return False


def fmt_inr(x, signed: bool = False) -> str:
    """Rupee amount with Indian digit grouping, rounded to whole rupees: ₹1,00,00,000 or -₹2,45,000."""
    if _missing(x):
        return "n/a"
    v = int(round(float(x)))
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    return f"{sign}{CURRENCY_SYMBOL}{group_indian(abs(v))}"


def fmt_inr_short(x, signed: bool = False) -> str:
    """Rupee amount in lakh or crore: ₹1.00 crore, -₹2.45 lakh."""
    if _missing(x):
        return "n/a"
    v = float(x)
    sign = "-" if v < 0 else ("+" if signed and v > 0 else "")
    a = abs(v)
    if a >= 1e7:
        body = f"{a / 1e7:,.2f} crore"
    elif a >= 1e5:
        body = f"{a / 1e5:,.2f} lakh"
    else:
        body = group_indian(int(round(a)))
    return f"{sign}{CURRENCY_SYMBOL}{body}"


def session_text() -> str:
    return (f"NSE normal market {SESSION_OPEN:%H:%M} to {SESSION_CLOSE:%H:%M} {TZ_LABEL}; daily bars treated as final "
            f"after {BAR_FINAL_AFTER:%H:%M} {TZ_LABEL}")


@dataclass(frozen=True)
class MarketFacts:
    """Facts handed to the agents and written into every record, so the market context travels with the data."""
    market_id: str = MARKET_ID
    market: str = MARKET_NAME
    exchange: str = EXCHANGE_NAME
    timezone: str = TZ_NAME
    session: str = ""
    currency: str = CURRENCY

    def as_dict(self) -> dict:
        return {"market_id": self.market_id, "market": self.market, "exchange": self.exchange,
                "timezone": self.timezone, "session": self.session or session_text(), "currency": self.currency}


MARKET_FACTS = MarketFacts()
