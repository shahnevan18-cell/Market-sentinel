# LLM path check (live NSE data)

Run at 2026-10-20 11:08:26 UTC with `python scripts/llm_check.py --live`.
LLM: gemini-3.5-flash via OpenAI-compatible API (https://generativelanguage.googleapis.com/v1beta/openai/). Data: live. Event: HCLTECH.NS:2026-10-13.

Result: **FAIL: the investigation fell back to the rule-based engine (see LLM errors)**

- Engine: Rule-based fallback after LLM failure
- Investigator model turns 6, strategist model turns 1; successful tool calls by actor {'Market Investigator': 9, 'Market Investigator (rule-based fallback)': 4, 'Risk Strategist (rule-based fallback)': 4}
- Checks the orchestrator had to run itself: 0
- Tokens reported by the provider: 37495
- Figures the grounding check could not match: 0
- Leading explanation: Insufficient evidence to classify the event (Low confidence)
- LLM errors: The AI investigation did not complete (LLM provider returned HTTP 429: the daily request quota is used up, so waiting would not help. Try again tomorrow or switch LLM_MODEL. Detail: [{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota e). Findings below come from the rule-based engine.; The AI risk interpretation did not complete (LLM provider returned HTTP 429: the daily request quota is used up, so waiting would not help. Try again tomorrow or switch LLM_MODEL. Detail: [{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. For more information on this error, head to: https://ai.google.dev/gemini-api/docs/rate-limits. To monitor your current usage, head to: https://ai.dev/rate-limit. \n* Quota e). Rule-based risk notes are shown instead.
- Saved to history as HCLTECH-NS-2026-10-13_20261020T110902.json

## Model turns

```
Market Investigator: 5 model turn(s)
  turn 1: model asked for calculate_returns_and_volatility, calculate_abnormal_volume, compare_with_benchmark, compare_with_peers, search_public_news
    ok      calculate_returns_and_volatility: Return +8.42%, robust z +5.2, 10-day vol 53% annualised
    ok      calculate_abnormal_volume: Volume 8.9x median, robust z +4.3
    ok      compare_with_benchmark: Beta 0.90; NIFTY 50 +1.60%; abnormal return +6.99% (z +3.4)
    ok      compare_with_peers: 2 peers, median +5.46%; relative z +2.2; NIFTY IT +5.22% (z +5.1)
    ok      search_public_news: 72 item(s), 16 listed for the agent. Google News RSS (India edition): ok, Yahoo Finance headlines (yfinance): empty, NSE/BSE official disclosures (lin
  turn 2: model asked for get_market_context, list_news_items
    ok      get_market_context: 92% of watchlist up; 3 alert(s) that day; NIFTY 50 z +3.1
    error   list_news_items: Invalid arguments: 'limit' must be <= 15.
  turn 3: model asked for list_news_items
    ok      list_news_items: 43 matching item(s); 15 shown from offset 0
  turn 4: model asked for get_price_history
    ok      get_price_history: 5 daily rows to 2026-10-13; event-day return +8.42%
  turn 5: model asked for evaluate_hypotheses
    ok      evaluate_hypotheses: Leading: Insufficient evidence to classify the event (Low confidence)
    error   llm_call: LLM call failed: LLM provider returned HTTP 429: the daily request quota is used up, so waiting would not help. Try again tomorrow or switch LLM_MODEL
```
