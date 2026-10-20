# Demonstration script (about 9 minutes, India version)

For a five-minute slot, use the sequence in `PRESENTATION_GUIDE.md`. This longer script splits the demo between the
two speakers.

Two speakers: Darshil (D) and Nevan (N). Adjust the split to suit you.

## Before the presentation

- The evening before, on the presentation laptop: run `scripts\validate_symbols.py` (30 symbols, no FAIL) and `scripts\smoke_test.py --no-llm`, and keep the two result files in `docs`. Then start `run_app.bat` once and close it, so its one-time package check is out of the way.
- With `LLM_MODEL=gemini-3.5-flash` in `.env`, run `scripts\llm_check.py`. PASS means both agents completed with the model; PARTIAL means the investigation did and the risk step fell back. Either can be shown honestly; say which. Confirm the sidebar shows the LLM as configured.
- 30 minutes before: double-click `run_app.bat`, stay in live mode and let it load once. The data is then cached for six hours, so the demo does not depend on the venue's network.
- Before 16:15 IST on 21 October the header shows a session in progress and the analysis runs to Monday 19 October (20 October was Dussehra). This is correct; be ready to explain the 16:15 IST rule.
- Run one investigation of the preselected live alert, note the stock and its leading explanation, and open Investigation history to confirm it saved. This is your guaranteed live example.
- Backup: if the network or Yahoo fails, switch the data source to Demonstration data. The preselected alert is Saffron Bank (fictional), 30 September 2026, the worked example in the viva guide.
- Turn on Presentation pacing in the workspace so the audience can follow the live activity.

## Script

| Time | Speaker | Screen | What to say and do |
|---|---|---|---|
| 0:00 | D | Market overview | "The NSE produces hundreds of moves a day. Market Sentinel asks which ones were genuinely unusual for that particular stock, gathers evidence about why, and is honest when it cannot tell. It is an analysis tool, not a trading tool." |
| 0:45 | D | Market overview | Point to the source pill and the latest complete session: "NSE prices from Yahoo via yfinance, in rupees, with the retrieval time; a day's bar only counts once NSE's day is final at 16:15 IST." Then the sentinel grid: "Each row is a NIFTY 50 stock, each column a session, coloured by how unusual the return was against that stock's own last 60 sessions. Squares are alerts." Point to the NIFTY 50 and sector-index bars. |
| 2:00 | N | Anomaly monitor | Filter to Critical and High, select an alert and read the three trigger sentences: "This one is measured against the NIFTY 50 with a beta from the last 120 sessions." "The score is transparent: four components, fixed weights, shown here." Show the price (₹) and volume chart with the event and the median-volume line. |
| 3:30 | D | Investigation workspace | Press Run investigation. While it runs: "Each line on the right is a step that really completed: the NIFTY 50 comparison, the sector index and peers, the Indian news search. With an LLM key the model chooses these tools; without one, a fixed protocol runs the same tools, and the report says which." Read the verdict box when it finishes. |
| 5:00 | N | Evidence, then Hypotheses tab | Show the comparison bars (stock, market-model expectation, NIFTY 50, sector index, peers) and the news table with IST publication times, timing and relevance. Point to the official disclosures list: "NSE's terms forbid automated scraping, so these are links for a manual check. We never claim to have searched the exchange." Open one hypothesis to show its criteria: "If none leads clearly, the system says the evidence is insufficient instead of guessing." |
| 6:15 | D | Audit trail, then Export tab | With an LLM, open Model decisions: "These are the model's own choices, turn by turn, read from the log." Select a tool call to show the exact arguments and output. Download the HTML report: "Fourteen sections, including what remains unknown and how the conclusion could be wrong." |
| 7:00 | N | Historical replay (switch to Demonstration data) | "Now the synthetic India dataset: fictional companies, ten planted scenarios." Show the Designed demonstration scenarios table, pick 30 Sep 2026, press Investigate as of that day: "Saffron Bank, a fictional bank, declared results at 18:05 IST on 29 September after its board meeting; the stock fell 9% the next session. The announcement counts because it fell between the two 15:30 closes, and the report keeps the publication time and the meeting date apart." |
| 8:00 | D | Risk scenario lab | NIFTY 50 shock of -5% passed through each holding's beta, on the illustrative ₹1 crore portfolio, with the formula on screen and the assumptions in amber. Close: "Every number comes from Python, every step is logged, and the system separates evidence from explanation. Thank you." |

## If something goes wrong

| Problem | What to say and do |
|---|---|
| Live data will not load | "The provider is unavailable, and the app shows that instead of inventing prices." Switch to demonstration data. |
| A symbol shows as unavailable | "Yahoo returned no rows for it; the app lists it as unavailable rather than filling it in." Carry on with the rest. |
| News sources fail | Show the "News evidence unavailable" banner and the capped H3 and H4 scores: this is the designed behaviour. |
| LLM call fails or hits the rate limit | Point to the red banner saying the AI step did not complete; the rule-based output is labelled as a fallback. Open the saved LLM run from Investigation history instead. |
| A question you cannot answer | Open Methodology and data; the formulas, session rules and thresholds are all there. |
