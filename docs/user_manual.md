# User manual (India version)

Start the app by double-clicking `run_app.bat` (Windows) or running `python3 launch.py` (Mac); see the README for
manual setup. The sidebar holds the page list, the data source switch, the alert thresholds, the reasoning-engine
status and a Reset session button.

## Sidebar

Data source switches between live NSE market data (25 NIFTY 50 shares, the NIFTY 50, three NSE sector indices and the
SENSEX, through Yahoo Finance) and the synthetic demonstration set of fictional India-themed companies. In live mode,
Refresh market data ignores the cache and downloads again. When a live load fails, the failure is shown again for two minutes
instead of retrying on every click; Refresh market data retries at once. Alert thresholds change the baseline window and the three z-score
thresholds; every page recalculates immediately and Reset to defaults restores 60 sessions and 3.0. The reasoning
engine panel shows whether an LLM key was found and lets you switch the LLM off for a run. Reset session clears the
selected alert and the open investigation without deleting cached data or saved reports.

## Market overview

The top strip shows the NIFTY 50's latest close (index points) and daily change, its 20-session realised
volatility, the share of watchlist stocks that rose, and alert counts. The pills in the header give the data source,
the latest complete NSE session and how long ago the data was retrieved. Amber warnings appear when data is stale or
a symbol failed. A blue note appears when the latest bar was fetched before 16:15 IST (the day is not final yet) or
when today is an NSE trading holiday.

The sentinel grid is the main picture: one row per stock, one column per session for the last 30 sessions, coloured
by the robust z-score of that day's return. Hover a cell for the return and the z-score; amber squares mark alerts.
Below it, the latest session's moves are sorted by return, and the NIFTY 50, the sector indices and the SENSEX are
compared over 1, 5 and 21 sessions. The watchlist table shows each share's last close in rupees. The alerts table
lists the highest-priority alerts of the last 10 sessions; pick one and press Open in workspace. Data freshness and
provider status, at the bottom, lists every symbol with its status, last bar, retrieval time in IST, currency,
exchange and data-quality notes.

## Anomaly monitor

Filter alerts by security, date range, severity, alert type and minimum priority. Select a row to see the detail
view: price and volume with the event marked (other alerts of the same stock in amber, the 60-session median volume
as a dotted line), the three z-scores over time with the thresholds, the plain-language reasons the alert fired, the
priority-score breakdown, and the baseline context (median return, beta, NIFTY 50 and sector-index moves, or a note
that the group has no sector index, peer-relative return, volume ratio, volatility regime, episode).

Investigate this alert opens the workspace in live mode. Investigate as of that day opens it in as-of mode, which
uses only prices up to that day and excludes news published after that day's close.

## Investigation workspace

The most recent Critical or High alert of the last 10 sessions is preselected, so a run can start at once; choose
any other alert from the list. Choose the investigation type, then press Run investigation. The left column lists the seven workflow
stages and marks each one as its required steps finish; the right column logs every completed step (tool calls,
model turns, validations and warnings) with its result. Presentation pacing adds a short pause after each step so an
audience can follow; results are identical.

The verdict box shows the leading assessment, its confidence and the conclusion. The strip under it names the engine
that produced the run: "LLM-directed" with the model turns and the number of tool calls the model chose, or
"Rule-based protocol" when no LLM was used or the LLM step failed. The tabs below it, in reading order:

| Tab | What it shows |
|---|---|
| Summary | The strategist's executive summary, the investigator's findings, what remains unknown and the follow-up checks |
| Evidence | Price (₹) and volume up to the event date; event-day returns against the market model, NIFTY 50, sector index and peers; a table of measures; news with publication time in IST, timing, relevance, basis (LLM judgement or keyword heuristic) and links; the official NSE, BSE and SEBI pages to check by hand (link-only) |
| Hypotheses | The five scores and, for each hypothesis, every criterion with its points and evidence |
| Risk | VaR before the event (with confidence and lookback), the event move as a multiple of it, the volatility regime, exposure in the illustrative ₹1 crore portfolio and any hypothetical stress tests in rupees |
| Audit trail | Model decisions (each model turn: the tools the LLM asked for and what they returned; empty for rule-based runs), then every step with its time in IST, actor, status and result; pick a tool call to see the exact arguments and the output the agent received |
| Export | The report as Markdown or printable HTML (print to PDF from the browser) and the full record as JSON |

Every completed run is saved, and the confirmation says so only when the file was written. Open Investigation history
at the bottom to reopen an earlier report; this works without a network connection. Reports saved by the earlier US
version are not listed (the files stay on disk).

## Historical replay

In demonstration mode the page starts with the designed scenarios: the ten shocks planted in the fictional data,
each with its date, the stocks affected and the strongest alert it raised. Choose one and press Investigate as of
that day to run a full investigation at once, without waiting for a live alert.

Pick a start and end date (the first 120 sessions are reserved for estimating baselines). The page shows how many
alerts fired, how often the abnormal move continued over the next five sessions, and whether volatility was higher
after alerts than on ordinary days. The event-study chart shows the average cumulative abnormal return from five
sessions before to 20 after, split into up and down alerts; the shaded part was not known when the alerts fired. The
scatter compares each alert's event-day abnormal z-score with its later five-session abnormal return.

Select an alert in the table to see its price path with the following 20 sessions shaded, and press Investigate as
of that day to run the full investigation exactly as it could have been run that evening. In demonstration mode an
expander checks the detector against the planted shocks (recall and precision). In live mode there is no such label,
and an expander explains why and links to the official NSE and BSE results pages for a manual comparison.

## Risk scenario lab

Edit the illustrative portfolio's weights (they are rescaled to 100%) and its value in rupees (₹1 crore by default).
Teal boxes are observed inputs from market data, amber boxes are your assumptions, cyan boxes are hypothetical
results with the formula underneath. Rupee amounts use Indian digit grouping (₹1,20,000) and charts show them in
lakh. The five tabs cover a single holding shock, a NIFTY 50 shock passed through each holding's beta, concentration
when one position grows, a volatility rise and its effect on VaR, and how the alert count changes with the threshold.

## Methodology and data

The data-source register (including the NSE terms that make official disclosures link-only), every formula, the
NSE session and holiday rules, the current thresholds and weights, the agent architecture diagram with the full list
of tools, the data-quality report for every symbol, and the limitations.
