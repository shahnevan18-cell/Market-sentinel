# AI-use declaration

Project: Market Sentinel (India), Business Analytics (Theme 4: Agentic AI)
Team: Darshil Mittal (A016, SAP ID 74052400181) and Nevan Shah (A043, SAP ID 74052400240)

## Generative AI used to build the project

The source code, tests and documentation in this repository were produced with Claude (model Claude Opus 5.5, by
Anthropic), used through claude.ai on 19 October 2026. The team wrote the project specification (the scope, the three
agent roles, the analytical methods required, the honesty rules and the acceptance criteria) and gave it to Claude as
the build brief. Claude wrote the code and documents, ran the automated tests in its own sandbox and reviewed
screenshots of the running interface. On 19 and 20 October Claude also set the project up on the team laptop, fixed
defects found with live data, audited the code against a second team brief (agent path, analytics, interface,
deployment), fixed the defects that audit found and wrote `PRESENTATION_GUIDE.md`. On 20 October, following a third team brief,
Claude converted the project from US to Indian equity markets: the NSE watchlist and NIFTY benchmarks, the IST
session and NSE holiday rules, rupee formatting and currency checks, the Indian news layer with link-only official
disclosures, the India-themed fictional demonstration data, the agent prompts and tools, the tests and the
documents. Each fix is listed with its evidence in `docs/test_report.md`.

## AI inside the application

The application can optionally call a large language model at run time (the Anthropic API or an OpenAI-compatible
endpoint) for two roles: the Market Investigator, which chooses which analysis tools to call and judges whether news
headlines are relevant, and the Risk Strategist, which writes qualified risk notes. Without an API key the app runs a
rule-based engine and labels its output accordingly. In both modes:

- every number shown is computed by Python functions, not by the model;
- anomaly detection and hypothesis scoring are deterministic and documented in `docs/methodology.md`;
- every model turn and tool call is recorded in the audit trail of each report;
- reports state which engine produced them and whether any AI step failed.

## Verification

The automated test results recorded during the build are in `docs/test_report.md`. Live connections to Yahoo
Finance (NSE symbols) and Google News could not be made from the build sandbox; they are verified on the team's own
computer with `python scripts/validate_symbols.py` and `python scripts/smoke_test.py`, which record their outcomes in
`docs/symbol_validation_result.md` and `docs/live_smoke_test_result.md`. The LLM path is tested automatically with
scripted models and was run against a real provider (Google Gemini) on 20 October 2026 with
`python scripts/llm_check.py`; the outcomes, including the failures, are in `docs/test_report.md`.

## Team review record

Complete this table before submission so the declaration reflects what the team actually checked.

| Date | Team member | What was reviewed, tested or changed |
|---|---|---|
| | | |
| | | |

The team is responsible for the submitted work, including any errors that AI assistance may have introduced.
