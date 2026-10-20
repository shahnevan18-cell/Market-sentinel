# Data-source register (India version)

Conversion date: 20 October 2026. The build sandbox cannot reach Yahoo Finance, Google News or the NSE website (its
network proxy blocks them), and the web-fetch tool used for research is refused by Yahoo and Google News under their
robots rules. Exchange facts below were therefore checked against official NSE, NSE Indices and SEBI pages and
circulars, and every live data source is checked from the team laptop with `scripts/validate_symbols.py` and
`scripts/smoke_test.py`, whose results are written to `docs/symbol_validation_result.md` and
`docs/live_smoke_test_result.md` with the time of the run.

| Source | Link | Used for | Access and terms | Checked | Limits |
|---|---|---|---|---|---|
| Yahoo Finance via the yfinance library (1.x) | https://github.com/ranaroussi/yfinance | Daily open, high, low, close, adjusted close, volume, dividends, splits, currency, exchange and exchange time zone for NSE shares (`.NS`), NIFTY 50 (`^NSEI`), NSE sector indices and SENSEX (`^BSESN`) | Open-source client for publicly available Yahoo data, not affiliated with Yahoo or NSE. No key. Personal and educational use | Symbols checked on the laptop with `scripts/validate_symbols.py` | Data can be delayed or revised against NSE's official bhavcopy; Yahoo throttles heavy use; endpoints can change without notice |
| Yahoo Finance intraday bars via yfinance (optional) | https://github.com/ranaroussi/yfinance | 5-minute open, high, low, close and volume for NIFTY 50 and the 25 shares, for the Intraday watch on the Market overview (`history(period=..., interval="5m")`, regular session only) | As for yfinance. Requested only while the page is open, at most once per bar interval for all users together, with a small worker pool and a throttle | `scripts/intraday_check.py` on the laptop writes `docs/intraday_check_result.md` (the sandbox cannot reach Yahoo) | Unofficial and possibly delayed, not a real-time exchange feed; Yahoo keeps about 60 days of 5-minute bars; no index volume; bars can arrive late or be missing, and missing bars are never filled |
| Google News RSS search, India edition | https://news.google.com/rss/search (`hl=en-IN&gl=IN&ceid=IN:en`) | Headlines, publisher, publication time and links around an event date, using the after: and before: operators | Public RSS feed; used at low volume for non-commercial academic work | Laptop smoke test | Coverage and ranking are Google's; links are Google redirect URLs; absence of a headline does not prove absence of news |
| Yahoo Finance headlines via yfinance | https://github.com/ranaroussi/yfinance | Latest headlines for a ticker (recent events only) | As for yfinance | Laptop smoke test | Only the most recent headlines; cannot reconstruct older windows |
| NSE corporate announcements | https://www.nseindia.com/companies-listing/corporate-filings-announcements | Link for a manual check of company announcements around an event | Link-only. NSE's terms of use, clause 9: "User is prohibited to conduct any systematic or automated data collection activities (including scraping, data mining, data extraction and data harvesting)". The app never fetches this page or NSE's internal endpoints | Terms read 20 Oct 2026 | Not an automated filing search; the user searches by company and date range |
| NSE financial results | https://www.nseindia.com/companies-listing/corporate-filings-financial-results | Link for a manual check of quarterly results | Link-only, as above | 20 Oct 2026 | Manual |
| BSE financial results and corporate filings | https://www.bseindia.com/corporates/Comp_Resultsnew.aspx, https://www.bseindia.com/corporates.html | Links for a manual check on BSE | Link-only. BSE's terms page could not be retrieved for review, so the same link-only rule is applied | 20 Oct 2026 | Manual |
| SEBI directory of corporate filings | https://www.sebi.gov.in/curation/corporate_filings.html | Where each filing type is published on NSE and BSE (the NSE and BSE links above come from this page) | Public reference page, link-only | 20 Oct 2026 | Reference only |
| NSE market timings | https://www.nseindia.com/static/market-data/market-timings | Session rules in `config/market.py`: normal market 09:15 to 15:30 IST, closing session 15:40 to 16:00, trade modifications until 16:15 | Read once by hand | 20 Oct 2026 | The app treats a daily bar as final after 16:15 IST |
| NSE trading-holiday circulars | NSE/CMTR/59722 (2024), NSE/CMTR/64960 (20 Nov 2024 election holiday), NSE/CMTR/65587 (2025), NSE/CMTR/71775 (2026), NSE/CMTR/72260 (15 Jan 2026 election holiday) on https://nsearchives.nseindia.com/content/circulars/ | The holiday table in `config/market.py` (Capital Market segment, weekday holidays) | Official circulars, copied by hand | 20 Oct 2026 | Covers 2024 to 2026 only; the 2024 list was read from a broker's copy of the circular. Muhurat trading on Sunday 8 Nov 2026 is announced; its timings are not yet notified |
| NSE Indices press releases | https://niftyindices.com/Press_Release/ind_prs10082026.pdf and the releases of 23 Feb, 12 Mar and 15 Sep 2026 | NIFTY 50 membership of the watchlist: Wipro excluded and BSE Ltd included from 30 Sep 2026; no NIFTY 50 change in the February and March 2026 reviews | Public PDFs | 20 Oct 2026 | The official constituent CSV could not be downloaded automatically, so the watchlist is a representative, manually configured list |
| Synthetic demonstration generator | `providers/market_data.py` | 17 fictional India-themed `.DEMO` securities, a fictional market index and sector indices, three fictional announcements | Built in, fixed random seed 20, NSE trading calendar | Built 20 Oct 2026 | Not market data; exists for offline demonstrations and tests. No real company appears in it |
| Anthropic Messages API (optional) | https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview | Tool selection, headline relevance and narrative | API key with credit; a claude.ai chat subscription does not include API access | Documentation reviewed | Usage is billed per token; output is checked but can still contain mistakes |
| OpenAI-compatible endpoints (optional) | https://ai.google.dev/gemini-api/docs/openai | Same role with other providers (Gemini, Groq, OpenRouter, OpenAI, Ollama) | Provider key and model name in `.env` or the hosting secrets; `GEMINI_API_KEY` alone selects Gemini with gemini-3.5-flash. Free-tier limits are per Google project and daily limits reset at midnight US Pacific time (https://ai.google.dev/gemini-api/docs/rate-limits) | gemini-3.8-flash and gemini-3.5-flash run on 20 Oct 2026 (see the test report) | Free tiers limit requests per minute and per day; tool-calling quality varies by model |

## Watchlist and provider symbols

The 25 shares are NIFTY 50 constituents, chosen from the candidate list in the project brief plus HCL Technologies
(third IT stock after Wipro left the index) and Dr. Reddy's (a peer for Sun Pharma). Company names, NSE symbols and
industry labels follow the NIFTY 50 constituent table dated 8 December 2025, checked against the 2026 press releases
above. Provider symbols are the NSE symbol plus `.NS`; M&M is `M&M.NS`.

| Peer group | Shares | Sector index |
|---|---|---|
| Financials | HDFC Bank, ICICI Bank, State Bank of India, Axis Bank, Kotak Mahindra Bank, Bajaj Finance | NIFTY Bank `^NSEBANK` (holds the five banks; Bajaj Finance is a non-bank lender) |
| IT services | Infosys, TCS, HCL Technologies | NIFTY IT `^CNXIT` |
| Oil, gas & power | Reliance Industries, ONGC, NTPC, Power Grid | none (peer comparison only; see below) |
| FMCG | ITC, Hindustan Unilever | none (peer comparison only; see below) |
| Autos | Maruti Suzuki, Mahindra & Mahindra | none (peer comparison only; see below) |
| Pharma & healthcare | Sun Pharmaceutical, Dr. Reddy's | NIFTY Pharma `^CNXPHARMA` |
| Consumer durables | Titan, Asian Paints | none (peer comparison only) |
| Cement & steel | UltraTech Cement, JSW Steel | none (peer comparison only) |
| Construction | Larsen & Toubro | none, and no peer in the watchlist |
| Telecom | Bharti Airtel | none, and no peer in the watchlist |

Two groups combine NSE industries so that every stock in them has a peer: Oil, Gas & Consumable Fuels with Power,
and Construction Materials with Metals & Mining. A symbol that fails `scripts/validate_symbols.py` must be corrected
or removed from `config/watchlist.py`; at run time it appears as unavailable and is never filled in.

The live check on the team laptop on 20 Oct 2026 at 15:59 IST passed 30 of the 33 symbols then configured: all 25
shares, the NIFTY 50, NIFTY Bank, NIFTY IT, NIFTY Pharma and the SENSEX (511 to 514 sessions each, INR, NSE or BSE,
Asia/Kolkata). NIFTY Energy (`^CNXENERGY`), NIFTY FMCG (`^CNXFMCG`) and NIFTY Auto (`^CNXAUTO`) returned only three
sessions (15 to 19 Oct 2026), too few to estimate a beta or a sector z-score, so they were removed and their groups use
peers only. They can be re-added if the check passes for them again.

## Timestamps

Bar dates are NSE trading sessions. Yahoo stamps each NSE daily bar at midnight India time, and the app reads the date
in the exchange's own time zone (the US version converted to New York time, which moved every Indian bar to the
previous day; a regression test now covers this). Publication and retrieval times are stored in UTC and shown in IST.
A daily bar retrieved before 16:15 IST on its own date is treated as incomplete. Each cached file keeps its original
retrieval time, so a stale cached copy is never shown as fresh.

## What is stored

Price series are cached as CSV files in `data/cache/market/yfinance/`, and each completed investigation as JSON in
`data/investigations/`. For news, only headlines, publishers, timestamps, links and short feed snippets are stored.
Article text is not downloaded, and nothing is downloaded from NSE or BSE.
