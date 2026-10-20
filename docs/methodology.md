# Methodology (India version)

All values below are the defaults in `config/settings.py`; exchange rules are in `config/market.py`. The alert
thresholds and the baseline window can be changed in the sidebar, and every report records the configuration it
used. Windows are counted in NSE trading sessions.

## 1. Data preparation

Daily bars are requested for about two years (760 calendar days) for 30 symbols: 25 NSE shares, the NIFTY 50, three
NSE sector indices and the BSE SENSEX. Yahoo stamps each NSE daily bar at midnight India time, and the date is read in
the exchange's own time zone (Asia/Kolkata). Each series is cleaned conservatively: rows are sorted, duplicated dates
are collapsed (the last value is kept), and non-positive prices or negative volumes are set to missing. Nothing is
interpolated or invented, and no observed bar is deleted because of its date. All symbols are aligned on the NIFTY
50's trading dates, so a missing day for one stock (for example a trading suspension) stays missing and no return is
computed across it.

If the latest bar was retrieved before 16:15 IST on its own date, the day is not final (NSE's normal market closes at
15:30, the closing session runs to 16:00 and trade modifications are allowed until 16:15). Such a bar is treated as
incomplete and excluded from detection until the data is refreshed.

Data-quality checks per symbol: missing and duplicated dates, non-positive prices, close outside the high-low range,
missing or zero volume (index volume is informational only), single-day moves of 25% or more (for a large Indian
company usually an unadjusted bonus issue, split or demerger, or a data error), recorded splits and bonus issues,
bars on weekends or listed NSE holidays (kept and reported, because NSE holds special sessions such as Muhurat
trading), currency against INR, short history, and staleness in NSE sessions against the expected latest session.

## 2. Returns

Prices are not comparable across stocks, so the analysis works with returns, which express each change relative to
the previous price. All returns use the adjusted close, which removes the mechanical effect of dividends, splits and
bonus issues when the provider records them. Returns do not depend on the currency.

$$r_t = \frac{P_t}{P_{t-1}} - 1 \qquad \ell_t = \ln\frac{P_t}{P_{t-1}}$$

Simple returns compound across time and aggregate across a portfolio; log returns add up across time. Volume is the
provider's share volume, used as reported.

## 3. Abnormal price move (robust z-score)

For each stock and day $t$, the baseline is the previous $L = 60$ returns, $r_{t-60}, \dots, r_{t-1}$. The day being
tested is never part of its own baseline. At least 40 valid observations are required.

$$z^{ret}_t = \frac{r_t - \operatorname{median}(r_{t-L..t-1})}{1.4826 \cdot \operatorname{MAD}(r_{t-L..t-1})}$$

MAD is the median of absolute deviations from the median. The factor 1.4826 makes it comparable to a standard
deviation when data are normal. Median and MAD are used because a single crash day inside the window barely changes
them, whereas it would inflate a mean and standard deviation and hide the next anomaly. If MAD is zero the z-score is
left missing instead of becoming infinite.

## 4. Abnormal volume

Volume is right-skewed, so the test uses log volume with the same robust z-score and window:

$$z^{vol}_t = \frac{\ln V_t - \operatorname{median}(\ln V_{t-L..t-1})}{1.4826 \cdot \operatorname{MAD}(\ln V_{t-L..t-1})}$$

The volume ratio is $V_t$ divided by the median raw volume of the same window. Zero or missing volume is skipped.
The test is one-sided: only unusually high volume raises an alert.

## 5. Market model and abnormal return

Alpha and beta are estimated by ordinary least squares on the previous 120 sessions (minimum 60 paired observations)
against the NIFTY 50, using only data up to $t-1$:

$$r_{i,t} = \alpha + \beta\, r_{m,t} + \varepsilon_t$$

The expected return on day $t$ is $\hat\alpha + \hat\beta\, r_{m,t}$, and the abnormal return is the difference:

$$AR_t = r_{i,t} - (\hat\alpha + \hat\beta\, r_{m,t}) \qquad z^{AR}_t = \frac{AR_t}{\hat\sigma_\varepsilon}$$

where $\hat\sigma_\varepsilon$ is the residual standard deviation of the estimation window (with an $n-2$ degrees of
freedom correction). This is the standard event-study market model. The prediction-error term of the forecast is
ignored, which slightly overstates $|z^{AR}|$ for short windows. When R-squared is below 0.10 the report warns that
the market explains little of the stock's movement.

## 6. Sector and peer comparison

Peer groups are configured in `config/watchlist.py`, starting from the NSE industry labels of the NIFTY 50
constituent list. The peer-relative return is the stock's return minus the median return of the other watchlist
stocks in its group that day, and it gets its own robust z-score from the previous 60 sessions.

Three groups have a matching NSE sector index with enough provider history, and it also gets a robust z-score:
NIFTY Bank (for the financial group, which holds the five banks), NIFTY IT and NIFTY Pharma. NIFTY indices are
weighted by free-float market capitalisation, so a large constituent influences its own sector index, which the
report notes. NIFTY Energy, NIFTY FMCG and NIFTY Auto were configured too, but on 20 October 2026 Yahoo returned only
three sessions for each, too few for a beta or a z-score, so the symbol check failed them and they were removed. The
oil, gas and power, FMCG, autos, consumer durables, and cement and steel groups are therefore compared with peers
only. Larsen & Toubro and Bharti Airtel have neither a sector index nor a peer in the watchlist,
so for them no sector or peer comparison is made and the report states it.

## 7. Volatility regime

$$\rho_t = \frac{\operatorname{sd}(r_{t-9..t})}{\operatorname{sd}(r_{t-69..t-10})}$$

The numerator includes the event day; the denominator is the 60 sessions before that recent window. Annualised
volatility multiplies a daily standard deviation by $\sqrt{252}$; NSE has roughly 245 to 250 sessions a year, so 252
is a convention. All volatility in the app is historical (realised). It describes the past and is not a forecast.

## 8. Alert rule and priority score

A stock-day is an alert when any test fires: $|z^{ret}| \ge 3$, $|z^{AR}| \ge 3$, or $z^{vol} \ge 3$.

Each component is normalised to 0-1 and weighted:

| Component | Normalisation | Weight |
|---|---|---|
| Abnormal price move | $\min(\lvert z^{ret}\rvert / 6, 1)$ | 0.35 |
| Market-relative move | $\min(\lvert z^{AR}\rvert / 6, 1)$ | 0.30 |
| Abnormal volume | $\min(\max(z^{vol}, 0) / 6, 1)$ | 0.25 |
| Volatility regime shift | $\min(\max(\rho - 1, 0) / 2, 1)$ | 0.10 |

$$\text{Priority} = 100 \times \sum_k w_k\, s_k$$

Severity bands: Critical from 70, High from 50, Moderate from 30, otherwise Low. A missing component scores zero and
is reported as missing. The score ranks analyst attention. It is not the probability that a headline caused the move
and not a prediction of future returns. Alerts for the same stock within three sessions are grouped into an episode.

## 9. News timing, relevance and official disclosures

The information window for an event on session $D$ runs from 15:30 IST on the previous NSE session to 15:30 IST on
$D$, with holidays and weekends skipped. Results declared after market hours therefore count for the next session,
which matches how Indian companies usually announce. Items are labelled `before_window`, `in_window`, `after_close` or
`unknown`. An item published after the event-day close cannot have caused that day's move. In as-of (historical)
investigations such items are not retrieved at all.

News comes from the Google News India edition (`hl=en-IN, gl=IN`) and Yahoo Finance headlines. Each item keeps its
publication time (the source's), its retrieval time (when the app fetched it) and, only when the source states it,
the date of the event it reports. A headline published on 30 September about a board meeting on 29 September keeps
both dates.

Official NSE and BSE announcements are not retrieved. NSE's terms of use (clause 9) prohibit systematic or automated
data collection, and neither exchange offers a documented public announcements API, so the app does not scrape the
exchange websites or call their internal endpoints. Each investigation lists the official pages (NSE announcements
and results, BSE results and filings, SEBI's directory) with the company name and NSE symbol to search for, marked
link-only. This is a manual verification step, not an automated filing search.

Relevance labels: `direct` (a timely company-specific item that could plausibly explain the move), `indirect`
(market or sector context), `uncertain`, `unrelated`. Without an LLM a keyword heuristic assigns them:

| Rule | Label |
|---|---|
| Company announcement inside the window (demo data only in this version) | `direct` |
| Headline naming the company and a cause word (results, net profit, provisions, order, bags, acquisition, SEBI, RBI, USFDA, block deal, downgrade and so on) inside the window | `direct` |
| Headline naming the company that only describes the move (tanks, zooms, slips, upper circuit) | `uncertain` |
| Round-up of several stocks ("stocks to watch") | `uncertain` |
| Tips, live price pages, forecast pages and holdings reports ("share price live", "should you buy", "multibagger", multi-year "share price target 2026, 2027, 2030" pages, "stock of the day" calls with stop loss and targets) | `unrelated` |
| Market words without the company name (Sensex, Nifty, FIIs, RBI policy, rupee) | `indirect` |
| Anything published after the event-day close | `uncertain` at best |

Company names are matched with aliases (RIL, HUL, L&T, M&M, SBI, Infy) after removing other companies whose names
contain an alias, such as Reliance Power, ITC Hotels, Tech Mahindra, Kotak Mahindra Bank (for M&M), SBI Life, HDFC
Life, NTPC Green and L&T Finance.

Reaction coverage is kept apart from explanations because on any large move news sites publish "shares tank"
headlines whether or not a cause exists; counting them would make every big move look explained. With an LLM, the
model reviews the labels and gives a one-sentence rationale for each; the report shows which basis was used. The
model first receives counts by timing and heuristic label and a balanced sample of items, and can page through every
retrieved item, so it can weigh evidence against the leading explanation as well as for it.

## 10. Hypothesis rubric

Two flags are used below. A move is sector-wide when the sector index's $|z| \ge 2$ in the same direction and at least
half of the peers moved the same way with $|z| \ge 2$. A move is market-wide when the NIFTY 50's $|z| \ge 2$ in the
same direction and at least 75% of the watchlist moved the same way. The stock-specific strength is
$s = \min(|z^{AR}|, |z^{rel}|)$, using only the measures that exist for the stock.

H1 Broad-market movement

| Criterion | Points |
|---|---|
| Benchmark $\lvert z\rvert \ge 2$ in the same direction | +35 (opposite direction: -30; $\lvert z\rvert < 1$: -10) |
| Market model explains the move: expected / actual return $\ge 0.5$ | +25 ($\le 0.2$: -15; moves under 0.5% are neutral) |
| Stock ordinary after market adjustment: $\lvert z^{AR}\rvert < 2$ | +20 ($\ge 3$: -30) |
| At least 75% of the watchlist moved the same way | +20 (50% or less: -10) |

H2 Sector-wide movement

| Criterion | Points |
|---|---|
| Sector index $\lvert z\rvert \ge 2$ in the same direction | +30 ($\lvert z\rvert < 1$: -10; no sector index configured: missing, stated as such) |
| At least half the peers moved the same way with $\lvert z\rvert \ge 2$ | +25 (34% or fewer in the same direction: -15; no peer in the watchlist: missing) |
| Stock in line with peers: $\lvert z^{rel}\rvert < 2$ | +25 ($\ge 3$: -30, or 0 when the move is sector-wide) |
| Sector $\lvert z\rvert$ exceeds market $\lvert z\rvert$ by 1.5 or more | +20 (market $\lvert z\rvert \ge 2$ and gap below 0.5: -20) |

H3 Company-specific news or announcement

| Criterion | Points |
|---|---|
| Stock-specific strength $s \ge 3$ | +30 (+10 if sector-wide; $2 \le s < 3$: +15; $s < 1.5$: -30) |
| Direct evidence inside the information window: a company announcement, or direct headlines from at least two publishers | +40 (one direct headline from a single publisher: +20; searched, none found: -15; sources unavailable: missing) |
| That item is a company announcement | +15 (live mode: neutral, with a pointer to the link-only official pages) |
| Volume $z \ge 3$ | +15 ($z < 1$: -5) |

In live mode a company announcement is never retrieved automatically, so strong live evidence for H3 needs direct
headlines from at least two independent publishers. The demo's fictional announcements exercise the announcement
path.

H4 Unusual trading activity without an identified public explanation

| Criterion | Points |
|---|---|
| Volume $z \ge 3$ | +30 ($2 \le z < 3$: +15; $z < 1$: -10) |
| Stock-specific pattern: $s \ge 2.5$, or heavy volume with $\lvert z^{ret}\rvert < 2$ | +20 or +15 (0 if sector-wide; $s < 1.5$: -10) |
| Sources searched and no direct, timely item found | +30 (+10 when a broad move already explains the event; strong direct evidence found: -40; a single direct headline: -20) |
| Market and sector $\lvert z\rvert$ both below 2 | +20 (otherwise -15) |

H5 Insufficient evidence

| Criterion | Points |
|---|---|
| Two leading explanations within 10 points | +30 |
| No news source could be searched | +25 |
| Beta missing, or the peer-relative z or sector z missing for a stock that should have one | +20 |
| Data-quality warnings for the security | +15 |
| Best explanation below 45 | +10 |

Scores are clipped to 0-100. When no news source returned a usable answer (all failed, or news switched off), H3 is
capped at 50 and H4 at 40, because the presence or absence of news cannot be established. The link-only entry for
the official pages is not a search and never counts as one.

Conclusion rule: if the best of H1-H4 scores below 45, or leads the next by less than 10 points, the outcome is H5
(insufficient evidence) with Low confidence. Otherwise confidence is High when the leading score is at least 70, it
leads by at least 25 points, no core input that should exist is missing and news was available; in every other case
it is Moderate. A group without a sector index, or a stock without peers, is a limit of the watchlist and does not by
itself lower the confidence. Scores describe fit with the evidence. They are not probabilities and do not prove cause.

## 11. Risk measures

One-day historical VaR at 95% is the 5th percentile loss of the last 250 daily returns up to the event date:
$\mathrm{VaR} = -Q_{0.05}(r)$. The "before the event" version excludes the event day. Expected shortfall is the
average loss beyond the VaR cut-off. Parametric VaR assumes normal returns: $1.645\,\sigma$ at 95%, which usually
understates tail losses. Maximum drawdown is the largest fall from a running peak over the last 120 sessions. Each
output states its confidence level, lookback and method; VaR and ES are fractions of position value, so they do not
depend on the currency. Rupee amounts appear only for the illustrative portfolio.

## 12. Risk scenario lab formulas

All scenario inputs are assumptions and are labelled as such. The illustrative portfolio is hypothetical, worth ₹1
crore by default, and amounts are shown with Indian digit grouping (charts in lakh).

| Scenario | Formula |
|---|---|
| Single holding shock | $\Delta V = V \cdot w_i \cdot \text{shock}$ |
| Sector shock | $\Delta V = V \cdot \text{shock} \cdot \sum_{i \in \text{sector}} w_i$ |
| NIFTY 50 shock | holding move $= \beta_i \cdot \text{shock}$; portfolio return $= \sum_i w_i \beta_i \cdot \text{shock}$ (missing beta treated as 1) |
| Concentration | $\mathrm{HHI} = \sum_i w_i^2$; effective holdings $= 1/\mathrm{HHI}$; other weights rescaled in proportion |
| Volatility rise | scale every observed portfolio return by $k$; historical and parametric VaR scale by $k$ |
| Threshold sensitivity | count of stock-days where any test reaches the chosen threshold |

## 13. Historical replay and evaluation

Detection in the replay uses the same trailing-window features, so an alert on day $D$ depends only on data up to
$D$ (tested by recomputing features on truncated data). After the alert, the replay attaches retrospective outcomes:

- forward raw return $P_{D+h}/P_D - 1$ for $h$ = 1, 5 and 20 sessions;
- cumulative abnormal return $\sum_{k=1}^{h} AR_{D+k}$ with alpha and beta frozen at $D$;
- continuation rate: the share of alerts whose later abnormal return has the same sign as the event-day abnormal return;
- volatility after alerts: mean absolute return over the next $h$ sessions divided by the mean absolute return over
  all stock-days in the period;
- the average CAR path from 5 sessions before to 20 after, separately for up and down alerts (event study). The five
  pre-event days fall inside the 120-session window used to estimate alpha and beta, so their abnormal returns are
  in-sample residuals and lean towards zero; the post-event days, which carry the evaluation, are out of sample.

There is no ground-truth label for a correct alert in live data, so no accuracy is claimed for NSE data. A natural
proxy label would be results and board-meeting dates, but those are NSE and BSE announcements, which the app does not
collect automatically. In demonstration mode the planted shocks are known, so the replay reports recall and precision
against them: all six stock-specific shocks are detected (recall 100%), and 43 of the 46 planted stock-days across all
scenarios. Precision against planted labels is low by design, because the generator's random returns have fat tails
and some unplanned days are genuinely unusual.

## 14. NSE calendar and sessions

| Rule | Value |
|---|---|
| Time zone | Asia/Kolkata (IST, UTC+05:30, no daylight saving) |
| Normal market | 09:15 to 15:30 IST |
| Daily bar final | 16:15 IST (end of trade modifications) |
| Trading holidays | Weekday holidays of the Capital Market segment for 2024, 2025 and 2026 from NSE circulars |
| Expected latest session | The latest trading day whose bar should be final at the time of retrieval; a holiday or weekend points back to the previous session |
| Special sessions | Weekend or holiday bars (Muhurat trading, Budget-day sessions) are kept and reported; they count as sessions only if the NIFTY 50 also has them |
| Years outside the table | Every weekday is treated as a possible session; the NIFTY 50's own dates still decide which sessions exist |

On 20 October 2026 (Dussehra) the expected latest session is 19 October, and the app says no new session is expected
that day. Muhurat trading on Sunday 8 November 2026 is announced; its timings are not yet notified.

## 15. Evidence levels, business summary and next action

After the rubric and the risk step, `agents/guidance.py` turns the record into the answer shown first in the Summary
tab and section 1 of the report. It uses only the record: tool outputs, rubric inputs and scores, the retrieved news
items with their timing, source type, publisher and links, the provider statuses, the validation results and the
link-only official pages. Nothing is fetched or invented, and the step is written to the audit trail as "Action
guidance" with the source ID it relied on.

Catalyst evidence levels:

| Level | Meaning | When |
|---|---|---|
| A, verified company event | A retrieved company announcement identifies the event | A company announcement inside the information window. Live NSE/BSE announcements are link-only, so only the synthetic demonstration announcements can reach level A in this version |
| B, potential catalyst, not yet verified | A headline suggests a cause; its article and the official filing were not read | A direct headline inside the window. The candidate is the subject (results, order, deal, corporate action, management change, regulatory matter, rating change, operational update) reported by the most independent publishers, then the earliest report of it that names the company. Social-media posts are not counted as publishers, and tips and forecast pages are screened out |
| C, no identified catalyst | No direct, timely item, or no news source could be searched | Otherwise; the two cases are kept apart |

A headline never verifies a cause. When company news leads on a level-B headline, the explanation is marked
provisional and the summary says, for example, that a headline reports quarterly results but the retrieved evidence
does not establish the full content or that it explains this move, and that the results filing and its timing should
be checked first. An explanation is marked verified only for a level-A announcement with High confidence. When the
rubric is inconclusive, the summary states what is established, the two explanations still in play with their
scores, why the evidence cannot separate them and which evidence would, with how each finding would move the
assessment.

The next action is chosen by fixed rules, in this order, so the most basic open question is settled first:

1. Data that undermines the event's numbers: the alert not reproduced on as-of data, too little baseline history,
   an unfinished session, no beta, or a data-quality error or large single-day gap on the event date. Routine notes,
   such as a zero-volume day elsewhere in the history, are listed as limitations instead.
2. A failed news search: check the official announcements by hand and re-run before calling anything unexplained.
3. An unresolved tie: the check that separates the two explanations (for sector against company news, the company's
   own filing in the window and the peers' shared driver).
4. The leading explanation's weakest link: verify a level-B headline against the filing and its time, check the
   broker behind a rating change and any company news under it, align a level-A announcement's time with the move,
   search for a catalyst when the move is stock-specific but nothing names a cause, check announcements and deal
   disclosures for unexplained volume (which is never treated as evidence of misconduct), or confirm a market or
   sector move.

Every action carries the reason, up to three steps, what would change the assessment, what it should clarify, when
to hold back a stronger conclusion, the official pages to check (live data only) and the limitations. Figures in the
guidance are copied from the record; no threshold, deadline or target is created for it. In demonstration mode,
steps that need an exchange website say what the live step would be, because the companies are fictional.

## 16. Sentinel grid colours

The grid's default colour is alert priority, using the same bands that label every alert: Low below 30, Moderate 30
to below 50, High 50 to below 70, Critical 70 and above, on an ordered scale from dim slate to red. Only alert cells
carry a band. A session without an alert is a neutral colour, and a session with no data for that stock carries a
cross, so missing data is never shown as a low score. Alert cells also show an arrow for the direction of the move and
the score when cells are wide enough, so the grid does not rely on colour alone. The alternative view colours every
cell by the robust z-score of the day's return, which measures how unusual the move was. Anomaly intensity and alert
priority are related but not the same: priority also weighs market-relative movement, volume and the volatility
regime. Neither says whether a stock is a good or bad investment.

## 17. Reasoning engine modes

Every investigation records which engine ran and why (`engine.mode` in the record, an "Engine selection" entry at
the top of the audit trail, and the strip above the report):

| Mode | Meaning |
|---|---|
| `llm` | The model (for example Gemini, `gemini-3.5-flash`) chose the tools, read their results and submitted findings that passed schema validation, for both the investigation and the risk step |
| `mixed` | One of the two steps was model-directed; the other fell back to the rule-based protocol, and the reason is named |
| `llm_provider_fallback` | The model was called but the provider returned an error (key rejected, daily quota used up, rate limit, model not found, provider busy, timeout, network, unusable response); the rule-based protocol produced the report |
| `llm_failed` | The model ran but its output could not be used (it stopped calling tools, its findings failed validation twice, or it ran out of turns); the rule-based protocol produced the report |
| `rules_selected` | The rule-based protocol was chosen in the sidebar |
| `rules_no_credentials` | No key is configured on this deployment |
| `rules_config_problem` | LLM settings were given but cannot be used (for example a provider without a key, or no model name) |
| `rules_switched_off` | `LLM_PROVIDER` is set to none |
| `rules_locked` | The deployment asks for a passcode (`MS_LLM_PASSCODE`) and it has not been entered in this session |

A configured key is not the same as a model-directed run: the mode is set from what actually happened. Each model
turn in the audit trail records the model name, the tools it asked for and the provider's token counts; each failed
call records its error category. Provider messages are stored with keys removed. The sidebar's Test connection
sends one small request that must come back as a tool call, so it checks the key, the model name, the endpoint and
the tool-calling path in one request without running an investigation.

## 18. Intraday watch (5-minute bars)

The Market overview has an optional intraday section, separate from the daily analytics above. It changes no daily
score, adds no alert and starts no investigation, and it never calls the LLM.

Data. 5-minute bars for NIFTY 50 and the 25 stocks come from Yahoo Finance through yfinance (unofficial; it may be
delayed and does not promise when a bar appears). Timestamps are read in IST. Only regular-session bars on the
5-minute grid from 09:15 to 15:30 IST are kept; rows outside the session, rows off the grid (a live quote stamped at
the current minute), duplicates and rows without a price are dropped and counted. A bar whose end lies after the
time it was received is still forming: it is shown, marked, and excluded from every statistic. Missing bars are
never filled, and missing or zero volume is stored as missing (Yahoo reports no volume for indices). Daily bars are
never relabelled as intraday; in demonstration mode the section says intraday bars are not simulated.

Refresh. The section refreshes only while the page is open: a Streamlit timed fragment reruns it every 5, 10 or 15
minutes when Auto-refresh is on (off by default), and Refresh now requests at once. Bars are held in the server's
memory and shared by all sessions:

| Rule | Value |
|---|---|
| Cache life of the latest bars | one bar interval less 20 seconds (4 min 40 s) |
| Refresh now | ignores the cache; a request that finished in the last 15 seconds is reused instead of repeated |
| Two sessions refreshing together | one request (requests are serialised by a lock) |
| History for baselines | about 60 days of 5-minute bars, requested once per day; later refreshes request the last 5 days |
| A failed refresh | keeps the last good bars and states their age; one failing symbol keeps its earlier bars, labelled |
| Market closed | automatic refresh sends no request once the last session's bars are in memory; Refresh now still does |

Status. Each refresh is labelled Fresh (the newest complete bar is at most one bar behind the clock), Waiting for new
data (no newer bar since the last refresh, data more than one bar behind the clock, or the market closed, with the
reason and the next open), Cached (served from memory without a request), Stale (the last request failed; older bars
shown with their age) or Unavailable (nothing loaded, or the first request failed). The status line also shows the
time of the last request, the latest complete bar in IST, the interval and the source.

Detection. Intraday volume and volatility follow a strong daily pattern, busy after the open and before the close
and quieter around midday, so each measure of the latest complete bar is compared with the same bar of the day in up
to 40 earlier sessions:

- 5-minute return: log change from the previous bar of the same session; the 09:15 bar is measured from the previous
  trading session's last bar, so its baseline also consists of opening bars with their overnight gaps. After a
  missing bar the return is left missing.
- Return relative to NIFTY 50: stock return minus beta times NIFTY 50's return for the same bar, with beta estimated
  from the baseline sessions' 5-minute returns (opening bars excluded, at least 300 pairs, limited to -1 to 3).
- Volume: log volume of the bar.

Robust z = (value - median) / (1.4826 x MAD) over the baseline values of that bar of the day. A bar is flagged when
|z| is 4 or more for either return measure, or z is 4 or more for volume. That is stricter than the daily tests
because 26 symbols with 75 bars a session make about 2,000 comparisons a day; a lower cut-off would flag chance
extremes every hour. A measure needs at least 15 earlier sessions with a value for that bar of the day; with fewer it
is shown for display only and never flagged. The section also lists, for the session so far, the largest 5-minute
move for its time of day per stock. Flags are prompts for review, not conclusions, and say nothing about whether a
stock is a good or bad investment.
