"""Monitored universes.

Two universes are defined:

* LIVE_UNIVERSE: 25 established, liquid companies listed on the National Stock Exchange of India, all NIFTY 50
  constituents, with NIFTY 50 (^NSEI) as the market benchmark, three NSE sector indices and the BSE SENSEX
  for display. Provider symbols are Yahoo Finance NSE symbols ending in ".NS".

  Constituent status was checked on 20 Oct 2026 against the NIFTY 50 list of 8 Dec 2025 and the NSE Indices
  press releases of 23 Feb, 12 Mar, 10 Aug and 15 Sep 2026. Wipro, which was on the original candidate list,
  left the NIFTY 50 on 30 Sep 2026 (replaced by BSE Ltd), so HCL Technologies takes the third IT slot. The
  official constituent file could not be downloaded automatically, so this is a representative, manually
  configured watchlist; re-check it at https://www.niftyindices.com before relying on it.

  Peer groups start from the NSE industry labels of the NIFTY 50 constituent list. Two pairs of industries are
  combined so that every stock in them has a peer ("Oil, Gas & Consumable Fuels" with "Power", and
  "Construction Materials" with "Metals & Mining"). Larsen & Toubro (Construction) and Bharti Airtel
  (Telecommunication) have no peer in the watchlist, so no peer comparison is made for them.

  Sector indices are used only where NSE publishes a matching index and the provider has enough history for
  it: NIFTY Bank for the financial group (it holds the five banks; Bajaj Finance is a non-bank lender),
  NIFTY IT and NIFTY Pharma. The other groups have no sector index comparison. Every symbol must pass
  scripts/validate_symbols.py; a symbol that fails is removed from this file rather than kept silently.

  Removed after the live check on 20 Oct 2026 (15:59 IST): NIFTY Energy (^CNXENERGY), NIFTY FMCG (^CNXFMCG)
  and NIFTY Auto (^CNXAUTO). Yahoo returned only 3 sessions for each (15 to 19 Oct 2026), too few to estimate
  a beta or a sector z-score, so the oil, gas and power, FMCG and auto groups are compared with peers only.
  Re-add a symbol only after scripts/validate_symbols.py passes for it.

* DEMO_UNIVERSE: fictional India-themed securities with a ".DEMO" suffix used by the deterministic
  demonstration mode. They have no connection to real companies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config.market import CURRENCY


@dataclass(frozen=True)
class Security:
    ticker: str               # provider symbol, e.g. RELIANCE.NS
    name: str
    sector: str               # peer group used for peer comparisons and the sector index
    search_name: str          # name used in news searches
    is_synthetic: bool = False
    industry: str = ""        # NSE industry label from the NIFTY 50 constituent list
    aliases: tuple[str, ...] = ()    # names that identify the company in headlines
    exclude: tuple[str, ...] = ()    # other companies whose names contain an alias (removed before matching)

    @property
    def exchange_symbol(self) -> str:
        """NSE trading symbol without the provider suffix (RELIANCE.NS -> RELIANCE)."""
        return re.sub(r"\.(NS|BO|DEMO)$", "", self.ticker)

    @property
    def match_names(self) -> tuple[str, ...]:
        return self.aliases or (self.search_name,)


@dataclass(frozen=True)
class Universe:
    key: str
    label: str
    securities: tuple[Security, ...]
    benchmark: str
    benchmark_name: str
    sector_indices: dict[str, str]          # peer group -> sector index symbol (groups without one are absent)
    sector_index_names: dict[str, str]
    portfolio: dict[str, float] = field(default_factory=dict)
    portfolio_value: float = 10_000_000.0   # ₹1 crore, illustrative
    sector_source: str = ""
    other_indices: dict[str, str] = field(default_factory=dict)   # display-only indices: symbol -> name
    currency: str = CURRENCY
    constituent_note: str = ""

    @property
    def tickers(self) -> list[str]:
        return [s.ticker for s in self.securities]

    @property
    def index_symbols(self) -> list[str]:
        out: list[str] = []
        for sym in [self.benchmark] + list(self.sector_indices.values()) + list(self.other_indices):
            if sym not in out:
                out.append(sym)
        return out

    @property
    def all_symbols(self) -> list[str]:
        """Stocks, benchmark, sector indices and display indices, without duplicates."""
        seen: list[str] = []
        for sym in self.tickers + self.index_symbols:
            if sym not in seen:
                seen.append(sym)
        return seen

    @property
    def sectors(self) -> list[str]:
        out: list[str] = []
        for s in self.securities:
            if s.sector not in out:
                out.append(s.sector)
        return out

    def get(self, ticker: str) -> Security | None:
        for s in self.securities:
            if s.ticker == ticker:
                return s
        return None

    def resolve(self, symbol: str | None) -> str | None:
        """Accept a provider symbol or a bare NSE symbol (RELIANCE -> RELIANCE.NS); None if unknown."""
        if not symbol:
            return None
        sym = symbol.strip().upper()
        if sym in self.all_symbols:
            return sym
        for s in self.securities:
            if s.exchange_symbol.upper() == sym:
                return s.ticker
        return None

    def sector_of(self, ticker: str) -> str | None:
        sec = self.get(ticker)
        return sec.sector if sec else None

    def sector_index_for(self, ticker: str) -> str | None:
        sector = self.sector_of(ticker)
        return self.sector_indices.get(sector) if sector else None

    def peers_of(self, ticker: str) -> list[str]:
        sector = self.sector_of(ticker)
        return [s.ticker for s in self.securities if s.sector == sector and s.ticker != ticker]

    def display_name(self, symbol: str) -> str:
        sec = self.get(symbol)
        if sec:
            return sec.name
        if symbol == self.benchmark:
            return self.benchmark_name
        for sector, idx in self.sector_indices.items():
            if idx == symbol:
                return self.sector_index_names.get(sector, f"{sector} sector index")
        if symbol in self.other_indices:
            return self.other_indices[symbol]
        return symbol

    def short_label(self, symbol: str | None) -> str:
        """Compact label for charts and tables: RELIANCE.NS -> RELIANCE, ^NSEI -> NIFTY 50."""
        if not symbol:
            return ""
        if symbol in self.index_symbols:
            name = self.display_name(symbol)
            return name.split(" (")[0]
        return re.sub(r"\.(NS|BO|DEMO)$", "", symbol)


def _s(ticker, name, sector, search, industry, aliases=(), exclude=()):
    return Security(ticker, name, sector, search, False, industry, tuple(aliases), tuple(exclude))


FIN, IT, ENERGY, FMCG, AUTO, HEALTH = ("Financials", "IT services", "Oil, gas & power", "FMCG", "Autos",
                                       "Pharma & healthcare")
DURABLES, MATERIALS, CONSTRUCTION, TELECOM = ("Consumer durables", "Cement & steel", "Construction", "Telecom")

_LIVE_SECURITIES = (
    _s("HDFCBANK.NS", "HDFC Bank Ltd.", FIN, "HDFC Bank", "Financial Services", ["HDFC Bank"]),
    _s("ICICIBANK.NS", "ICICI Bank Ltd.", FIN, "ICICI Bank", "Financial Services", ["ICICI Bank"]),
    _s("SBIN.NS", "State Bank of India", FIN, "State Bank of India", "Financial Services",
       ["State Bank of India", "SBI"],
       ["SBI Life", "SBI Card", "SBI Cards", "SBI Mutual Fund", "SBI MF", "SBI General", "SBI Funds"]),
    _s("AXISBANK.NS", "Axis Bank Ltd.", FIN, "Axis Bank", "Financial Services", ["Axis Bank"]),
    _s("KOTAKBANK.NS", "Kotak Mahindra Bank Ltd.", FIN, "Kotak Mahindra Bank", "Financial Services",
       ["Kotak Mahindra Bank", "Kotak Bank"], ["Kotak Securities", "Kotak Mahindra AMC", "Kotak Mutual Fund"]),
    _s("BAJFINANCE.NS", "Bajaj Finance Ltd.", FIN, "Bajaj Finance", "Financial Services", ["Bajaj Finance"],
       ["Bajaj Finserv", "Bajaj Housing Finance"]),
    _s("INFY.NS", "Infosys Ltd.", IT, "Infosys", "Information Technology", ["Infosys", "Infy"]),
    _s("TCS.NS", "Tata Consultancy Services Ltd.", IT, "Tata Consultancy Services", "Information Technology",
       ["Tata Consultancy Services", "TCS"]),
    _s("HCLTECH.NS", "HCL Technologies Ltd.", IT, "HCL Technologies", "Information Technology",
       ["HCL Technologies", "HCLTech", "HCL Tech"]),
    _s("RELIANCE.NS", "Reliance Industries Ltd.", ENERGY, "Reliance Industries", "Oil, Gas & Consumable Fuels",
       ["Reliance Industries", "RIL", "Reliance Jio", "Jio Platforms", "Reliance Retail"],
       ["Reliance Power", "Reliance Infrastructure", "Reliance Infra", "Reliance Capital", "Reliance Communications",
        "Reliance Home Finance", "Jio Financial", "Reliance General Insurance", "Reliance Nippon"]),
    _s("ONGC.NS", "Oil & Natural Gas Corporation Ltd.", ENERGY, "ONGC", "Oil, Gas & Consumable Fuels",
       ["ONGC", "Oil and Natural Gas Corporation", "Oil & Natural Gas Corporation"]),
    _s("NTPC.NS", "NTPC Ltd.", ENERGY, "NTPC", "Power", ["NTPC"], ["NTPC Green"]),
    _s("POWERGRID.NS", "Power Grid Corporation of India Ltd.", ENERGY, "Power Grid Corporation", "Power",
       ["Power Grid", "PowerGrid", "POWERGRID"], ["PowerGrid InvIT", "Power Grid Infrastructure Investment Trust"]),
    _s("ITC.NS", "ITC Ltd.", FMCG, "ITC", "Fast Moving Consumer Goods", ["ITC"], ["ITC Hotels", "ITC Infotech"]),
    _s("HINDUNILVR.NS", "Hindustan Unilever Ltd.", FMCG, "Hindustan Unilever", "Fast Moving Consumer Goods",
       ["Hindustan Unilever", "HUL"]),
    _s("MARUTI.NS", "Maruti Suzuki India Ltd.", AUTO, "Maruti Suzuki", "Automobile and Auto Components",
       ["Maruti Suzuki", "Maruti"]),
    _s("M&M.NS", "Mahindra & Mahindra Ltd.", AUTO, "Mahindra & Mahindra", "Automobile and Auto Components",
       ["Mahindra & Mahindra", "Mahindra and Mahindra", "M&M"],
       ["Mahindra & Mahindra Financial", "M&M Financial", "M&M Finance", "Mahindra Finance", "Tech Mahindra",
        "Mahindra Lifespace", "Mahindra Holidays", "Mahindra Logistics", "Kotak Mahindra"]),
    _s("SUNPHARMA.NS", "Sun Pharmaceutical Industries Ltd.", HEALTH, "Sun Pharma", "Healthcare",
       ["Sun Pharma", "Sun Pharmaceutical"], ["Sun Pharma Advanced Research", "SPARC"]),
    _s("DRREDDY.NS", "Dr. Reddy's Laboratories Ltd.", HEALTH, "Dr Reddy's", "Healthcare",
       ["Dr Reddy's", "Dr. Reddy's", "Dr Reddys", "Dr. Reddy"]),
    _s("TITAN.NS", "Titan Company Ltd.", DURABLES, "Titan Company", "Consumer Durables", ["Titan Company", "Titan"],
       ["Titan Biotech", "Titan Intech", "Titan Securities", "Titanic"]),
    _s("ASIANPAINT.NS", "Asian Paints Ltd.", DURABLES, "Asian Paints", "Consumer Durables", ["Asian Paints"]),
    _s("ULTRACEMCO.NS", "UltraTech Cement Ltd.", MATERIALS, "UltraTech Cement", "Construction Materials",
       ["UltraTech", "Ultratech Cement"]),
    _s("JSWSTEEL.NS", "JSW Steel Ltd.", MATERIALS, "JSW Steel", "Metals & Mining", ["JSW Steel"]),
    _s("LT.NS", "Larsen & Toubro Ltd.", CONSTRUCTION, "Larsen & Toubro", "Construction",
       ["Larsen & Toubro", "Larsen and Toubro", "L&T"],
       ["L&T Finance", "L&T Technology Services", "L&T Tech", "LTTS", "LTIMindtree", "L&T Mutual Fund"]),
    _s("BHARTIARTL.NS", "Bharti Airtel Ltd.", TELECOM, "Bharti Airtel", "Telecommunication",
       ["Bharti Airtel", "Airtel"], ["Bharti Hexacom", "Airtel Africa"]),
)

LIVE_UNIVERSE = Universe(
    key="live",
    label="NSE large caps: 25 NIFTY 50 stocks, NIFTY 50 benchmark, 3 NSE sector indices and SENSEX",
    securities=_LIVE_SECURITIES,
    benchmark="^NSEI",
    benchmark_name="NIFTY 50 (broad-market benchmark)",
    # ENERGY, FMCG and AUTO have no sector index: see the module note on the 20 Oct 2026 symbol check.
    sector_indices={
        FIN: "^NSEBANK",
        IT: "^CNXIT",
        HEALTH: "^CNXPHARMA",
    },
    sector_index_names={
        FIN: "NIFTY Bank (sector index for the five banks; Bajaj Finance is a non-bank lender)",
        IT: "NIFTY IT (sector index)",
        HEALTH: "NIFTY Pharma (sector index)",
    },
    other_indices={"^BSESN": "BSE SENSEX (display only)"},
    # Illustrative, hypothetical portfolio used only by the Risk Scenario Lab. Weights add up to 100%.
    portfolio={
        "HDFCBANK.NS": 0.12, "RELIANCE.NS": 0.12, "ICICIBANK.NS": 0.10, "INFY.NS": 0.09, "TCS.NS": 0.08,
        "BHARTIARTL.NS": 0.07, "LT.NS": 0.07, "ITC.NS": 0.06, "SBIN.NS": 0.06, "MARUTI.NS": 0.05,
        "SUNPHARMA.NS": 0.05, "TITAN.NS": 0.05, "ULTRACEMCO.NS": 0.04, "NTPC.NS": 0.04,
    },
    portfolio_value=10_000_000.0,
    sector_source=(
        "Peer groups follow the NSE industry labels of the NIFTY 50 constituent list (8 Dec 2025 list, checked "
        "against 2026 NSE Indices press releases on 20 Oct 2026). 'Oil, gas & power' combines Oil, Gas & Consumable "
        "Fuels with Power; 'Cement & steel' combines Construction Materials with Metals & Mining. Construction (L&T) "
        "and Telecom (Bharti Airtel) have no peer in the watchlist."
    ),
    constituent_note=(
        "Representative watchlist of 25 NIFTY 50 constituents, configured manually and checked on 20 Oct 2026. "
        "Wipro left the NIFTY 50 on 30 Sep 2026 and is not included."
    ),
)

# ---------------------------------------------------------------------------
# Fictional India-themed demonstration universe
# ---------------------------------------------------------------------------

D_FIN, D_IT, D_ENERGY, D_FMCG, D_AUTO, D_HEALTH, D_CAPGOODS = (
    "Financials", "IT services", "Oil, gas & power", "FMCG", "Autos", "Pharma & healthcare", "Capital goods")


def _d(ticker, name, sector, search):
    return Security(ticker, f"{name} (fictional)", sector, name, True, sector, (name,), ())


_DEMO_SECURITIES = (
    _d("SAFFRON.DEMO", "Saffron Bank", D_FIN, "Saffron Bank"),
    _d("BANYAN.DEMO", "Banyan Bank", D_FIN, "Banyan Bank"),
    _d("PEACOCK.DEMO", "Peacock Finance", D_FIN, "Peacock Finance"),
    _d("BODHI.DEMO", "Bodhi Infotech", D_IT, "Bodhi Infotech"),
    _d("LOTUSSW.DEMO", "Lotus Softworks", D_IT, "Lotus Softworks"),
    _d("MONSOON.DEMO", "Monsoon Systems", D_IT, "Monsoon Systems"),
    _d("GRIDSTAR.DEMO", "Gridstar Power", D_ENERGY, "Gridstar Power"),
    _d("COASTPET.DEMO", "Coastline Petroleum", D_ENERGY, "Coastline Petroleum"),
    _d("SUNVOLT.DEMO", "Sunvolt Energy", D_ENERGY, "Sunvolt Energy"),
    _d("MANGO.DEMO", "Mango Orchard Foods", D_FMCG, "Mango Orchard Foods"),
    _d("NEEM.DEMO", "Neem Home Care", D_FMCG, "Neem Home Care"),
    _d("GHATMTR.DEMO", "Ghat Road Motors", D_AUTO, "Ghat Road Motors"),
    _d("RIKSHA.DEMO", "Rickshaw Mobility", D_AUTO, "Rickshaw Mobility"),
    _d("CURELINE.DEMO", "Cureline Pharma", D_HEALTH, "Cureline Pharma"),
    _d("AYURA.DEMO", "Ayura Life Sciences", D_HEALTH, "Ayura Life Sciences"),
    _d("IRONBRG.DEMO", "Ironbridge Engineering", D_CAPGOODS, "Ironbridge Engineering"),
    _d("RIVERLN.DEMO", "Riverline Infra", D_CAPGOODS, "Riverline Infra"),
)

DEMO_UNIVERSE = Universe(
    key="demo",
    label="Synthetic demonstration universe (17 fictional India-themed stocks, fictional index and sector indices)",
    securities=_DEMO_SECURITIES,
    benchmark="MKT.DEMO",
    benchmark_name="Synthetic broad-market index (fictional)",
    sector_indices={
        D_FIN: "BANKIDX.DEMO",
        D_IT: "ITIDX.DEMO",
        D_ENERGY: "ENRGIDX.DEMO",
        D_FMCG: "FMCGIDX.DEMO",
        D_AUTO: "AUTOIDX.DEMO",
        D_HEALTH: "PHRMIDX.DEMO",
    },
    sector_index_names={
        D_FIN: "Synthetic bank index (fictional)",
        D_IT: "Synthetic IT index (fictional)",
        D_ENERGY: "Synthetic energy index (fictional)",
        D_FMCG: "Synthetic FMCG index (fictional)",
        D_AUTO: "Synthetic auto index (fictional)",
        D_HEALTH: "Synthetic pharma index (fictional)",
    },
    portfolio={
        "SAFFRON.DEMO": 0.12, "BANYAN.DEMO": 0.08, "BODHI.DEMO": 0.10, "LOTUSSW.DEMO": 0.10,
        "GRIDSTAR.DEMO": 0.08, "COASTPET.DEMO": 0.08, "MANGO.DEMO": 0.08, "GHATMTR.DEMO": 0.08,
        "CURELINE.DEMO": 0.10, "IRONBRG.DEMO": 0.10, "PEACOCK.DEMO": 0.08,
    },
    portfolio_value=10_000_000.0,
    sector_source="Fictional peer groups that exist only in the demonstration dataset. Capital goods has no "
                  "sector index, like several live groups, so the demo also shows a peer-only comparison.",
    constituent_note="Fictional securities. SYNTHETIC DEMONSTRATION DATA.",
)


def get_universe(mode: str) -> Universe:
    return DEMO_UNIVERSE if mode == "demo" else LIVE_UNIVERSE
