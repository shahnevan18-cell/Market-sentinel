# Live smoke test result

Run at 2026-10-20 10:30:26 UTC (20 Oct 2026, 16:00 IST) on Windows 11, Python 3.15.0.
Package versions: yfinance 1.7.0, pandas 3.0.6, numpy 2.5.4, streamlit 1.66.0, plotly 7.1.0, requests 2.34.2, pydantic 2.14.1.
LLM configuration: gemini-3.8-flash via OpenAI-compatible API (https://generativelanguage.googleapis.com/v1beta/openai/).

| Check | Result | Detail | Seconds |
|---|---|---|---|
| Market data: yfinance (^NSEI, RELIANCE.NS, currency INR) | PASS | ^NSEI 29 rows, last bar 2026-10-19, currency INR, time zone Asia/Kolkata; RELIANCE.NS 29 rows, last bar 2026-10-19, exchange NSE | 3.9 |
| News: Google News RSS search, India edition | PASS | 100 headline(s) in the last 7 days from the India edition; first: 'India's Reliance, Airtel rally as Jio Platforms IPO recasts valuations' (Reuters) | 1.0 |
| News: Yahoo Finance headlines via yfinance | PASS | 0 latest headline(s) for RELIANCE.NS | 1.4 |
| Disclosures: NSE/BSE announcements | LINK-ONLY | Not retrieved automatically (NSE terms of use, clause 9); the app links to the official pages. | 0.0 |
| Pipeline: load full live watchlist (cache-first) | PASS | 33/33 symbols, latest bar 2026-10-19, statuses {'live': 33}, failures 0 | 15.5 |
| Pipeline: Sentinel Monitor scan | PASS | 599 alert(s) in the history; 1 in the latest session | 4.9 |
| Pipeline: rule-based investigation of a recent alert | PASS | ITC.NS:2026-10-05: leading 'Company-specific news or announcement' (Moderate); engine rules/rules; 55 news item(s); sources: Google News RSS (India edition)=ok, Yahoo Finance headlines (yfinance)=skipped, NSE/BSE official disclosures (link-only)=link_only; saved ITC-NS-2026-10-05_20261020T103058.json | 5.2 |
| Pipeline: LLM investigation | SKIPPED | --no-llm flag | 0.0 |
