# User manual (India version)

Start the app by double-clicking `run_app.bat` (Windows) or running `python3 launch.py` (Mac); see the README for
manual setup. The sidebar holds the page list, the data source switch, the alert thresholds, the reasoning-engine
status and a Reset session button.

## Sidebar

Data source switches between live NSE market data (25 NIFTY 50 shares, the NIFTY 50, three NSE sector indices and the
SENSEX, through Yahoo Finance) and the synthetic demonstration set of fictional India-themed companies. In live mode,
Refresh market data ignores the cache and downloads again. When a live load fails, the failure is shown again for two minutes
instead of retrying on every click; Refresh market data retries at once. Alert thresholds change the baseline window and the three z-score
thresholds; every page recalculates immediately and Reset to defaults restores 60 sessions and 3.0. Reset session
clears the selected alert and the open investigation without deleting cached data or saved reports.

Reasoning engine. When a key is configured, choose "Gemini (model-directed)" or "Rule-based protocol" for the next
investigation; the caption names the model and the setting the key was read from (never the key). Without a key, or
with settings that cannot be used, the caption says which and what to set. If the deployment has a passcode
(`MS_LLM_PASSCODE`), enter it before the model can be called; until then investigations use the rule-based protocol
and say why. Test connection sends one small request (one request of the daily quota) and reports either "Connected"
with the response time or the reason it failed, such as a rejected key or a used-up daily quota with its reset time in
IST; the provider's own message, with any key removed, is folded underneath. Engine diagnostics lists the names of the
settings the app found, never their values.

## Market overview

The top strip shows the NIFTY 50's latest close (index points) and daily change, its 20-session realised
volatility, the share of watchlist stocks that rose, and alert counts. The pills in the header give the data source,
the latest complete NSE session and how long ago the data was retrieved. Amber warnings appear when data is stale or
a symbol failed. A blue note appears when the latest bar was fetched before 16:15 IST (the day is not final yet) or
when today is an NSE trading holiday.

Intraday watch (live data only) shows 5-minute bars for the NIFTY 50 and the 25 stocks. Nothing is requested when the
page opens: press Refresh now, or turn on Auto-refresh and choose every 5, 10 or 15 minutes. The status line gives the
status (Fresh, Waiting for new data, Cached, Stale or Unavailable), the time of the last request, the latest complete
bar in IST, the interval, the source, and whether this view sent a request; the sentence under it explains the status,
for example that the market is closed for a holiday and when the next session opens. Stocks whose latest complete bar
is unusual for its time of day are listed with the reason, and earlier unusual bars of the session are named. The
chart shows the NIFTY 50's 5-minute closes for the session, and the table lists every symbol's latest bar, its z-scores
against the same time of day, volume against the usual for that time, and the number of earlier sessions behind each
comparison, most unusual first. "n/a" means the value does not exist (an index has no volume on Yahoo, or a stock
has too little history for that time of day); it is never shown as zero. The section changes no daily alert or score
and starts no investigation. It refreshes only while the page is open.

The sentinel grid is the main picture: one row per stock, one column per NSE session. Choose the period (1 week,
1 month, 3 months or a custom range of sessions), what the colour shows and the row order; Reset view returns to one
month, alert priority and highest priority first. In the default Alert priority view, each alert cell is coloured by
its priority band (Low under 30, Moderate 30 to under 50, High 50 to under 70, Critical 70 and above, the same
thresholds that label every alert) and carries an arrow for the direction of the move and, when space allows, its
score. Sessions without an alert are a neutral colour, and a cross marks a session with no data. The Anomaly
intensity view instead colours every cell by the robust z-score of the day's return: how unusual the move was, which
is not the same as how urgent it is. Hover a cell for the company, date, priority band, return, z-score and volume.
Zoom with the + and - buttons at the top right of the chart or by dragging across an area; the house button resets
the zoom. Click an alert cell, or pick it in "Alert in this period", to see its details and open its investigation.
Below it, the latest session's moves are sorted by return, and the NIFTY 50, the sector indices and the SENSEX are
compared over 1, 5 and 21 sessions. The watchlist table shows each share's last close in rupees. The alerts table
lists the highest-priority alerts of the last 10 sessions; pick one and press Open in workspace. Data freshness and
provider status, at the bottom, lists every symbol with its status, last bar, retrieval time in IST, currency,
exchange and data-quality notes.

## Anomaly monitor

Filter alerts by security, date range, severity, alert type and minimum priority. Clearing Severity or Alert type
means "all", and a note says so. When no alert matches, a panel says so and offers Reset filters; when no market data
is loaded, the page explains the data problem instead of reporting a calm market. Click a row, or use Selected alert
(labels read "SYMBOL · date · alert type · Priority N", and typing a symbol jumps to it), to open the full-width
alert panel: company and symbol, peer group, event date, alert type, priority and band, daily return, the NIFTY 50
the same day, volume against its median and a plain-English reason the alert fired. Below it is the detail view: price and volume with the event marked (other alerts of the same stock in amber, the 60-session median volume
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

The verdict box shows the explanation, its status (Verified, Provisional or Unresolved) and the recommended next
action. Before the run, a caption says which engine the run will use and why. After it, the strip under the verdict
names what actually happened: "Model-directed" with the model, its turns and the tool calls it chose; "Partly
model-directed"; "Rule-based fallback after a provider error" or "... the model's output could not be used", with a
red note giving the reason (the provider's own message, keys removed, is in a collapsed section); or "Rule-based
protocol" with the reason no model ran (selected in the sidebar, no credentials, settings unusable, switched off, or
locked by passcode). The tabs below it, in reading order:

| Tab | What it shows |
|---|---|
| Summary | A. What happened, in plain English. B. The most plausible explanation and its status, with the supporting and limiting evidence and the catalyst evidence card: level A (verified company event, a retrieved announcement), B (potential catalyst, not yet verified: the exact headline, publisher, publication time in IST, retrieval time and link, with the access limitation stated) or C (no identified catalyst). For an unresolved case: what is established, the two explanations still in play, why the evidence cannot separate them and the evidence that would. C. One recommended next action: why, up to three steps, what would change the assessment, what it should clarify, when to hold back a stronger conclusion, the official pages to check and its limitations. D. The material unknowns. E. Quantitative evidence and methodology, collapsed: the technical summary, findings, rubric scores and plain definitions of the terms |
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
