# Viva guide (India version)

This guide explains Market Sentinel in plain language, walks through one alert from raw prices to the final report,
and prepares answers to the questions an evaluator is likely to ask.

## The one-minute explanation

Markets produce hundreds of price moves a day on the NSE, and most are noise. Market Sentinel watches 25 NIFTY 50
companies and asks, every session, which moves were genuinely unusual for that particular stock. It measures
"unusual" by comparing today with the stock's own previous 60 trading sessions. When something stands out, an analyst
can open an investigation. Three roles then work in sequence. The Sentinel Monitor has already found and ranked the
event. The Market Investigator collects evidence with tools: it compares the stock with the NIFTY 50, its NSE sector
index and its peers, and searches Indian news headlines around the date. Five possible explanations are scored with a
fixed rubric. The Risk Strategist then asks what the event means for risk: how large it was against normal daily
risk, whether volatility has shifted, and how exposed an illustrative ₹1 crore portfolio would be. The report keeps
facts, hypotheses and unknowns apart and shows every step that ran.

## How the parts fit together

Think of a small research desk. The monitor is the screen that flashes when something moves oddly. The investigator
is the analyst who pulls the charts, checks the NIFTY and the competitors, and reads the news. The strategist is the
risk manager who reads the analyst's notes and asks what to watch next. The orchestrator is the desk head who hands
out the work, insists that the standard checks are done, keeps a log of everything and refuses to sign off a note
whose numbers do not match the data.

The tools are ordinary Python functions. The agents can only act by calling them, and every call is checked: the tool
must exist, the arguments must match its schema, and there is a budget on the number of calls. The results go into a
shared evidence store, so the rubric, the strategist and the report all use exactly the numbers the investigator saw.

Everything specific to the Indian market sits in two files. `config/market.py` holds the time zone (Asia/Kolkata),
the session (09:15 to 15:30 IST, bar final at 16:15), the NSE holiday table, the currency and the official
disclosure links. `config/watchlist.py` holds the 25 shares, the NIFTY indices, the peer groups and the company
aliases. The statistics and the agents read those files, which is why converting the project from US to Indian
markets did not need new analytics.

## What makes it agentic, and what does not

With an LLM key configured, the investigator receives a goal (explain this alert) and a set of tools, and decides for
itself which tools to call, in what order, with what arguments, and when it has enough evidence. It can, for example,
pick its own peer list or refine a news search after seeing the first results. It also reads each headline and
decides whether it is a direct, indirect or unrelated explanation, giving a reason. That loop of deciding, acting,
observing and deciding again is what makes it an agent.

Three things are deliberately kept away from the LLM. Detection is statistical, so alerts are reproducible. Numbers
are computed in Python, and a grounding check flags any figure in the LLM's text that matches no tool output, in
rupee, lakh and crore formats too. Hypothesis scores come from a fixed rubric, so the conclusion can be audited
criterion by criterion.

Without an LLM key, or when the rule-based protocol is chosen in the sidebar, a fixed protocol calls the same tools in
a set order and writes the narrative from templates. Each report names the engine that actually ran and why:
model-directed, a fallback after a provider error (with the reason), a fallback because the model's output could not
be used, the rule-based protocol chosen by the user, or no credentials configured. Having a key is never reported as
the model having run. This is the honest fallback for a live demonstration without paid API access.

## Worked example: Saffron Bank (fictional), 30 September 2026

This example uses the synthetic demonstration dataset, so every number below is synthetic and refers to a fictional
company. It is fully reproducible: switch the data source to Demonstration data, open the workspace and run the
preselected alert. After running the app on live NSE data, repeat the same walk-through on a real alert from the
report's Evidence and Hypotheses tabs.

### Step 1: from prices to a return

Adjusted close on 29 September: ₹61.7327. On 30 September: ₹56.0784.

r = 56.0784 / 61.7327 - 1 = -0.0916, a fall of 9.16%. The log return is -0.0961.

### Step 2: is the fall unusual for this stock?

Baseline: the 60 NSE sessions from 7 July to 29 September 2026 (30 September itself is excluded, and holidays such as
Ganesh Chaturthi on 14 September are not sessions). Median daily return in that window: +0.276%. Median absolute
deviation (MAD): 0.7317%.

Robust z = (-9.159% - 0.276%) / (1.4826 x 0.7317%) = -9.435% / 1.085% = -8.7.

A move of almost nine robust standard deviations is far beyond the alert threshold of 3.

### Step 3: was the volume unusual?

Volume was 1,75,95,416 shares against a 60-session median of 22,79,318, which is 7.7 times normal. On the log scale
the robust z-score is +8.5, so the volume test fires as well.

### Step 4: how much of the fall does the market explain?

The market model was estimated on the 120 sessions from 8 April to 29 September 2026: alpha +0.070% a day, beta
0.996, R-squared 0.52, residual standard deviation 0.899%.

The synthetic market index was flat that day (-0.01%). Expected return = 0.070% + 0.996 x (-0.010%) = +0.061%.

Abnormal return = -9.16% - 0.06% = -9.22%. Divided by the residual standard deviation: -9.22% / 0.899% = -10.3.

So the market explains none of the fall: it is entirely stock-specific.

### Step 5: did the sector and peers do the same?

The synthetic bank index fell 1.63% (robust z -1.78), an ordinary day. The two peers fell 1.32% and 0.58% (z -0.59
for both), a median of -0.95%. Relative to that median the bank fell a further 8.21%, a robust z of -7.1. 59% of the
watchlist rose that day.

### Step 6: priority score

| Component | Value | Normalised | Weight | Points |
|---|---|---|---|---|
| Price move, robust z | -8.70 | 1.00 (capped at 6) | 0.35 | 35.0 |
| Market-relative, z of abnormal return | -10.26 | 1.00 | 0.30 | 30.0 |
| Volume, robust z of log volume | +8.47 | 1.00 | 0.25 | 25.0 |
| Volatility regime, 10-day vs earlier 60-day | 2.04 | (2.04 - 1) / 2 = 0.52 | 0.10 | 5.2 |

Total 95.2 out of 100, so the severity is Critical.

### Step 7: news timing

The demo dataset holds a fictional announcement: "Saffron Bank (fictional) Q2 results: net profit falls as provisions
for bad loans rise sharply", published at 18:05 IST on 29 September after the board meeting that approved the
results. The information window for 30 September runs from the previous session's close (15:30 IST on 29 September)
to 15:30 IST on 30 September, so the item is inside it and is a company announcement. Relevance: direct. The record
keeps two dates: the publication time (29 September, 18:05 IST) and the event the announcement reports (the board
meeting on 29 September). Results declared after market hours affect the next session, which is why the window
starts at the previous close.

### Step 8: the rubric

| Hypothesis | Main criteria | Score |
|---|---|---|
| H3 Company-specific news | stock-specific strength min(10.3, 7.1) at least 3: +30; direct evidence in the window (the company's own announcement): +40; company announcement: +15; volume z at least 3: +15 | 100 |
| H4 Unexplained trading | volume z at least 3: +30; stock-specific: +20; direct evidence was found: -40; market and sector ordinary: +20 | 30 |
| H1 Broad market | market z -0.08, an ordinary day: -10; market explains none of the fall: -15; abnormal z beyond -3: -30; only 41% of stocks fell: -10 | 0 |
| H2 Sector | sector index z -1.8: 0; peers not strongly moving: 0; relative z -7.1: -30; sector moved more than the market: +20 | 0 |
| H5 Insufficient evidence | no criterion fired | 0 |

H3 leads with 100 and is 70 points ahead of H4, with no core input missing, so confidence is High. The report's
wording is "most consistent with company-specific news", not "caused by".

### Step 9: risk interpretation

Before the event, the one-day 95% historical VaR (250-session lookback) was 2.64%. The 9.16% fall was 3.5 times that
level, a sign that VaR based on calm history understated the tail. Recent 10-day volatility (48.6% annualised) is 2.04
times the earlier 60-day level (23.8%). In the illustrative ₹1 crore portfolio the bank is a 12% holding (28% in
financials), so the day cost 1.10% of the portfolio, about ₹1,09,911. A further hypothetical 10% fall would cost
another ₹1,20,000 (1.20%).

### How this conclusion could be wrong

- The announcement might be unrelated to the fall, or the market might have reacted to something else the same morning. Timing alone does not prove cause.
- Only two peers are configured, so the peer median is a weak reference.
- Beta is estimated from the past 120 sessions; if the bank's sensitivity to the market changed, the abnormal return is mis-measured.
- The baseline window may not be typical (for example, if it contained an earlier shock), which would change the z-scores.
- Daily data cannot show whether the price fell before or after any news within the day.
- In demo mode the announcement is fictional, so this example demonstrates the method, not a market fact. In live mode the app cannot read NSE announcements itself; an analyst would confirm the results filing on the NSE page linked in the report.

## Likely questions and answers

Why use the median and MAD instead of the mean and standard deviation?
Returns have fat tails. One crash inside the 60-day window inflates the standard deviation and makes the next shock
look ordinary. The median and MAD barely move when a few extreme days enter the window. The factor 1.4826 rescales
MAD so it matches a standard deviation for normal data, so a z of 3 still reads as roughly three standard deviations.

How do you avoid look-ahead bias?
Every baseline window ends the day before the day being tested, and beta is estimated only on earlier days. A test
recomputes all features on data cut off at a date and checks they are identical to the full-data values for that
date. Investigations launched from the replay run on a dataset physically truncated at the event date, and news
published after that day's close is not retrieved. The orchestrator also re-detects every alert on truncated data and
reports whether the score matches.

What is an abnormal return?
The part of a stock's return that the market does not explain. The market model predicts the return from beta times
the NIFTY 50's return; the abnormal return is the actual return minus that prediction. It is the standard tool of
event studies in finance.

Why the NIFTY 50, and not the SENSEX?
Both are free-float weighted large-cap indices; the NIFTY 50 is the NSE's own benchmark, our prices are NSE prices,
and every watchlist stock is a NIFTY 50 constituent. The SENSEX is loaded for display. Because each stock is part of
its benchmark, a heavyweight such as Reliance or HDFC Bank moves the index a little itself; beta absorbs most of this,
and the report notes it for sector indices.

Why three separate tests?
They catch different things. A large raw move can be the whole market falling. The market-relative test isolates
moves the market does not explain. The volume test catches heavy trading that has not yet moved the price.

What does the priority score mean?
A ranking for analyst attention on a 0 to 100 scale, built from normalised components with fixed weights shown in the
app. It is not a probability that a headline caused the move and not a prediction.

How did you choose the weights and thresholds?
They are judgement calls, documented and adjustable. A z of 3 is a common anomaly threshold; the weights put the most
emphasis on the size of the move and on the part the market cannot explain. The Risk scenario lab shows how the alert
count changes with the threshold, which is the honest way to discuss the trade-off between false alarms and missed
events.

How many false alarms do you get?
Under a normal distribution, a |z| of 3 or more happens on about 0.27% of days. Real returns have fatter tails, so
there are more. The replay page shows the alert rate per stock per 100 sessions. Whether an alert is a false alarm
needs a definition of a true event, and we do not invent one for NSE data. On the synthetic data the planted shocks
are known: the detector finds all six stock-specific shocks and 43 of 46 planted stock-days, and the precision is
low because random fat-tailed days also look unusual, as they do in real markets.

What does the LLM actually do?
It decides which tools to call and with which arguments, reads the results and picks the next step, for example
paging through the retrieved news or opening an announcement's details. It judges the relevance of each headline with a
reason, decides when it has enough evidence and writes the narrative. It never calculates numbers, and it does not
set the hypothesis scores.

How do you know the model really chose the tools?
The Audit trail tab's Model decisions section lists every model turn with the tools the model asked for and what they
returned. It is read from the audit log written while the calls ran. A rule-based run shows no model turns at all, and
the strip under the verdict says which engine produced each part of the report.

How do you stop the LLM from inventing numbers or sources?
It can only call registered tools, and every call is validated. Its final output must pass a schema check and a
numeric grounding check against the tool outputs; mismatches are sent back once for revision and anything left is
flagged in the report. Source links come from the providers, never from the model.

What happens if the LLM or a data source fails?
The orchestrator records the failure, runs any skipped checks itself and produces clearly labelled rule-based output.
If news cannot be searched, the report says "News evidence unavailable" and the rubric caps the explanations that
depend on news. If market data fails, the last cached copy is used with its original timestamp and a stale warning;
with no cache, the app says so and offers demonstration mode. It never substitutes synthetic prices on its own.

Is yfinance an official API?
No. It is an open-source library that reads publicly available Yahoo Finance data, including NSE shares under `.NS`
symbols and NIFTY indices. It can be delayed, revised against NSE's official bhavcopy or throttled, and the project's
documentation says the data is for personal and educational use. `scripts/validate_symbols.py` checks every
configured symbol (rows, currency INR, exchange, time zone) on the laptop, and the provider layer has a disk cache so
a failed refresh shows the last good copy with its original time.

Why don't you read NSE or BSE announcements directly?
NSE's terms of use (clause 9) prohibit systematic or automated data collection, including scraping, and neither
exchange offers a documented public API for announcements. Calling the website's internal endpoints would break the
terms and could stop working at any time. So the app links to the official NSE, BSE and SEBI pages with the company
name and symbol to search, marks them link-only, and never claims an automated filing search. Live evidence for
company news comes from news publishers, and strong evidence needs at least two of them.

How do you handle market hours, holidays and special sessions?
The NSE normal market runs 09:15 to 15:30 IST, and the day's bar is treated as final only after 16:15 IST, when trade
modifications end. A bar fetched earlier is marked "session in progress" and left out of detection. The holiday
table comes from NSE's circulars for 2024 to 2026, so a holiday such as Dussehra on 20 October 2026 is not counted as
a missed session. Weekend sessions such as Muhurat trading or a Budget-day session are kept as observed, never deleted
or invented.

Why do Larsen & Toubro and Bharti Airtel have no peer comparison?
No other watchlist stock is in the same industry (construction, telecom), and the app does not invent peers. Their
reports say so, and the rubric treats the missing comparison as a limit of the watchlist rather than as missing data.
Seven of the ten groups have no NSE sector index, so they are compared with peers only. Three of them lost theirs on
20 October: Yahoo had only three sessions of history for NIFTY Energy, FMCG and Auto, too few for a z-score, so the
symbol check failed them and they were removed rather than kept quietly.

What happens with corporate actions such as bonus issues or demergers?
Returns use the adjusted close, so splits, bonus issues and dividends the provider records do not create false
moves. If the provider fails to adjust one, the move appears as a large one-day return; the data-quality check flags
moves of 25% or more as a possible unadjusted corporate action to check against the exchange's records.

Why is the monitor not an LLM?
Detection must be reproducible and testable. A model could give different answers on different days for the same
data. The monitor is still an agent in the simple sense that it perceives (scans data), decides (applies the rules and
groups episodes) and acts (escalates events), but its policy is fixed.

What is the difference between the five hypotheses?
H1 says the whole market moved and the stock followed. H2 says its sector moved. H3 says the company had its own news.
H4 says the stock traded unusually but no public explanation was found. H5 says the evidence cannot tell them apart.
H3 and H4 share the same price evidence. What separates them is direct, timely evidence: a company announcement inside
the information window (in this version only in the synthetic data, because exchange announcements are link-only), or
relevant headlines from at least two different publishers. A single headline earns half the points, because a big
move attracts headlines whether or not anything caused it.

Why could a conclusion still be wrong?
Coincident timing is not causation, peer groups are small, beta changes over time, headlines are judged without the
article text, and daily data hides intraday order. The report lists the specific unknowns for each investigation.

What did testing teach you?
The first real LLM run, with Google's Gemini, showed three things the scripted tests could not. Model turns took up
to two minutes, so the timeout went from 90 to 240 seconds. The grounding check flagged a clock time ("11:00 UTC") as
an invented figure, so times are now ignored. And the free tier's rate limit stopped the risk step, so the client now
waits as long as Google asks before retrying. With gemini-3.5-flash the investigator then completed a full
investigation on its own. Converting to Indian markets found three more defects, each now covered by a test: the US
version read bar dates in New York time, which moved every NSE bar to the previous day; the link-only entry for the
official pages could hide a failed news search and give credit for "no news found"; and the grounding check split
Indian digit grouping (12,34,567) into two numbers. Lessons from the earlier live testing carry over: headlines that
only report a move, holdings reports and tips are kept apart from real causes, and one stray headline cannot decide
between company news and unexplained trading.

What does the replay show?
How alerts would have looked day by day in a past period, using only the information available at each close, and
what happened next. The event-study chart shows the average abnormal return path after up and down alerts. These are
descriptive results, clearly separated from what was known at detection.

Is volatility a forecast?
No. Every volatility figure in the app is historical (realised) volatility over a stated window, annualised with the
square root of 252.

What are the evidence levels A, B and C?
A is a verified company event: a retrieved announcement inside the information window (only the synthetic demo
announcements in this version, because live NSE and BSE pages are link-only). B is a potential catalyst: a headline
names the company and a cause inside the window, but its article and the official filing were not read, so it is
labelled "not yet verified" and the explanation is provisional. C means no catalyst was identified, either because
nothing direct and timely was found or because the news search failed; the two are reported differently.

How is the recommended next action chosen?
By fixed rules from what the record leaves open, in order: unreliable data first, then a failed news search, then an
unresolved tie between explanations, then the leading explanation's weakest link (for example verifying a headline
against the filing). It comes with the reason, up to three steps, what would change the assessment and when to hold
back a stronger conclusion. Its figures are copied from the record, and it never advises buying or selling.

What is the difference between alert priority and anomaly intensity on the grid?
Anomaly intensity is the robust z-score of the day's return: how unusual the move was. Alert priority is the 0 to 100
score that also weighs the market-adjusted move, volume and the volatility regime, banded at 30, 50 and 70. The grid
shows priority by default and intensity as a second view, so the two are never mixed.

What did testing on real data change in the guidance?
Running it on the laptop's saved HCL and ITC investigations showed three faults that synthetic fixtures had missed: a
routine zero-volume note was blocking the real next action, the earliest "direct" headline for ITC was about another
firm's tax "ITC demand", and social posts and price-forecast pages counted as evidence. The rules now treat routine
notes as limitations, choose the subject most publishers report (for ITC, Citi's rating upgrade), ignore social posts
as publishers and screen out tips and forecast pages. Each fix has a regression test with fictional names.

What does the intraday watch add, and what does it not?
It shows 5-minute bars for the NIFTY 50 and the 25 stocks and flags a latest bar that is unusual for its time of day:
its return, its return after removing beta times the NIFTY 50's, and its volume, each as a robust z against the same
bar in up to 40 earlier sessions (at least 15 needed), flagged at |z| of 4. The cut-off is stricter than the daily
tests because 26 symbols with 75 bars a session make about 2,000 comparisons a day. It refreshes only while the page
is open, uses unofficial and possibly delayed Yahoo bars, and is kept apart from the daily alerts: it changes no
priority score and starts no investigation. The investigations still work on daily bars.

What would you add with more time?
Intraday bars inside the investigation to time moves against announcements (the intraday watch only displays and
flags recent bars), larger peer groups from an official classification, reading the text of filings, an authorised or
licensed feed of NSE and BSE announcements, a labelled evaluation set reviewed by people, and scheduled monitoring
with alerts that runs without a browser open.

## Glossary

| Term | Meaning |
|---|---|
| Adjusted close | Closing price corrected for dividends, splits and bonus issues, so returns are not distorted by them |
| Robust z-score | How many robust standard deviations a value sits from the median of the previous 60 days |
| MAD | Median absolute deviation, a spread measure that ignores a few extreme values |
| Beta | How much a stock tends to move when the market moves 1% |
| Abnormal return | Actual return minus the return the market model expected |
| Information window | From the previous NSE session's 15:30 IST close to the event day's 15:30 IST close |
| NIFTY 50 | NSE's benchmark index of 50 large companies, weighted by free-float market capitalisation; the market in the market model |
| NSE sector index | A NIFTY index of one sector (Bank, IT and Pharma in the live watchlist) used for the sector comparison |
| IST | India Standard Time, UTC+05:30; NSE's normal market runs 09:15 to 15:30 IST |
| Bhavcopy | NSE's official end-of-day price file, generated after trade modifications end at 16:15 IST |
| Lakh and crore | 1 lakh = 1,00,000; 1 crore = 1,00,00,000 (ten million) |
| Muhurat trading | A short special session NSE holds on Diwali, sometimes on a weekend |
| VaR | Value at Risk: the one-day loss exceeded on 5% of days in the sample (at 95%) |
| CAR | Cumulative abnormal return over several days |
| HHI | Herfindahl-Hirschman index, the sum of squared portfolio weights; higher means more concentrated |
