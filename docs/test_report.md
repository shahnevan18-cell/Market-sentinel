# Test report (India version)

Recorded on 19 and 20 October 2026; the conversion to Indian equity markets was built and tested on 20 October, and
the hosted-Gemini fixes and the intraday watch on the night of 20 to 21 October.
Every result below comes from a run that actually happened. Anything that could not be run, or still has to be run
on the team laptop, is listed as such with the reason.

## Commands run

```bash
# Unit, integration and interface tests, in each environment listed below
python -m pytest -q -p no:cacheprovider

# Syntax of every module, scripts included, with Python 3.11, 3.12 and 3.13
python -m compileall -q .

# Dependency consistency in a fresh environment built only from requirements.txt
venv/bin/pip check

# The shared zip, then the full suite inside the unzipped copy
python scripts/make_share_zip.py <output.zip>

# The app in demonstration and live mode, driven in headless Chromium
streamlit run app.py --server.port 8611 --server.headless true

# The engine sidebar (fake key, no key, passcode) and the intraday panel (synthetic bars, accelerated clock),
# driven in headless Chromium with Playwright
streamlit run app.py --server.port 8632 --server.headless true

# On the team laptop, Windows 11 (results below)
python -m pytest -q
python scripts/validate_symbols.py
python scripts/smoke_test.py --no-llm
python scripts/llm_check.py            # and --live, and --probe for a one-request check
python scripts/intraday_check.py       # intraday intervals from Yahoo; still to be run
```

## Environments

| Run | Python | streamlit | pandas | numpy | plotly | yfinance | pydantic | Result |
|---|---|---|---|---|---|---|---|---|
| Latest versions | 3.13.16 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 297 passed, 0 failed, 0 skipped (93 s) |
| Minimum supported versions | 3.13.16 | 1.55.0 | 2.2.3 | 2.1.3 | 5.24.1 | 1.0 | 2.8.2 | 297 passed (83 s) |
| Python 3.15 | 3.15.0 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 297 passed (93 s) |
| Python 3.12 | 3.12.15 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 297 passed (94 s) |
| Python 3.11 | 3.11.17 | 1.66.0 | 3.0.6 | 2.4.6 | 7.1.0 | 1.7.0 | 2.14.1 | 297 passed (96 s) |
| Fresh environment from requirements.txt only (Community Cloud default Python) | 3.12.3 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 297 passed (97 s); `pip check`: no broken requirements |
| Unzipped copy of the shared zip (109 files, 387 KB; no API key inside) | 3.13.16 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 297 passed (94 s) |
| Team laptop, Windows 11, 20 Oct | 3.15.0 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 184 passed, 1 failed (183 s). The laptop was one test file behind (185 tests); the failure was the launcher port test, a Windows problem in the test itself (see the defects table) |
| Team laptop after the sector-index and port-test fixes, 20 Oct 16:24 IST | 3.15.0 | 1.66.0 | 3.0.6 | 2.5.4 | 7.1.0 | 1.7.0 | 2.14.1 | 186 passed, 0 failed (114 s). The 187th test, for the busy-provider wording below, was added after this run |

Sandbox runs were on Linux; the times are from the last run in each environment, on the night of 20 to 21 October,
with two suites running side by side. The suite uses deterministic synthetic fixtures only, with fictional company names in
every news fixture. It never reads the developer's `.env`, never calls a real LLM or a real data provider, and
writes its cache and history to a temporary folder.

## Results by file

| File | Tests | Passed | What it covers |
|---|---|---|---|
| test_returns.py | 6 | 6 | Daily simple and log returns, non-positive prices, annualised volatility, forward returns |
| test_anomaly_detection.py | 11 | 11 | Rolling baseline excludes the current day, insufficient history, zero MAD, missing values, beta recovery, the market model for a day ignores that day's returns (checked against an independent OLS fit), shock and volume detection, zero volume, missing benchmark, threshold sensitivity, calendar alignment |
| test_event_scoring.py | 7 | 7 | Weights sum to one, invalid configuration, score bounds, monotonicity and symmetry, one-sided volume, missing components, severity bands |
| test_historical_replay.py | 8 | 8 | No look-ahead (features identical on truncated data), changing future prices leaves past alerts unchanged, forward outcomes kept separate, label-evaluation definitions, every planted stock-specific demo shock detected, news after the 15:30 IST cutoff excluded, India-edition dated RSS query, as-of investigation uses truncated data |
| test_provider_failures.py | 37 | 37 | NSE bars keep their India date, yfinance metadata (INR, NSE, Asia/Kolkata, EQUITY or INDEX), unreachable provider stops quickly, rate limit stops further requests, only the NSE provider is offered, fresh cache, stale-cache fallback with original timestamp, non-INR data flagged and never relabelled, cleaning and quality checks, currency validation, IST session timing including a holiday, weekend special session kept, no return across a suspension gap, Google News India parsing and URL, Yahoo news parsing, 15:30 IST timing windows with holiday skipping, all news sources failing despite a link-only entry, India news search through the service with official links, a bar cached mid-session refetched after 16:15 IST, Indian headline rules for causes, moves, round-ups, noise (including multi-year price-target pages and stop-loss trading calls) and look-alike company names, a failed live load not refetched on every click |
| test_india_market.py | 38 | 38 | The 25-stock `.NS` watchlist with the NIFTY 50 benchmark and no US symbols, sector indices and peer-only groups, bare NSE symbols resolve, fictional demo universe, symbol validation (all pass on good data; missing, USD, short history, stale and zero-volume symbols reported), NSE holidays and trading days, session times in UTC and IST, partial bars judged in India time on any server, the demo calendar follows NSE trading days, rupee formatting with Indian grouping, company aliases and look-alike names, no US market terms in the interface, agents, reports or scripts, and the live NSE path end to end on labelled test prices for a stock with no peers and no sector index |
| test_llm_validation.py | 13 | 13 | Unknown tools rejected, argument validation, tool budget, nested schemas, submission schemas, numeric grounding, scripted LLM investigation end to end, orchestrator runs skipped checks, invented numbers trigger a revision, LLM failure reported and labelled, nonexistent tool calls refused, Anthropic and OpenAI-compatible wire formats |
| test_workflow.py | 20 | 20 | All 14 report sections present with IST times and no US terms, the six designed India demo scenarios reach the intended explanation, news unavailable is stated and limits conclusions (with a link-only entry present), history saved, US-version records hidden from the history list, different events give different reports, unknown event error, a single headline counts less than independent sources, a stock outside the illustrative portfolio is handled, activity lines label the holding weight and both VaR figures, publication and event dates kept apart, records carry the Indian market facts, news switched off counts as not searched |
| test_risk_lab.py | 8 | 8 | Single-holding and market stress formulas, concentration and reweighting, linear VaR scaling, historical VaR and ES, observed and hypothetical values kept apart, risk snapshot uses data to the event only and states its lookback and units, stress results in rupees |
| test_app_pages.py | 17 | 17 | All six pages render in demonstration mode; an investigation runs from the workspace on the preselected alert (Saffron Bank, 30 Sep 2026) with the engine named; demo mode is labelled; hosted secrets set the mode and the LLM without the key being displayed; the replay offers the designed scenarios at once; the risk lab shows rupees; no page shows SEC, 8-K, SPDR, S&P 500, New York, Wall Street, USD, sector fund or ETF |
| test_alert_monitor.py | 13 | 13 | The alert-table contract on zero rows, filters with populated alerts, all filters cleared, no severity, no alert type, no match, zero source alerts, a broken frame reported rather than hidden, no-data told apart from no-alerts, concise labels from the record, plain-English reasons, and the monitor page driven through clearing filters and Reset filters, with the selected-alert panel |
| test_guidance.py | 17 | 17 | Evidence levels A, B and C; the unresolved sector-against-company case and its discriminating checks; no repeated completed checks; the provisional earnings headline; categories from headline words; no catalyst; failed news search; validation first for unreliable data; routine data notes kept as limitations; corroboration over a single earlier mismatch; social posts and forecast pages excluded; the rating-change action; wording for every category; figures only from the record; no trading advice; level A only for a retrieved announcement, audited; different actions for different demo cases; saved records rebuilt; the Summary tab's A to E order |
| test_sentinel_grid.py | 7 | 7 | Priority colour equals each alert's score and quiet days are neutral, legend from the configured thresholds, missing sessions marked with a cross, rows ordered by priority, intensity view labelled as a different measure, direction arrows and click ids on alert cells, and the overview controls (colour, order, Reset view, alert picker) |
| test_packaging.py | 4 | 4 | The shared zip leaves out `.env`, deployment secrets, `.venv`, caches and saved runs and keeps the Mac launcher executable; the real project zip contains the launchers; the launcher reinstalls packages only when requirements.txt changes; a busy port moves the app to the next one |
| test_engine_modes.py | 42 | 42 | Gemini enabled by GEMINI_API_KEY alone, GOOGLE_API_KEY, LLM_API_KEY, LLM_PROVIDER=gemini and the laptop's long form; unusable settings named instead of ignored (no key, no model, unknown provider, switched off, no credentials, a Claude model with a Gemini key); hosted secrets copied, lifted from lower case and tables, updated when edited, and reported by name only; an unreadable secrets file reported without its content; the connection probe makes one real-format request, reads a tool call, and classifies a rejected key, a daily quota, a busy provider and an unknown model without showing the key; timeouts; the daily-quota reset at midnight Pacific shown in IST; the five engine states (model-directed, mixed, provider fallback with the reason, model output unusable, rule-based with the reason it ran); a failed first call leads to one rule-based run of each check, none forced; invalid tool arguments go back to the model; a failing tool is reported and the model continues; no key in the record, audit trail or report; the sidebar's engine choice, passcode lock and connection test; `llm_check.py --probe` |
| test_intraday.py | 28 | 28 | 5-minute bars read in IST, off-grid, out-of-session and duplicate rows dropped, never repaired; the bar still forming flagged, missing volume kept missing; the market clock on a holiday evening, a weekend and before the open; the newest complete bar expected at each time; Fresh, Waiting and closed-market explanations; peek never requests; the first refresh loads 60 days once, later refreshes only the last 5 days; a manual refresh bypasses the cache but not a request seconds old; a failure keeps the last good bars with their age; a first failure is Unavailable; one failing symbol keeps its earlier bars and says so; no automatic requests while the market is closed; two sessions refreshing together cause one request; history requested again on a new day; a stock-specific jump flagged against the same time of day; volume judged against its own time of day; a market-wide move not flagged as relative; short history display only; a forming or missing bar never used or filled; the intraday code never imports the LLM; the panel's controls, status and manual refresh; no simulated intraday in demo mode; the table shows n/a, never zero or None; `intraday_check.py` reports bars and failures |
| test_agent_robustness.py | 21 | 21 | Long tool results shortened without breaking JSON; a failing display summary does not stop a tool; the news search shows every group, company announcements first, with IST times and the stated event date; list_news_items pages and enforces its schema; grounding accepts rupee, crore and dollar figures quoted from sources, reads Indian digit grouping and written dates, and ignores clock times in IST and UTC; a malformed provider response falls back to rules; a partial fallback is named; OpenAI-compatible calls without ids still match their results; the decision trace shows an adaptive model's own choices; the record says whether it was saved; the final-bar time is shown in IST on any server; HTTP 429 waits as the provider asks, fails at once on a daily quota or an over-long wait, and respects Retry-After; a busy provider (HTTP 503) is logged as busy, with the wait marked as the app's own when the provider gives none; prompts and tools carry the Indian market facts; the LLM check refuses without a key and prints the model's turns |
| Total | 297 | 297 | |

## Coverage of the required test areas (India brief, section 9)

| Required area | Tests |
|---|---|
| Valid Indian ticker retrieval and failed-symbol handling | test_yfinance_provider_success_records_metadata, test_all_configured_symbols_pass_when_the_provider_returns_good_data, test_failed_or_doubtful_symbols_are_reported_not_kept_quietly (5 cases), test_no_cache_and_failure_gives_no_synthetic_data; live: `scripts/validate_symbols.py` |
| NIFTY 50 benchmark loading | test_live_watchlist_is_25_nse_shares_with_the_nifty_benchmark, test_live_nse_path_runs_end_to_end_for_a_stock_without_peers_or_sector_index, test_yfinance_provider_success_records_metadata (^NSEI as INDEX) |
| Time-zone conversions and session completeness | test_nse_bars_keep_their_india_date, test_session_timing_helpers_use_india_time, test_session_times_in_utc, test_partial_bar_is_detected_in_india_time_whatever_the_server_zone, test_bar_cached_mid_session_is_refetched_after_the_close, test_nse_holidays_and_trading_days, test_weekend_special_session_bar_is_kept_and_reported, test_bar_final_time_is_shown_in_ist_on_any_server |
| INR currency metadata and formatting | test_currency_metadata_is_validated (3 cases), test_non_inr_data_is_flagged_and_never_relabelled, test_rupee_formatting_uses_indian_grouping (5 cases), test_stress_results_are_labelled_in_rupees, test_risk_lab_shows_rupees |
| News timing and Indian company names | test_timing_classification_uses_the_1530_ist_close, test_india_news_search_through_the_service, test_headline_rules_separate_causes_moves_and_noise (10 cases), test_company_aliases_and_look_alike_names (17 cases), test_demo_announcement_keeps_publication_and_event_dates_apart |
| Provider failures, caching and stale data | test_unreachable_provider_stops_quickly, test_rate_limit_stops_further_requests, test_cache_then_stale_fallback_keeps_original_timestamp, test_all_news_sources_failing_is_reported, test_news_unavailable_is_stated_and_limits_conclusions, test_failed_live_load_is_not_retried_on_every_click |
| Anomaly scoring and benchmark regression | test_event_scoring.py, test_market_model_recovers_beta, the market-model check against an independent OLS fit, test_suspension_gap_gives_no_return_across_it |
| Historical replay and look-ahead safeguards | test_features_identical_when_future_data_is_removed, test_changing_future_prices_does_not_change_past_alerts, test_replay_attaches_future_outcomes_separately, test_orchestrator_historical_mode_uses_truncated_data, test_news_after_cutoff_is_excluded, test_detector_recovers_every_planted_stock_specific_shock |
| Risk metrics | test_risk_lab.py |
| Agent tool calls, structured outputs and fallback | test_llm_validation.py, test_agent_robustness.py, test_prompts_and_tools_carry_indian_market_facts |
| Synthetic scenarios | test_designed_scenarios_reach_the_intended_explanation (6 cases), test_replay_offers_the_designed_scenarios_immediately, test_demo_universe_is_fictional_and_labelled, test_demo_calendar_follows_nse_trading_days |
| Page rendering, start-up and deployment configuration | test_app_pages.py, test_packaging.py, test_hosted_secrets_configure_the_app_and_the_key_is_never_shown, the fresh-environment and unzipped-copy runs above |
| Gemini configuration, engine modes and fallbacks (hosted-Gemini brief) | test_engine_modes.py; see the next section for each required path |
| Intraday bars, cache policies and time-of-day detection (hosted-Gemini brief) | test_intraday.py |

## India conversion: defects found and fixed

Each defect was confirmed on the previous code before the fix, and each fix has a regression test.

| Defect | Evidence | Fix | Test |
|---|---|---|---|
| Every NSE bar was dated one day early | The US code converted bar timestamps to New York time. Yahoo stamps an NSE bar at 00:00 IST, which is 13:30 or 14:30 the previous day in New York | Dates are read in the exchange's own time zone (from the provider metadata, Asia/Kolkata by default) | test_nse_bars_keep_their_india_date |
| Every weekday counted as a session | The US code used business days, so an NSE holiday such as Dussehra (20 Oct 2026) would make fresh data look a session behind | NSE holiday table from the official circulars for 2024 to 2026; expected latest session and staleness are counted in NSE sessions | test_session_timing_helpers_use_india_time, test_nse_holidays_and_trading_days |
| The link-only entry for official pages hid a failed news search | With Google News and Yahoo both failed, the extra "link_only" status made "all sources failed" false, so the rubric gave H4 30 points for "no public explanation found despite searching" | Link-only and skipped entries are not counted as searches | test_news_unavailable_is_stated_and_limits_conclusions, test_all_news_sources_failing_is_reported |
| News switched off counted as searched | With `MS_NEWS_ENABLED=false` nothing was searched, yet H4 earned the "searched, nothing found" points | No usable news answer (all failed or none searched) is treated as unavailable, with the H3 and H4 caps | test_news_switched_off_counts_as_not_searched |
| The grounding check split Indian digit grouping | "12,34,567" was read as 12 and 34,567, both flagged as invented | Indian grouping, rupee prefixes (₹, Rs, INR) and lakh and crore units are understood; written dates are ignored | test_grounding_reads_indian_digit_grouping_and_written_dates, test_grounding_accepts_scaled_figures_quoted_from_headlines |
| Peer-only groups always capped confidence at Moderate | A stock in a group without a sector index (for example the demo's capital goods, or Titan, UltraTech and L&T live) counted "sector z" as a missing core input | A measure counts as missing only when it should exist for that stock | assertion in test_record_carries_indian_market_facts (Ironbridge reaches High) |
| Old US records appeared in the India history list | The laptop's `data/investigations` holds Bank of America and Harbour Bank runs from the US version | The list shows only records with the India market id; the files stay on disk | test_history_hides_records_from_the_us_version |
| HTTP 429 from a free-tier LLM ended the step after a 2-second retry | Real gemini-3.5-flash run on 20 Oct: the risk strategist stopped on "429 You exceeded your current quota" | The client waits as long as the provider asks (Retry-After or Google's retryDelay), up to 65 s and twice; a daily quota or a longer wait fails at once with a clear message; each wait is written to the audit trail | test_rate_limit_waits_as_the_provider_asks_then_succeeds and three related tests |
| Three configured sector indices had no usable history | Laptop symbol check, 20 Oct 15:59 IST: Yahoo returned 3 sessions (15 to 19 Oct 2026) for NIFTY Energy `^CNXENERGY`, NIFTY FMCG `^CNXFMCG` and NIFTY Auto `^CNXAUTO`, against at least 120 needed for a beta | Removed from the watchlist; the oil, gas and power, FMCG and autos groups are compared with peers only, as the report states. The methodology page now lists the sector indices from the configuration instead of a fixed sentence | test_sector_indices_belong_to_real_groups_and_others_are_peer_only; the short-history case of test_failed_or_doubtful_symbols_are_reported_not_kept_quietly |
| The launcher port test failed on Windows (a defect in the test) | Laptop run: the stand-in server queued only one connection. Windows refuses a connection once that queue is full, so the launcher's second check saw the busy port as free. Linux admits one connection beyond the queue size, so the sandbox never showed it | The stand-in server queues 16 connections, like a real server (Streamlit accepts connections as they arrive). The launcher is unchanged | test_launcher_moves_to_the_next_port_when_one_is_busy; passed on the laptop at 16:24 IST |
| The audit trail called a busy provider a rate limit and claimed the provider set the wait | India-version Gemini run, 20 Oct 16:27 IST: an HTTP 503 with no wait time was logged as "HTTP 503 rate limit: waited 5 s as the provider asked"; the 5 s was the app's own default | HTTP 503 is logged as "provider busy", and a wait the provider did not specify is labelled as such | test_busy_provider_wait_is_labelled_honestly |

## Product fixes of 20 October evening (issues found in the deployed app)

The deployed app was tested on 20 October and seven defects were reported. Each was traced to its cause in the code,
fixed there, and given regression tests. The guidance was then run on the laptop's two real saved live investigations
(HCL Technologies, 13 Oct; ITC, 5 Oct), which exposed four further faults; those are fixed and tested too, with
fictional names in the fixtures.

| Issue | Cause found | Fix | Tests |
|---|---|---|---|
| 6. Anomaly monitor crashed with KeyError 'priority_score' after filters were cleared | With Severity cleared, the frame had no rows; the alert-type mask built on it was an empty object-dtype Series, which pandas treats as a list of column names, so the next line saw a frame with no columns (reproduced on the old code). Zero-alert frames also lacked three derived columns | One alert-table contract (`EVENT_COLUMNS`) kept on every frame, including zero rows; filters built as explicit boolean masks in `analytics/alert_view.py`; a cleared multiselect means "all" and says so; separate states for no match (with Reset filters), no alerts and no data; a broken frame raises a named schema error | test_alert_monitor.py, cases 1 to 7 of the brief plus the page driven through clearing filters |
| 5. Alert selector truncated long labels | Labels joined name, date, every alert type and the score in one string | Labels "SYMBOL · date · type · Priority N" from the record in the monitor, workspace and overview, plus a full-width selected-alert panel with name, date, type, priority band, return, NIFTY 50 move, volume, a plain-English reason and investigate buttons; table clicks drive the selector | test_alert_label_is_concise_and_comes_from_the_record, test_selected_alert_panel_shows_the_full_details |
| 1. An unresolved investigation gave no next step | The rubric's conclusion only repeated the tied scores | `agents/guidance.py`: established facts, the two plausible explanations, why the evidence cannot separate them, the checks that would, and one next action | test_unresolved_case_still_gives_one_meaningful_next_action and related |
| 2. Company news was named without its catalyst or strength | No layer described the source behind "company-specific" | Evidence levels: A verified announcement, B potential catalyst with exact headline, publisher, IST time, retrieval time, link and access limitation, C none identified; a headline never verifies a cause | test_company_classification_names_the_candidate_catalyst_as_provisional and related |
| 3. Summary too technical | The tab led with the agents' statistical summary | Summary tab and report section 1 in business order (what happened, explanation and status, next action, unknowns), with the numbers in a collapsed "Quantitative evidence and methodology" section with plain definitions | test_summary_tab_renders_an_unresolved_live_case_in_business_order |
| 4. Follow-up checks generic | A fixed checklist was appended to every report | One prioritised, case-specific action from fixed rules, with reason, steps, reassessment condition, outcome, escalation, evidence references, official links and limitations; recorded in the audit trail | test_designed_demo_cases_get_different_actions, test_action_figures_come_from_the_record, test_guidance_never_gives_trading_advice |
| 7. Heatmap hard to read and to zoom | Colour was the return z-score with alert squares on top; Plotly's toolbar was hidden; the grid was fixed at 30 sessions | Priority-band colour from the configured thresholds, neutral quiet days, crosses for missing data, direction arrows and scores, a separate intensity view, period buttons (1 week, 1 month, 3 months, custom), row order, Reset view, visible zoom toolbar, click-to-inspect | test_sentinel_grid.py |
| Real data: a routine data note blocked the action | Any data-quality warning, such as a zero-volume day elsewhere, made "validate the data" the first action (HCL, ITC) | Only issues that undermine the event's numbers come first; routine notes are listed as limitations | test_routine_data_note_does_not_hide_the_real_next_action |
| Real data: wrong catalyst for ITC | The earliest "direct" headline was about another firm's tax "ITC demand" | The candidate is the subject reported by the most independent publishers, then its earliest report naming the company | test_best_corroborated_subject_beats_an_earlier_single_mismatch |
| Real data: social posts and forecast pages counted as evidence | Facebook and Instagram posts counted as publishers; a "Share Price Target 2026, 2027, 2030" page and a stop-loss trading call were labelled direct | Social posts excluded from catalyst choice and corroboration; new noise rules for forecast pages and trading calls, also applied when rebuilding saved records | test_forecast_pages_and_tips_never_lead, three new headline-rule cases |
| Real data: rating changes treated as filings | "Verify the reported a broker rating change in ... filing" | A separate action: confirm the broker's change and check for company news under it; category nouns fixed for every action | test_action_wording_reads_correctly_for_every_category |
| Audit wording for a busy provider | HTTP 503 with no wait time was logged as a rate limit "as the provider asked" | Logged as provider busy, with the wait marked as the app's own | test_busy_provider_wait_is_labelled_honestly |

The repaired pages were checked in headless Chromium on 20 October against the demonstration data: the overview grid
in 1-month, 3-month and intensity views and after Reset view; the monitor with Severity cleared, then Alert type
cleared, then a minimum priority of 100 (empty state) and Reset filters, with no error text on any page; the
workspace Summary of a fresh Saffron Bank run (verified, align-timing action); and the saved live HCL Technologies
record reopened from Investigation history, which showed the unresolved case with its checks and the NSE links. Live
data cannot be reached from the sandbox, so the live path was checked through the saved live records and the labelled
test prices; the team laptop rerun is listed below.

## Gemini on the hosted app and the intraday watch (night of 20 to 21 October)

### What the public app showed, and why

Opened from the laptop's browser at about 22:20 IST on 20 October, the public app loaded live data (30 of 30
symbols, latest session 19 October) and its sidebar read: "No LLM key found, so investigations use the rule-based
engine. Add ANTHROPIC_API_KEY (or LLM_API_KEY) ...". The app's secrets cannot be read from here. Two explanations
fit that screen: no key was in the secrets (the key lived only in the laptop's `.env`, which is git-ignored and never
uploaded), or a key was stored under a name the old code ignored, such as `GEMINI_API_KEY`. Either way the hosted app
never called Gemini. Tracing the path from secrets to the report found these defects:

| Defect | Effect | Fix | Tests |
|---|---|---|---|
| Only `ANTHROPIC_API_KEY`, or `LLM_API_KEY` with `LLM_PROVIDER`, `LLM_BASE_URL` and `LLM_MODEL`, enabled a model | A Gemini key under its natural name (`GEMINI_API_KEY` or `GOOGLE_API_KEY`) left the app on rules | `GEMINI_API_KEY` alone enables Gemini through Google's OpenAI-compatible endpoint with gemini-3.5-flash; the laptop's long form still works | test_gemini_is_enabled_by_any_supported_setup (5 cases) |
| `LLM_PROVIDER=gemini` fell through to OpenAI's URL with no model | The LLM was disabled without saying why | Gemini is a provider of its own with its defaults; a missing key or model is reported | test_unusable_settings_are_explained_not_silently_ignored (6 cases) |
| Secrets were copied only when the variable did not exist, nested tables and lower-case names were skipped, and every error was swallowed | An edited secret needed a full restart; a key inside `[gemini]` was ignored; a broken secrets box looked like "no key" | Values this app copied are updated, app settings are lifted from tables and lower case, an unreadable secrets box is reported without its content, and Engine diagnostics lists the names found | test_secrets_are_copied_lifted_and_updated, test_unreadable_secrets_are_reported_without_their_content |
| Every problem was shown as "No LLM key found ... Add ANTHROPIC_API_KEY (or LLM_API_KEY)" | The message pointed at the wrong variable for a Gemini user | The sidebar states the actual situation and what to set | test_sidebar_without_credentials_says_so |
| The report's engine label came from what was configured | A provider failure, a model failure and a deliberate rule-based choice were hard to tell apart | The engine mode comes from what happened in the run (next table), with an "Engine selection" audit entry naming the model, endpoint host and key variable, and each model turn recording the model, the tools it asked for and the token counts | test_model_directed_run_is_labelled_with_model_and_key_source, test_engine_strip_names_each_mode, test_mixed_run_is_named |
| Provider error text could carry a key (some messages echo the request) | A key could reach the report, the audit trail or the screen | Errors are redacted when created and when stored; the probe and diagnostics show names only | test_probe_classifies_provider_errors_and_hides_the_key, the key check in test_provider_errors_fall_back_and_say_why |
| After a failed first model call the orchestrator ran the required checks as "skipped by the investigator", then the rule-based fallback ran them again | Duplicate tool calls and a misleading warning in every provider-failure report (seen in the browser check below) | The fallback runs first; the orchestrator forces only what is still missing | test_fallback_runs_each_required_check_once_and_forces_none |
| A `LLM_MODEL=claude-...` line left in `.env` would be sent to Google with a Gemini key | A model-not-found failure at run time | Reported as a configuration problem before any request | the sixth case of test_unusable_settings_are_explained_not_silently_ignored |
| No cheap way to check a key | Checking meant a full investigation (9 to 12 requests) | Test connection in the sidebar and `llm_check.py --probe`: one request that must come back as a tool call | test_probe_reports_a_real_tool_call, test_sidebar_connection_test_reports_a_quota_failure_plainly, test_llm_check_probe_option |
| A public link could spend the quota | Anyone with the link could use up the day's requests before a demo | Optional `MS_LLM_PASSCODE`, compared in constant time; until it is entered the run is rule-based and says so | test_sidebar_engine_selector_lock_and_rules_choice |

### The five engine states and the required failure paths

| State in the report | When |
|---|---|
| Model-directed | Both agents completed with the model |
| Partly model-directed | One agent completed with the model and the other fell back, with the reason |
| Rule-based fallback after a provider error | The model was called and the provider failed: rejected key, daily quota (with the reset time in IST), rate limit, unknown model, busy provider, timeout, network |
| Rule-based fallback: the model's output could not be used | The model answered but stopped calling tools or submitted output that failed validation |
| Rule-based protocol, with the reason | Selected in the sidebar, no credentials configured, settings unusable, switched off, or locked by the passcode |

| Required path | Evidence | Result |
|---|---|---|
| Real Gemini call with credentials | Laptop, 20 Oct 21:13 IST, `llm_check.py --live` on the build before these changes | PASS (table "Real LLM runs" below). On this build, laptop, 21 Oct 01:46 IST: `llm_check.py --probe` PASS, gemini-3.5-flash answered with a tool call in 2.4 s (1 request, key read from LLM_API_KEY). A full investigation on this build is still to be run |
| Missing key | test_sidebar_without_credentials_says_so, test_rule_based_runs_say_why_no_model_ran, browser check | Passed |
| Invalid key | test_probe_classifies_provider_errors_and_hides_the_key (HTTP 400 and 401), test_provider_errors_fall_back_and_say_why | Passed |
| Daily quota | the same two tests (HTTP 429 per-day), test_quota_reset_is_midnight_pacific_shown_in_ist, test_sidebar_connection_test_reports_a_quota_failure_plainly | Passed |
| Timeout | test_probe_timeout_and_unconfigured, test_provider_errors_fall_back_and_say_why (read timeout) | Passed |
| Provider unavailable | HTTP 503 cases; browser check in which the sandbox's proxy really refused the connection to Google | Passed |
| Invalid tool arguments | test_invalid_tool_arguments_go_back_to_the_model | Passed: rejected by the schema, returned to the model, which recovered |
| Invalid model output | test_invalid_model_output_is_a_model_failure_not_a_provider_error, test_model_that_stops_using_tools_falls_back | Passed |
| Tool failure | test_a_failing_tool_is_reported_and_the_model_continues | Passed |
| Rule-based chosen deliberately | test_rule_based_runs_say_why_no_model_ran, the sidebar AppTest, browser check | Passed |

The failure-path tests drive the real orchestrator and agent loop with a scripted stand-in for the provider. No test
pushes a successful investigation through a mocked model and presents it as a real run.

### Intraday watch

The daily path was audited first: daily bars are cached on disk for six hours, kept in memory per server process, and
the monitor result is cached per dataset. The six-hour figure is a cache life, not a schedule: nothing refreshes on
its own. The intraday watch is a separate path (`providers/intraday.py`, `analytics/intraday.py`,
`ui/intraday_panel.py`) and the daily path is unchanged.

| Policy | Behaviour |
|---|---|
| Opening the page | No request ("peek"); shows what the server already holds, or Unavailable |
| Auto-refresh (5, 10 or 15 minutes, a Streamlit timed fragment) | Requests only when the held bars are older than one bar interval less 20 seconds, and never while the market is closed and the last session is complete |
| Refresh now | Bypasses that cache; a request that finished in the last 15 seconds is reused instead of repeated |
| Several open sessions | One lock and one store per server process, so simultaneous refreshes cause one request |
| History for the baselines | 60 days of 5-minute bars once per day; later refreshes ask for the last 5 days only |
| A failed refresh | Keeps the last good bars and reports Stale with their age; a symbol that fails alone keeps its earlier bars and is named |
| LLM | Never called; a test checks that the intraday modules do not import it |

The app was not able to fetch real intraday bars from the sandbox (Yahoo is blocked there). The panel was therefore
driven in headless Chromium inside a sandbox-only harness that serves the real panel and store with labelled
synthetic bars and a clock running 20 times faster: Unavailable on opening, Fresh after Refresh now, Cached within the
bar life, then new requests each time the bars expired (four request times in 48 seconds at a 15-second test
interval). The table showed "n/a" for values that do not exist (an index has no volume) and no negative zero.

### Browser checks of the engine states

The real app was run in demonstration mode, driven in headless Chromium. In the run with a fake Gemini key, the
sandbox's proxy refused every connection to Google, so the failures below are real network failures, not simulations.

| Set-up | What the page showed |
|---|---|
| Fake `GEMINI_API_KEY` | Sidebar: "Gemini (model-directed)" and "Rule-based protocol", "Configured: gemini-3.5-flash via Google Gemini (OpenAI-compatible endpoint), key read from GEMINI_API_KEY." Test connection: "Connection test failed ... The provider could not be reached (network error)." The run: "Rule-based fallback after a provider error", "model called: gemini-3.5-flash", and a red banner with the reason |
| Same, Rule-based protocol chosen | Preview "rule-based protocol, because selected in the sidebar"; report "Rule-based protocol, selected in the sidebar" |
| No key | Sidebar "No LLM credentials are configured ... set GEMINI_API_KEY in .env, or in the app's secrets when hosted"; report "Rule-based protocol: no LLM credentials configured" |
| Fake key and `MS_LLM_PASSCODE` | Sidebar asks for the passcode; report "Rule-based protocol: model locked by passcode" |

The fake key never appeared in any page's HTML.

## US assumptions removed or retained

| Assumption in the US version | India version |
|---|---|
| 24 US stocks, SPY benchmark, seven SPDR sector ETFs | 25 NIFTY 50 stocks (`.NS`), NIFTY 50 (`^NSEI`), three NSE sector indices (Bank, IT, Pharma), SENSEX for display; groups without an index use peers only and say so |
| New York time zone, 16:00 close, 16:15 bar rule | Asia/Kolkata, 09:15 to 15:30 normal market, bar final at 16:15 IST, 15:30 IST information windows |
| Weekdays as sessions | NSE holiday table 2024 to 2026; weekend special sessions kept |
| SEC EDGAR filings and Form 8-K items as company disclosures | Removed. NSE and BSE announcements are link-only because NSE's terms prohibit automated collection |
| SEC earnings proxy in the replay | Removed; demo planted-scenario check instead, live outcomes descriptive only |
| Google News US edition | India edition (`hl=en-IN, gl=IN`) with Indian vocabulary and company aliases |
| USD amounts and $ formatting | INR with ₹ and Indian digit grouping; ₹1 crore illustrative portfolio; currency validated per symbol |
| Tiingo provider (US end-of-day data) | Removed; it does not cover NSE shares |
| US demo companies (Harbour Bank and others) | Fictional India-themed companies with fictional announcements and an NSE calendar |
| Retained: Yahoo Finance through yfinance | Kept, because it serves NSE symbols and NIFTY indices; every symbol is checked by `scripts/validate_symbols.py` |
| Retained: Google News RSS and Yahoo headlines | Kept as the compliant automated news sources, with the India edition |
| Retained: the 252-day annualisation convention | Kept and documented (NSE has roughly 245 to 250 sessions a year) |
| Retained: statistics, scoring weights, rubric, agent loop, audit trail, risk formulas | Unchanged, apart from the evidence wording and the missing-input rule above |

## Real LLM runs (Google Gemini, OpenAI-compatible endpoint)

| Time (20 Oct) | Model | Data | Result |
|---|---|---|---|
| Before 12:56 IST | gemini-3.8-flash | US-version demo (Harbour Bank) | FAIL. The investigator ran four model turns of its own choice (five tools, then the announcement's details and market context, then the rubric, then a submission), but the grounding check flagged a clock time ("11") and the next call timed out after 90 s; the strategist ran one turn, then timed out. Both fell back to rules, labelled as such. Led to the clock-time fix and the 240 s timeout |
| 12:56 IST | gemini-3.5-flash | US-version demo (Harbour Bank) | PARTIAL by today's definition. The investigator completed the investigation itself: 5 model turns, 9 tool calls it chose, 0 checks the orchestrator had to force, 0 unverified figures, 29,474 tokens. The strategist completed one turn (three risk tools); its next call hit HTTP 429 (free-tier quota) and it fell back to rules. Led to the rate-limit handling |
| 16:26 IST | gemini-3.5-flash | India demo (Saffron Bank, 30 Sep 2026) | PASS. Both agents completed with the model and nothing fell back to rules. The Market Investigator took 6 model turns and 10 tool calls of its own choice: five evidence tools first, then market context, the news list and the announcement's details, then the price history, then the rubric. Its first submission quoted -9.6095, which no tool had returned; the grounding check sent it back and the corrected submission passed with 0 unmatched figures. The Risk Strategist took 3 turns and 5 tool calls, including two stress scenarios it chose (Saffron -10%, financials -10%). 0 checks forced by the orchestrator, 55,412 tokens, leading explanation company-specific news (High). One HTTP 503 (5 s wait) and one HTTP 429 (17 s wait, as Google asked) were absorbed by the retry handling |
| 16:38 IST | gemini-3.5-flash | Live NSE data (HCL Technologies, 13 Oct 2026: +8.42%, volume 8.9x median, NIFTY IT +5.22%) | FAIL, reported as such. The Market Investigator ran 5 model turns on real data: the five evidence tools, then market context and the news list (its first news request asked for more than the 15-item limit; argument validation refused it and the model asked again within the limit), then the price history and the rubric. Its next call hit HTTP 429 with the free tier's daily request quota used up, so the app failed at once instead of waiting, and both agents fell back to rules, labelled as such (37,495 tokens, 0 unmatched figures). The rule-based result was insufficient evidence (Low) |
| 21:13 IST | gemini-3.5-flash (key from a fresh Google project) | Live NSE data (HCL Technologies, 13 Oct 2026) | PASS. Both agents completed with the model on real NSE prices and Indian headlines, no fallback. The investigator chose 9 tool calls over 5 turns, paging the news list twice before scoring; the strategist chose 5 tool calls over 4 turns, including two stress scenarios. Its first submission quoted 7,317,480, which no tool had returned; the grounding check sent it back and the corrected submission passed with 0 unmatched figures. One HTTP 503 was absorbed and logged as provider busy. 0 checks forced, 70,098 tokens, leading explanation insufficient evidence (Low), matching the rule-based rubric. Record: `docs/llm_check_live_result.md` |

## Live checks on the team laptop

The build sandbox cannot reach Yahoo Finance or Google News (its network proxy refuses both hosts), so live NSE data
was verified on the team laptop (Windows 11, Python 3.15.0, yfinance 1.7.0) on 20 October 2026, an NSE holiday
(Dussehra), so the latest complete session was Monday 19 October. The result files are
`docs/symbol_validation_result.md` and `docs/live_smoke_test_result.md`.

| Check (20 Oct, 15:59 to 16:26 IST) | Result |
|---|---|
| `validate_symbols.py`: the 33 symbols then configured | 30 PASS, 3 FAIL. All 25 shares: 514 sessions from 23 Sep 2024 to 19 Oct 2026, INR, NSE, Asia/Kolkata, EQUITY. NIFTY 50 513 sessions, NIFTY Bank 512, NIFTY IT 512, NIFTY Pharma 511, SENSEX 512 (exchange BSE), all INR and INDEX. NIFTY Energy, FMCG and Auto: 3 sessions each, so they were removed (defects table) |
| `validate_symbols.py` rerun at 16:26 IST with the 30 symbols now configured | 30 PASS, 0 warnings, 0 FAIL |
| Yahoo prices for ^NSEI and RELIANCE.NS | PASS: last bar 19 Oct 2026, currency INR, time zone Asia/Kolkata, exchange NSE (3.9 s) |
| Google News RSS, India edition | PASS: 100 headlines from the last seven days (1.0 s) |
| Yahoo headlines for RELIANCE.NS | The request worked but returned no headlines, so in practice Google News India supplies the news evidence |
| Full live watchlist load | PASS: 33 of 33 symbols live, latest bar 19 Oct 2026, no failures (15.5 s) |
| Sentinel Monitor scan | PASS: 599 alerts in the two-year history, 1 in the latest session (4.9 s) |
| Rule-based investigation of a recent alert | PASS: ITC, 5 Oct 2026, leading explanation company-specific news (Moderate), 55 news items from Google News India, Yahoo skipped for a past date, NSE and BSE link-only, record saved (5.2 s). At the time ITC's group had the NIFTY FMCG index configured, which had no usable history; the group now uses peers only |

Earlier, in the sandbox with the hosts blocked, live mode showed "Received 0 of 33 symbols", a red source pill, the
provider errors and the NSE holiday note for 20 October, and offered demonstration mode without substituting data.

## Interface checks

The app was started in demonstration mode and every page was opened in headless Chromium on 20 October. The overview
shows the fictional universe with the NIFTY-style labels, the sentinel grid grouped by Indian peer groups and the
watchlist in rupees; the workspace's activity log shows times in IST; the replay page lists the ten designed
scenarios with their strongest alerts; the risk lab shows the ₹1 crore portfolio with Indian grouping. An
investigation of Saffron Bank completed (company-specific news, High confidence). An automated test reads every page's
text and confirms no US market term appears.

## Earlier history (US version, 19 and 20 October)

Before the conversion, the US version passed 121 tests in the same environments, and the laptop ran the live smoke
test on 19 October (Yahoo, SEC EDGAR and Google News all reachable; 32 of 32 symbols loaded). The audit of 20
October fixed the agent-path defects that carry over unchanged: the balanced news sample with `list_news_items`,
JSON-safe shortening of long tool results, the fallback on malformed provider responses, ids for OpenAI-compatible
tool calls, the "Mixed" engine label, the honest save message and the two-minute cache of a failed live load. Live
testing then had taught the rules that still apply: reaction headlines, tips and holdings reports are not
explanations, and one headline cannot decide between company news and unexplained trading.

## Not tested or still unverified

- A full real Gemini investigation on this build. The connection probe passed on the laptop at 01:46 IST on 21
  October (key, model, endpoint and tool calling); the last full model run is the 21:13 IST live PASS on the previous
  build. Run `scripts/llm_check.py --live` on the laptop.
- Yahoo's intraday intervals and live 5-minute bars. `scripts/intraday_check.py` must run on the laptop, and the
  first market session after this build is 21 October from 09:15 IST.
- The public app with this build. It still runs the earlier build until the new files are uploaded to GitHub and the
  Gemini key is added to its secrets; nothing here claims the public app is fixed.
- The 70 tests added on the night of 20 October have run in the sandbox environments only until the laptop reruns the
  suite (the laptop's last run passed 186 of 186, before the 41 tests of the earlier evening).
- Live data during NSE market hours for the daily path. The laptop checks ran on a holiday, so a bar still in
  progress (before 16:15 IST) has been tested only with labelled test data.
- How Yahoo treats each corporate action of the watchlist companies (bonus issues and demergers). The app flags moves
  of 25% or more but cannot see the provider's adjustment policy.
- The 2024 holiday list was read from a broker's copy of the NSE circular, because the official PDF could not be
  retrieved.
- `run_app.bat` on Windows has not been observed starting from scratch; the app on the laptop has been started from
  PowerShell.
