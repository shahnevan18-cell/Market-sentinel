# Limitations and responsible use

## What the results mean

An alert says that a move was statistically unusual for that stock compared with its own recent history. It says
nothing about why. Many unusual moves have no discoverable public cause, and the app reports that outcome as a valid
finding. An anomaly is never evidence of fraud, manipulation or insider trading, and the app never says so.

Hypothesis scores measure how well each explanation fits the evidence that was gathered. They are not probabilities,
and the leading explanation is an assessment, not proof of cause. A conclusion is only stated when one explanation
clearly leads; otherwise the report says the evidence is insufficient.

The priority score ranks alerts for attention. It is not a measure of importance to any investor and not a forecast.

## Data limits

- Yahoo data obtained through yfinance is unofficial, can be delayed or revised against NSE's official bhavcopy, and can be throttled. It is intended for personal, research and educational use.
- Official NSE and BSE announcements are not retrieved automatically. NSE's terms of use prohibit systematic or automated data collection, so the app links to the official pages instead. A filing on the exchange website can explain a move that the app reports as unexplained, which is why every report points to those pages for a manual check.
- Daily bars cannot show whether news arrived before or after the move within a session. The information window (previous session's 15:30 IST close to the event-day close) is the finest timing the app can establish.
- Headline relevance is judged from titles, publishers and publication times. Article text is not read, and a publication time is not always the date of the event a headline reports. A headline can therefore only ever be a potential catalyst (evidence level B), never a verified one; in live mode no explanation is marked verified, because official announcements are link-only.
- The catalyst picker prefers the subject most independent publishers report and ignores social-media posts, tips and forecast pages. Publisher counts are a proxy for corroboration, not for reliability, and a widely repeated report can still be wrong.
- The recommended next action comes from fixed rules over the record. It names the most useful check given what the record leaves open; it cannot see evidence the app never retrieved, and it is not investment advice.
- Google News results depend on Google's ranking; an empty search does not prove that no news existed.
- The watchlist is a manually configured set of 25 NIFTY 50 constituents, checked on 20 October 2026. Index membership changes twice a year and must be rechecked.
- Peer groups are project configuration and small (one to six stocks). Larsen & Toubro and Bharti Airtel have no peer in the watchlist, and seven of the ten groups have no sector index (three because Yahoo's history for NIFTY Energy, FMCG and Auto was only three sessions on 20 Oct 2026), so for them the sector explanation rests on less evidence.
- NIFTY sector indices are weighted by free-float market capitalisation and include the stock being studied.
- Corporate actions are handled through the adjusted close. A bonus issue, split or demerger the provider does not adjust appears as a large one-day move and is flagged for manual checking, not corrected.
- The NSE holiday table covers 2024 to 2026. Later years need the new circular; until then every weekday is treated as a possible session and the NIFTY 50's own dates decide which sessions exist.

## Statistical limits

- The robust z-score assumes the previous 60 sessions are a fair picture of normal behaviour. After a regime change, alerts can cluster until the baseline catches up.
- Beta from 120 sessions moves over time and is unreliable when R-squared is low; the report warns when it is below 0.10.
- With 25 stocks and roughly 245 sessions a year, a 3-sigma rule produces false alarms by chance alone, especially because returns have fat tails. The threshold sensitivity tab shows the trade-off.
- Historical VaR and volatility describe the past. They understate risk when markets become more volatile.
- The replay is descriptive on live data. There is no ground-truth label for a correct alert, so no accuracy figure is claimed for NSE data. The recall check in demonstration mode measures the detector against planted shocks only.

## LLM limits

- The LLM can misjudge relevance or write misleading prose. Its relevance judgements are logged with rationales, its figures are checked against tool outputs (including rupee amounts in lakh and crore and Indian digit grouping), and the final scores come from the fixed rubric.
- Headlines are untrusted text. The model is instructed not to follow instructions inside them, and it can only act through the registered tools, none of which can trade, send messages or change data.
- Free tiers limit requests. On HTTP 429 the client waits as long as the provider asks, up to 65 seconds and twice; a longer wait or a used-up daily quota ends the model step, and the report shows the labelled rule-based output with the reason.
- On 20 October 2026, gemini-3.5-flash completed both agents itself on the India demo data (PASS). On live NSE data the investigator ran five turns before the free tier's daily quota ran out; the app reported this and fell back to the labelled rule-based output. The daily quota resets at midnight Pacific time (12:30 IST).
- Without an LLM key, the investigation is a fixed protocol over the same tools. It is labelled as such and should not be described as AI reasoning.

## Responsible use

- Use Market Sentinel for learning and for structuring an analyst's checks, never as a basis for trading.
- Read the audit trail and the data-quality notes before relying on any conclusion, and check the official NSE or BSE announcements before quoting a cause.
- Treat demonstration mode as a software demonstration. Its securities and announcements are fictional and no real company appears in it.
- Keep API keys in `.env` or in hosting secrets, never in code or screenshots.
- Respect the providers' terms: low request volumes, no scraping of exchange websites, and no redistribution of downloaded data.
