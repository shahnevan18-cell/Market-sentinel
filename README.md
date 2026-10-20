# Market Sentinel (India)

An agentic market-anomaly investigation and risk-intelligence platform for shares listed on the National Stock
Exchange of India, built as a Business Analytics project (Theme 4: Agentic AI) by Darshil Mittal (A016, SAP ID
74052400181) and Nevan Shah (A043, SAP ID 74052400240).

Market Sentinel watches 25 large NIFTY 50 companies against the NIFTY 50 index, three NSE sector indices and the BSE
SENSEX. It flags statistically unusual price or volume moves, then runs a three-role investigation on any alert you
pick. A Sentinel Monitor finds and ranks the events. A Market Investigator gathers evidence with callable tools
(prices, NIFTY 50, sector indices and peers, Indian news headlines) and tests five competing explanations. A Risk
Strategist turns the findings into qualified risk notes in rupees. Every step is logged, every number comes from a
Python function, and the final report separates observations, hypotheses and what remains unknown.

It is an educational analysis tool. It does not trade, does not give buy or sell advice and does not forecast prices.

## How an investigation works

1. The monitor computes robust z-scores of returns and volume against the previous 60 NSE sessions, a market-model
   abnormal return against the NIFTY 50, and a transparent 0-100 priority score.
2. You choose an alert. The orchestrator re-detects it on data truncated at the event date, which checks that no
   later information was used.
3. The investigator calls tools: price history, returns and volatility, abnormal volume, NIFTY 50 comparison, peer
   and sector-index comparison, market breadth, news search and source details. With an LLM configured, the model
   decides which tools to call and judges headline relevance; without one, a fixed rule-based protocol calls the
   same tools.
4. A fixed rubric scores five explanations (broad market, sector, company news, unexplained trading, insufficient
   evidence). A conclusion is stated only when one explanation clearly leads; otherwise the report says the cause is
   unresolved.
5. The strategist computes VaR, the volatility regime and the exposure of an illustrative ₹1 crore portfolio, and
   writes monitoring suggestions.
6. The guidance step turns the record into a business-facing answer: what happened, the most plausible explanation
   marked verified, provisional or unresolved, the catalyst evidence level (A verified company event, B potential
   catalyst from a headline, C none identified) and one prioritised next action with its reasons, steps and the
   finding that would change the assessment. Investigative guidance only, never buy or sell advice. The report and
   the full audit trail are saved and can be downloaded.

## Indian market conventions

| Topic | How the app handles it |
|---|---|
| Exchange and symbols | NSE shares through Yahoo Finance symbols ending in `.NS` (RELIANCE.NS, HDFCBANK.NS); NIFTY 50 is `^NSEI` |
| Watchlist | 25 NIFTY 50 constituents across 10 peer groups, checked on 20 Oct 2026 against NSE Indices press releases (Wipro left the index on 30 Sep 2026 and is not included) |
| Benchmark | NIFTY 50 for the market model; NIFTY Bank, NIFTY IT and NIFTY Pharma as sector indices; SENSEX for display |
| Peer groups without a sector index | Oil, gas and power, FMCG, autos, consumer durables, and cement and steel are compared with peers only, and the report says so. NIFTY Energy, FMCG and Auto were dropped after the live symbol check of 20 Oct 2026 found only three sessions of history on Yahoo. L&T (construction) and Bharti Airtel (telecom) have no peer in the watchlist |
| Sessions | Asia/Kolkata time, normal market 09:15 to 15:30 IST; a daily bar counts as final only after 16:15 IST |
| Holidays | NSE trading-holiday table for 2024 to 2026 from NSE circulars; weekend special sessions such as Muhurat trading are kept |
| Currency | INR, shown with ₹ and Indian digit grouping (₹1,00,00,000); each symbol's reported currency is checked and never relabelled |
| News | Google News India edition and Yahoo Finance headlines, timed against the 15:30 IST close |
| Official disclosures | NSE and BSE announcements are link-only: NSE's terms of use (clause 9) prohibit automated data collection, so the app links to the official pages for a manual check |

All exchange rules live in `config/market.py` and the watchlist in `config/watchlist.py`.

## What kind of number is this?

| Kind | Example | Where it comes from | How it is marked |
|---|---|---|---|
| Verified market data | RELIANCE.NS adjusted close, NIFTY 50 return | Yahoo Finance via yfinance, checked by `scripts/validate_symbols.py` and the data-quality report | Source pill, latest session and retrieval time on every page |
| Synthetic data | SAFFRON.DEMO falls 9% | The demonstration generator (fixed seed, fictional companies) | Amber banner on every page; reports start with "SYNTHETIC DEMONSTRATION DATA" |
| News evidence | A headline from an Indian publisher | Google News India or Yahoo, with publication and retrieval times | Evidence table with relevance, timing and link |
| Inferred explanation | "Most consistent with company-specific news" | The hypothesis rubric (fixed points) and, if configured, the LLM's relevance judgements | Stated as fit with the evidence, never as proven cause |
| Hypothetical risk output | A -10% shock costs the illustrative portfolio ₹1,20,000 | Formulas applied to assumptions you type in | Amber "assumption" and cyan "hypothetical result" boxes |

## Quick start

You need Python 3.11 or newer (the tests pass on 3.11, 3.12, 3.13 and 3.15) and an internet connection for the first
start and for live data.

On Windows, double-click `run_app.bat` in the project folder. On a Mac, open Terminal in the folder and run
`python3 launch.py`. The first start creates a private environment in `.venv` and installs the packages (a few
minutes); later starts take a few seconds. The app then opens in your browser at http://localhost:8501. Keep the
launcher window open while you use it, and close that window to stop the app. `START_HERE.txt` gives the same steps
for someone who receives the project as a zip.

To do the same by hand in PowerShell, from the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address localhost
```

The first live load downloads about two years of daily data for 30 symbols (usually 15 to 40 seconds); later loads
come from the local cache for six hours. Optional settings such as an LLM key go in a `.env` file: copy
`.env.example` to `.env` and edit it.

To share the project, run `.\.venv\Scripts\python.exe scripts\make_share_zip.py`. It writes a clean
`Market_Sentinel_share.zip` next to the project folder, without `.env`, `.venv` or cached data.

To start straight in the synthetic demonstration mode (no internet needed), set `MS_DEFAULT_MODE=demo` in `.env`,
or switch the data source in the sidebar.

## Data modes

| Mode | Where the numbers come from | How it is labelled |
|---|---|---|
| Live | Yahoo Finance through the yfinance library (NSE symbols), then cached in `data/cache` | Source pill, latest session and retrieval time on every page |
| Cached or stale | The last successful download, with its original retrieval time | Amber warning naming the stale symbols |
| Demonstration | 17 fictional India-themed `.DEMO` securities generated with a fixed seed | Amber banner on every page |

If live data cannot be loaded and no cache exists, the app shows the provider errors and suggests demonstration
mode. It never swaps synthetic prices in for real ones on its own.

The demonstration data holds ten planted scenarios, including a bank falling after results declared the previous
evening, an IT company trading seven times its normal volume, an engineering company winning a ₹4,200 crore order, a
broad market fall, a sector-wide rise in oil, gas and power, and an isolated fall with no news. Every company and
announcement in it is fictional. The Historical replay page lists the scenarios and opens any of them as an as-of
investigation.

## Intraday watch (optional, live data only)

The Market overview has an Intraday watch: 5-minute bars for the NIFTY 50 and the 25 stocks from Yahoo through
yfinance, which are unofficial and may be delayed. Nothing is requested until you press Refresh now or turn on
Auto-refresh (every 5, 10 or 15 minutes, default 10). The status line shows when the last request was sent, the newest
complete bar in IST and one status: Fresh, Waiting for new data, Cached, Stale or Unavailable, with a sentence that
explains it (for example, the market has closed, or Yahoo has not yet published the next bar).

The latest complete bar of each stock is compared with the same time of day in up to 40 earlier sessions, for its
return, its return relative to the NIFTY 50 and its volume, and flagged at a robust |z| of 4. With fewer than 15
earlier sessions a stock is shown for display only. A bar still forming is never used, a missing bar is never filled
and missing volume is never treated as zero. The intraday watch is separate from the daily alerts: it changes no
priority score, starts no investigation and never calls the LLM.

The refresh runs only while the page is open in a browser. Bars are kept in the server's memory, shared by everyone
using the app and lost when it restarts; nothing collects bars in the background. Demonstration mode has no intraday
bars, and none are simulated.

## Optional: connect an LLM

Leave the keys empty and investigations use the rule-based protocol, which is labelled as such. To let Google Gemini
drive the investigator and strategist, one line in `.env` is enough:

```
GEMINI_API_KEY=your-key
```

The app then uses Google's OpenAI-compatible endpoint and gemini-3.5-flash (set `LLM_MODEL` to change the model). An
Anthropic key works as `ANTHROPIC_API_KEY`, and any other OpenAI-compatible endpoint as `LLM_PROVIDER=openai_compatible`
with `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL`; `.env.example` shows all three. A Claude chat subscription does
not include API access. On a hosted copy, put the same names in the app's secrets instead of `.env`.

The sidebar shows what the app found: "Configured: gemini-3.5-flash via Google Gemini ... key read from
GEMINI_API_KEY", or "No LLM credentials are configured", or the name of the setting that cannot be used. With a key
present you choose the engine for the next investigation (Gemini, model-directed, or the rule-based protocol), and
Test connection sends one small request to check the key, the model and tool calling. On a public deployment,
`MS_LLM_PASSCODE` makes visitors enter a passcode before the model can be called, so a shared link cannot use up the
quota.

Every report names the engine that actually ran: model-directed, partly model-directed, a rule-based fallback after a
provider error (with the reason, such as a daily quota and its reset time), a fallback because the model's output
could not be used, or the rule-based protocol with the reason it was used. Keys never appear in the app, the reports,
the audit trail or error messages.

Google AI Studio's free tier has per-minute and per-day limits that belong to the Google project, not the key. Daily
limits reset at midnight US Pacific time, 12:30 IST (13:30 IST from November to mid-March). One investigation uses
about 9 to 12 requests. When the provider answers HTTP 429 for a per-minute limit, the app waits as long as the
provider asks (up to 65 seconds, twice); a daily limit fails at once and the report says when it resets. Restart the
app after editing `.env`.

To check the LLM path end to end, run `python scripts/llm_check.py`. It investigates the most recent high-priority
alert in the demonstration data, prints every model turn with the tools the model chose and what they returned, saves
the run and writes `docs/llm_check_result.md`. It reports PASS, PARTIAL (the model completed the investigation but
the risk step fell back) or FAIL, and the engine mode. Add `--live` to investigate a live NSE alert, or use `--probe`
to send a single test request instead.

Status on 20 Oct 2026: with gemini-3.5-flash both agents completed with the model on the synthetic Saffron Bank case
and on live NSE data (HCL Technologies, 13 Oct 2026). In the live run the investigator chose 9 tool calls over 5 turns
and the strategist 5 over 4; the grounding check caught one figure that no tool had returned, and the model removed
it. `docs/llm_check_result.md` and `docs/llm_check_live_result.md` hold the two runs.

## Tests

```powershell
python -m pytest -q                  # 297 automated tests, no internet needed
python scripts/validate_symbols.py   # live check of all 30 symbols (rows, INR, exchange, time zone)
python scripts/smoke_test.py         # live check of Yahoo (NSE), Google News India and the full pipeline
python scripts/intraday_check.py     # live check of Yahoo's intraday intervals for NIFTY 50 and four stocks
python scripts/llm_check.py --probe  # one request: key, model, tool calling and quota
python scripts/llm_check.py          # real LLM investigation, needs a key in .env
```

The live scripts write their results to `docs/` with the time of the run. See `docs/test_report.md` for the results
recorded during the build.

## Deployment

A public copy runs on Streamlit Community Cloud (entry point `app.py`, dependencies in `requirements.txt`, settings
through secrets). `docs/deployment.md` gives the steps for GitHub and Community Cloud, how to add the Gemini key as a
secret, and the checks to run on the public URL after each update.

## Project structure

```
market_sentinel/
  START_HERE.txt              how to open the project, for anyone who receives the zip
  run_app.bat                 one-click start on Windows (run_app.command on a Mac)
  launch.py                   creates .venv on first run, installs packages, starts the app, opens the browser
  app.py                      Streamlit entry point and navigation
  config/market.py            NSE conventions: time zone, session times, holidays, currency, official links
  config/watchlist.py         the 25-stock NSE watchlist, indices, peer groups and the fictional demo universe
  config/settings.py          thresholds, windows, weights and environment variables
  providers/                  market data (yfinance, cache, demo), intraday bars, news, symbol validation, LLM clients
  analytics/                  returns, anomaly detection, scoring, benchmark and peers, risk, replay, data quality,
                              intraday time-of-day baselines
  agents/                     monitor, investigator, strategist, orchestrator, tools, rubric, grounding check
  reports/                    Markdown and HTML report builder
  ui/                         theme, shared components, the six pages, the intraday panel
  tests/                      pytest suite and fictional fixtures
  scripts/validate_symbols.py live check of every configured NSE symbol
  scripts/smoke_test.py       live provider check for your own machine
  scripts/llm_check.py        runs one real LLM investigation and prints the model's decisions (--probe: one request)
  scripts/intraday_check.py   checks which intraday intervals Yahoo returns for NSE symbols
  scripts/make_share_zip.py   builds a clean zip to share
  requirements-lock.txt       exact package versions verified on a fresh Python 3.12 environment
  PRESENTATION_GUIDE.md       opening, five-minute demo, checklist, examiner questions
  docs/                       architecture, methodology, data sources, tests, manual, viva pack, deployment
  data/                       cache and saved investigations (created at runtime)
```

## Documentation

| Document | Contents |
|---|---|
| [PRESENTATION_GUIDE.md](PRESENTATION_GUIDE.md) | Opening, agent workflow, five-minute demo, checklist, examiner questions, limits |
| [docs/architecture.md](docs/architecture.md) | Diagrams of the components and of one investigation |
| [docs/methodology.md](docs/methodology.md) | Every formula, threshold, session rule and rubric criterion |
| [docs/data_sources.md](docs/data_sources.md) | Data-source register with links, access dates, terms and limits |
| [docs/test_report.md](docs/test_report.md) | What was tested, what passed, what could not be run |
| [docs/user_manual.md](docs/user_manual.md) | Page-by-page guide |
| [docs/limitations_and_responsible_use.md](docs/limitations_and_responsible_use.md) | Limits and responsible use |
| [docs/ai_use_declaration.md](docs/ai_use_declaration.md) | AI-use declaration for the submission |
| [docs/viva_guide.md](docs/viva_guide.md) | Plain-language explanation, worked example, likely questions |
| [docs/demo_script.md](docs/demo_script.md) | Presentation script and backup plan |
| [docs/deployment.md](docs/deployment.md) | Launcher and manual setup, sharing the zip, troubleshooting, Streamlit Community Cloud |

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| "Live market data could not be loaded" | No internet, or Yahoo is throttling. Wait a minute and press Refresh market data, or use demonstration mode. |
| "Today is an NSE trading holiday" | Correct behaviour: no new session is expected; the analysis runs to the previous session. |
| "Session in progress" pill | The latest bar was fetched before 16:15 IST; it is excluded until the day is final. Refresh after 16:15 IST. |
| Some symbols marked stale or unavailable | Their refresh failed; the cached copy is shown with its original time, or the symbol is listed as unavailable. Run `scripts/validate_symbols.py`. |
| News sources show "failed" | Network or the source is down. The investigation continues on price evidence and says news was unavailable. |
| LLM step shows HTTP 429 | Free-tier rate limit. The app already waited as asked; try again in a minute. If the message says the daily quota is used up, it resets at 12:30 IST, or use a key from another Google project. |
| Hosted app says "No LLM credentials are configured" | The key is only in your laptop's `.env`. Add `GEMINI_API_KEY = "your-key"` to the app's secrets on Streamlit Community Cloud and reboot the app. |
| Intraday watch says "Waiting for new data" | No newer complete bar exists yet: the market is closed, or Yahoo has not published the next 5-minute bar. The explanation under the status says which. |
| `No module named streamlit` (or pytest) | The command ran outside the project folder. `cd` into the project folder first, or double-click `run_app.bat`. |
| Windows Firewall asks whether to allow Python | Choose Cancel (the app still works on this laptop), or start it with `--server.address localhost`. |

More detail: [docs/deployment.md](docs/deployment.md).
