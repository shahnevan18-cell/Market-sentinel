# Presentation guide (India version)

Market Sentinel, Business Analytics project (Theme 4: Agentic AI). Darshil Mittal (A016) and Nevan Shah (A043).
This is the short version for the day. `docs/viva_guide.md` has the full worked example and more answers, and
`docs/demo_script.md` splits the demo between the two speakers.

## The two-minute opening

Every trading day on the NSE, hundreds of stocks move. Most moves are noise, a few matter, and an analyst cannot read
the news for all of them. The usual alert, "the stock fell 5%", treats a 5% fall the same for a steady FMCG name and
a volatile metal stock, and it says nothing about why. Analysts then lose time on alerts the market explains on its
own, and the interesting ones arrive without context.

Market Sentinel addresses both halves. First it decides what is unusual for each particular stock, against that
stock's own last 60 sessions, using robust statistics that a single crash cannot distort. It also checks the part of
the move the NIFTY 50 does not explain, and whether trading volume exploded. Then, for the alert you pick, a set of
agents investigates. They pull the price evidence, compare the stock with the NIFTY 50, its NSE sector index where
one exists and its peers, search Indian news in the right time window, and weigh five competing explanations: the whole market moved,
the sector moved, the company had news, the stock traded unusually with no public explanation, or the evidence cannot
tell.

The output is an evidence-backed report that separates what was observed from what is inferred and what remains
unknown, with every source linked and every step logged. It watches 25 NIFTY 50 stocks with prices in rupees and
times in IST. It is a research aid. It does not trade, it does not give buy or sell advice, and it never claims to
know the cause of a move.

## Architecture in one picture

```
Market data: NSE shares (.NS), NIFTY 50, NSE sector indices, SENSEX via yfinance, cached; or the synthetic demo set
        |              all exchange rules (IST, 09:15-15:30, NSE holidays, INR) in config/market.py
Sentinel Monitor  - rule-based agent: robust z-scores, market model vs NIFTY 50, volume test, priority score
        |  ranked alerts
Orchestrator      - tool budgets, turn limits, schema checks, required checks, fallbacks, audit trail
        |
Market Investigator  <-- tools -->  prices, returns, volume, NIFTY 50, sector index and peers, market context,
   (LLM tool loop,                  Indian news search (Google News India, Yahoo), news paging, source details,
    or a fixed protocol)            hypothesis rubric; NSE/BSE announcement pages linked for a manual check
        |  validated findings
Risk Strategist      <-- tools -->  VaR, volatility regime, exposure of an illustrative ₹1 crore portfolio, stress tests
        |
Report (14 sections, Markdown and HTML) + full audit trail, saved to history
```

Every number comes from a Python function. The model, when one is configured, decides what to look at and judges
relevance. It never calculates figures, and it does not set the scores.

## What makes it agentic, said accurately

With an LLM key configured, the Market Investigator gets a goal (explain this alert) and a set of tools, and nothing
else is scripted. The model decides which tools to call, in what order and with which arguments, reads the results
and chooses the next step from them. It can page through the news it retrieved, open a source's details, pick its own
peers or rerun a search with a better query. It judges each headline as direct, indirect, uncertain or unrelated, with
a reason, and those judgements feed the rubric. It decides when it has enough evidence and submits structured
findings, which must pass a schema check and a numeric grounding check against the tool outputs (it understands
₹4,200 crore and 12,34,567). The Risk Strategist then works the same way from the validated findings. The Workspace's
Audit trail tab has a "Model decisions" section that shows every model turn: what it asked for and what came back.
That section is built from the log, so it cannot be staged.

Three things stay outside the model on purpose. Detection is statistical, so alerts are reproducible. Numbers come from
code. The hypothesis scores come from a fixed rubric, so a conclusion can be checked criterion by criterion. The
orchestrator also owns the safety rules: an agent cannot skip a required check, overspend its tool budget or call a
tool that does not exist, and a failed model step is reported as failed.

Without a key, or when you choose it in the sidebar, a fixed protocol calls the same tools in a set order and writes
the narrative from templates. Every report names the engine that actually ran: "Model-directed", "Rule-based fallback
after a provider error" (with the reason, for example the daily quota and when it resets), "Rule-based fallback: the
model's output could not be used", "Rule-based protocol, selected in the sidebar" or "Rule-based protocol: no LLM
credentials configured". A key being present never makes a run look model-directed by itself. Do not present a
rule-based run as AI reasoning. Present it as the honest fallback, and explain what changes when a model is connected.

Status to state if asked: on 20 October the India version ran with Google's gemini-3.5-flash on the free tier.
On the synthetic Saffron Bank case both agents finished with the model and nothing fell back to rules. The Market
Investigator took six turns and ten tool calls of its own choosing; its first submission quoted -9.6095, a number no
tool had returned, so the grounding check sent it back and the corrected version passed. The Risk Strategist chose two
stress scenarios itself. On live data (HCL Technologies, 13 October) the investigator ran five turns on real NSE prices
and Indian headlines, and its one malformed request was refused by argument validation and corrected. Then Google's
free daily quota ran out, the app said so at once, and the report was labelled as a rule-based fallback. Rerun that
evening with a key from a fresh Google project, the live HCL case passed in full: both agents finished with the
model on real NSE data, and the grounding check caught one invented figure, which the model then removed. Both passing
runs are in Investigation history and in `docs/llm_check_result.md` (demo) and `docs/llm_check_live_result.md` (live).

LLM quota on the day: free-tier quotas belong to the Google project, not the key, and reset at midnight US Pacific
time, which is 12:30 IST. One investigation uses about 9 to 12 model requests and the free allowance seen on 20
October was about 20 a day, so plan on one or two Gemini runs per project per day. If the laptop's project ran
several investigations the night before, its allowance is probably used up until 12:30 IST. Before presenting, press
Test connection in the sidebar (one request). "Connected" means Gemini is ready. A daily-quota message means: use a
key from another Google project, or select Rule-based protocol and open the saved live run (HCLTECH-NS-2026-10-13,
20 Oct, 21:13 IST) from Investigation history to show its Model decisions; it works offline. Any new investigation
still completes, and its engine line says it ran on rules and why.

## The five-minute demonstration

Plan A uses live NSE data and shows the India conversion working on real stocks. Plan B uses the synthetic India
dataset and works with no network at all. Both use the same pages.

Timing on the day: the presentation is on Wednesday 21 October, an NSE trading day. If you present between 09:15 and
16:15 IST, the header shows "Session in progress" for 21 October, and the analysis runs to the last complete session
(Monday 19 October, because 20 October was Dussehra). That is the designed behaviour: the day's bar is not final until
16:15 IST. Say so if asked.

| Time | Page | Do | Say |
|---|---|---|---|
| 0:00 | Market overview | Point to the source pill, the NIFTY 50 strip and the Sentinel grid, then the legend | "Twenty-five NIFTY 50 stocks, rupee prices, NSE sessions in IST. Each coloured cell is an alert, coloured by its priority band, slate to red, with the direction and the score on it. Quiet days stay neutral, and a cross means no data. Priority means urgency of review, not a good or bad stock." |
| (optional, 20 s) | Market overview, Intraday watch (only between 09:20 and 15:40 IST) | Press Refresh now. Point to Status, Latest complete bar and the table | "Five-minute bars from Yahoo, unofficial and possibly delayed, each compared with the same time of day over the previous 40 sessions. It is separate from the daily alerts and never starts an investigation or calls the model." |
| 0:40 | Anomaly monitor | Filter Severity to Critical and High, pick the alert in Selected alert. Read the panel's plain-English reason, then the score breakdown | "Three tests: the raw move, the part the NIFTY 50 does not explain, and volume. The score ranks attention; it is not a probability." |
| 1:20 | Investigation workspace | The alert is preselected. Turn on Presentation pacing, press Run investigation. When it ends, read the Summary tab top to bottom: what happened, the explanation and its status, the one next action | "Each line on the right is a step that actually ran. The summary separates three things: what we observed, how strong the explanation is (verified, provisional or unresolved) and the single next check an analyst should make." |
| 2:20 | Same page, Evidence tab | Show the comparison bars, the news table (published time in IST, timing, relevance, links) and the official disclosures list | "Only items between the previous 15:30 close and the event-day close can explain the move. NSE's terms forbid automated scraping, so exchange announcements are linked for a manual check, never scraped." |
| 2:50 | Hypotheses, then Audit trail | Open the leading hypothesis to show its criteria and points. In Audit trail, show Model decisions (or say the rule-based protocol ran) and inspect one tool call | "This is the exact input and output of that call, as the agent saw it." |
| 3:30 | Historical replay (demo data) | Switch the sidebar to Demonstration data. In "Designed demonstration scenarios", pick 30 Sep 2026: bank falls after results, press Investigate as of that day | "A fictional bank declared results at 18:05 IST on 29 September; the stock fell 9% the next session. The report keeps the publication time and the board-meeting date apart." |
| 4:20 | Risk scenario lab | NIFTY 50 shock tab, slider at -5% | "Each holding moves by its beta times the shock, on an illustrative ₹1 crore portfolio. Teal boxes are observed inputs, amber boxes are assumptions, cyan boxes are hypothetical results." |
| 5:00 | | Close | "Every number comes from code, every step is logged, and the system separates evidence from explanation." |

Plan B (no network): start the app in Demonstration data and follow the same rows. The preselected alert is Saffron
Bank (fictional) on 30 September 2026, the worked example in the viva guide. Other designed scenarios: Ironbridge
Engineering's ₹4,200 crore order (17 September), Monsoon Systems' volume spike (25 September), Cureline Pharma's
unexplained fall (28 August), the oil, gas and power rally (3 August) and the market fall (2 July).

If something fails, say what failed and switch. If live data does not load, the app says so and never substitutes
synthetic prices; switch to Demonstration data. If news sources fail, the report says "News evidence unavailable" and
caps the news-dependent scores, which is the designed behaviour. If Gemini fails, the engine line says "Rule-based
fallback after a provider error" and a red banner gives the reason (for a daily quota, the time it resets); the
findings come from the rule-based protocol. You can also open a saved run from Investigation history at the bottom of
the workspace; it works offline. If intraday bars do not arrive, the Intraday watch says Unavailable or Stale with the
reason; the daily analysis is not affected.

## Pre-presentation checklist

The evening before, on the presentation laptop, in PowerShell:

```powershell
cd "C:\Users\Navin shah\Documents\market_sentinel"
.\.venv\Scripts\python.exe -m pytest -q                  # expect 297 passed
.\.venv\Scripts\python.exe scripts\validate_symbols.py   # expect 30 symbols, no FAIL
.\.venv\Scripts\python.exe scripts\smoke_test.py --no-llm
.\.venv\Scripts\python.exe scripts\intraday_check.py     # which intraday intervals Yahoo returns
```

`intraday_check.py` asks Yahoo for NIFTY 50 and four stocks at 1, 2, 5, 15, 30 and 60-minute intervals and writes
`docs\intraday_check_result.md`. Outside market hours it reports the last session's bars.

For the LLM, check the key and the quota with one request first:

```powershell
.\.venv\Scripts\python.exe scripts\llm_check.py --probe  # one request: key, model and tool calling
.\.venv\Scripts\python.exe scripts\llm_check.py          # full run on synthetic India data (9 to 12 requests)
.\.venv\Scripts\python.exe scripts\llm_check.py --live   # the same on live NSE data
```

The full checks print every model turn and end with PASS, PARTIAL or FAIL. Each run is saved to history and written
to `docs\llm_check_result.md`. They spend most of a free project's daily allowance, so skip them on the morning of the
presentation if the probe says Connected.

Then double-click `run_app.bat` once and close its window when the app has opened. The first start through the
launcher checks the installed packages against `requirements.txt`, which takes a minute; later starts skip it.

Thirty minutes before:

- Start the app by double-clicking `run_app.bat`. Leave the black window open.
- Let live data load once. It is then cached for six hours, so the venue's network matters less.
- Check the header: "Latest complete session" should be 19 October before 16:15 IST on the 21st.
- Check the sidebar under Reasoning engine. It should read "Configured: gemini-3.5-flash via Google Gemini". Press
  Test connection once (one request).
- If you present during market hours, press Refresh now under Intraday watch on the Market overview once, and check
  that a complete bar from the last few minutes appears.
- Run one investigation of the preselected live alert so the data and news are warm, and note which stock it is.
- Open the saved Saffron Bank LLM run once from Investigation history so you know where it is.
- Keep the laptop on mains power, turn off sleep, close other heavy apps.

## Questions examiners are likely to ask

Why robust z-scores instead of mean and standard deviation?
One crash inside the 60-day window inflates the standard deviation and hides the next shock. The median and median
absolute deviation barely move, and the factor 1.4826 makes the scale comparable to a standard deviation.

Why the NIFTY 50 as the benchmark?
It is the broad, free-float weighted index of the 50 largest NSE companies, and every watchlist stock is a
constituent. That also means a heavyweight such as HDFC Bank or Reliance moves its own benchmark a little, which the
report notes; for sector comparisons the NIFTY sector indices are used where they exist.

How do you avoid look-ahead bias?
Every baseline ends the day before the tested day, and beta is estimated on the 120 sessions before it. A test
recomputes features on truncated data and checks they match. Each investigation re-detects the alert on data cut at
the event date, and as-of investigations exclude news published after that day's 15:30 IST close.

What is an abnormal return?
The part of the return the market model does not explain: actual return minus (alpha plus beta times the NIFTY 50's
return), divided by the residual standard deviation to make it comparable across stocks.

Why don't you read NSE announcements directly?
NSE's terms of use (clause 9) prohibit systematic or automated data collection, and neither exchange offers a
documented public API for announcements. So the app links to the official NSE, BSE and SEBI pages with the company and
symbol to search, marks them link-only, and never claims an automated filing search. Live evidence for company news
comes from independent publishers; strong evidence needs at least two.

How do you handle Indian market hours and holidays?
All rules are in `config/market.py`: Asia/Kolkata time, the 09:15 to 15:30 normal market, a bar counted as final only
after 16:15 IST (the end of trade modifications), and the NSE holiday circulars for 2024 to 2026. Weekend special
sessions such as Muhurat trading are kept, not deleted. A test caught that the US version's New York time conversion
moved every Indian bar to the previous day.

Is Gemini running on the public link?
Only when its key is in the Streamlit secrets. The sidebar says which: "Configured: gemini-3.5-flash via Google
Gemini ... key read from GEMINI_API_KEY", or "No LLM credentials are configured". Test connection sends one request
and reports the result. Each report also states which engine actually ran, so a configured key alone never makes a
run look model-directed.

Is the intraday data real-time?
No. The 5-minute bars come from Yahoo through yfinance, unofficial and possibly delayed, and are requested only while
someone has the Market overview open (a timed refresh every 5, 10 or 15 minutes, or Refresh now). Each bar is compared
with the same time of day over the previous 40 sessions, because volume and volatility are naturally high after the
open and before the close. With fewer than 15 earlier sessions a stock is shown for display only. Intraday flags are
separate from the daily alerts, change no score and start no investigation.

How do you know the LLM really chose the tools?
The Model decisions view lists each turn's requested tools, taken from the audit log written as the calls happened. A
rule-based run shows no model turns at all. In the first real Gemini run the model asked for five tools in its first
turn, then chose to open the announcement's details and the market context before scoring the hypotheses.

What stops the model from inventing numbers or sources?
It can act only through registered tools with validated arguments. Its final output must pass a schema check and a
grounding check that matches every figure against tool outputs; mismatches go back once for revision and anything left
is flagged. Links come from the providers, never from the model.

What if a headline contains instructions, a prompt injection?
Headlines are passed as data and the instructions say never to follow them. More importantly, no tool can trade, send
messages or change anything, so the worst a malicious headline can do is mislead a relevance judgement, which is shown
with its reason.

What does the priority score mean?
A ranking for analyst attention on a 0 to 100 scale from four capped components with fixed weights. It is not a
probability that anything caused the move.

Why does the app not say the earnings caused the move, when the headline says so?
The headline is the publisher's claim. The app read the headline, publisher, time and link, not the article or the
company's filing, so it labels the item "Potential catalyst - not yet verified" and the explanation provisional, and
its next action is to check the results filing and its time. Only a retrieved company announcement counts as
verified. When several publishers report the same subject, the app says so; that corroborates the report but is still
not an official record.

What does the app do when it cannot decide?
It says the cause is unresolved and still gives one next action. For HCL Technologies on 13 October, sector movement
(75) and company news (70) were almost tied: the whole IT group rose, HCL rose further, and results headlines were in
the window. The app names both explanations, explains that a daily close cannot separate a company reaction from a
larger reaction to sector news, and recommends checking HCL's own results filing on NSE and the peers' shared driver,
saying how each finding would move the assessment.

How accurate is it?
On live NSE data there is no ground truth for "this move deserved an alert", so no accuracy is claimed; the replay
reports descriptive outcomes. On the synthetic data the planted shocks are known: the detector finds all six
stock-specific shocks and 43 of 46 planted stock-days. Precision is low on purpose, because the random returns have
fat tails, which is also true of real markets.

What do corporate actions do to the analysis?
Returns use the adjusted close, so splits, bonus issues and dividends the provider records do not create false moves.
A corporate action the provider does not adjust, such as some demergers, shows up as a large one-day move; moves of 25%
or more are flagged for checking against the exchange's corporate-action records.

What did testing change?
The real Gemini run exposed three things: slow model turns needed a 240-second timeout, a clock time ("11:00 UTC")
was wrongly flagged as an invented figure, and the free tier's rate limit needed a provider-directed wait, and a busy provider (HTTP 503) had been logged as a rate limit. The India
conversion found that bar dates shifted by a day under New York time, that the link-only disclosure entry could hide
a failed news search, and that Indian digit grouping was split into two numbers by the grounding check. Each has a
regression test. The first live check on the laptop then found that Yahoo had only three sessions of history for
NIFTY Energy, FMCG and Auto, so those indices were removed and their groups are compared with peers only. The first
public deployment showed the rule-based engine because the key existed only in the laptop's `.env`; the app now reads
GEMINI_API_KEY from the hosting secrets, names any missing or unusable setting, and labels each run with the engine
that actually ran.

Is it deployed?
Yes, on Streamlit Community Cloud. Say that Gemini runs there only if its sidebar reads "Configured" and Test
connection succeeds on the day. `docs/deployment.md` has the steps for updating it.

## Limitations and ethics

- A statistical alert says a move was unusual. It does not say why, and many unusual moves have no public cause. It
  is never evidence of fraud or manipulation.
- Timing is not causation. Daily data cannot show whether the news came before or after the move within the day.
- Exchange announcements are link-only, so a filing can explain a move the app calls unexplained.
- Headlines are judged from titles, publishers and times. Article text is not read.
- Yahoo data through yfinance is unofficial, can be delayed or throttled, and is for personal and educational use.
- Intraday bars are collected only while someone has the Market overview open; there is no background collector.
- Beta from 120 sessions can drift, peer groups are small, and seven of the ten groups have no sector index.
- Historical VaR and volatility describe the past and understate tail risk in stressed markets.
- The illustrative portfolio is hypothetical. Stress results are assumptions, never observations.
- The tool must not be used for trading decisions, and the report says so on every page.
- API keys live only in `.env` or the hosting secrets, are never shown in the app, logs, reports or the shared zip, and
  `.gitignore` keeps them out of Git.
- AI assistance in building the project is declared in `docs/ai_use_declaration.md`.
