# Deployment guide

## Quickest start: the launcher

1. Install Python 3.11 or newer from python.org (the tests pass on 3.11, 3.12, 3.13 and 3.15) and tick "Add
   python.exe to PATH" during setup.
2. Extract the zip (right-click, Extract All) and open the extracted folder.
3. Double-click `run_app.bat`. On a Mac, open Terminal in the folder and run `python3 launch.py`, or double-click
   `run_app.command`.

The first start creates a private environment in `.venv` and installs the packages from `requirements.txt` (internet
needed, about 100 MB). Later starts skip that step unless `requirements.txt` changes, and take a few seconds. The
launcher then starts the app on the first free port from 8501 and opens it in the browser. Keep its window open while
you use the app; close it, or press Ctrl + C, to stop. If the `.venv` folder was copied from another computer and no
longer works, the launcher rebuilds it.

`launch.py` does the work on every system; `run_app.bat` and `run_app.command` only find a suitable Python and call
it.

## Manual setup on Windows

Use this if you prefer to see each step, or if the launcher reports a problem.

1. Open PowerShell in the project folder (Shift + right-click inside the folder, "Open PowerShell window here"), or
   move there with `cd "C:\path\to\market_sentinel"`. Every command below assumes you are in that folder.
2. Create and activate a virtual environment:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   If activation is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again, or use
   Command Prompt with `.venv\Scripts\activate.bat`.
3. Install the dependencies:

   ```powershell
   python -m pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. Optional: create a configuration file for an LLM key or other settings:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

5. Run the app: `streamlit run app.py --server.address localhost`, then open http://localhost:8501. Stop it with
   Ctrl + C.
6. Run the tests: `python -m pytest -q` (298 tests, no internet needed; about three minutes on the team laptop).
7. Check every configured NSE symbol: `python scripts/validate_symbols.py`. It writes
   `docs/symbol_validation_result.md`; a FAIL means the symbol must be corrected or removed in `config/watchlist.py`.
   Then check the live providers: `python scripts/smoke_test.py`, or `python scripts/smoke_test.py --no-llm` to skip
   the LLM call.
8. With an LLM key in `.env`, check the agent path: `python scripts/llm_check.py --probe` first (one small request:
   is the key accepted, is today's quota left?), then `python scripts/llm_check.py` (demonstration data, so only the
   LLM provider is contacted) or `python scripts/llm_check.py --live`. It prints every model turn, saves the run to
   history and reports PASS, PARTIAL (the risk step fell back) or FAIL, with the engine mode.
9. Check intraday bars from this computer: `python scripts/intraday_check.py`. It asks Yahoo Finance for NIFTY 50 and
   four stocks at 1, 2, 5, 15, 30 and 60-minute intervals, runs the app's intraday store and detector once on real
   5-minute bars, and writes `docs/intraday_check_result.md`.

Without activating the environment, the same commands work through its Python directly, for example
`.\.venv\Scripts\python.exe -m streamlit run app.py --server.address localhost`.

## Sharing the project as a zip

Do not zip the folder by hand. That would include `.env` with any API keys, the 100 MB `.venv` (which does not work
on another computer) and your cached data. Instead run, from the project folder:

```powershell
.\.venv\Scripts\python.exe scripts\make_share_zip.py
```

It writes `Market_Sentinel_share.zip` next to the project folder, about 200 KB, without `.env`,
`.streamlit/secrets.toml`, `.venv`, cached data, saved investigations or Python caches. The recipient extracts it and
follows `START_HERE.txt`, which describes the launcher steps above.

## Common failures

| Message or symptom | Cause | Fix |
|---|---|---|
| `py` is not recognised | Python launcher not installed | Use `python -m venv .venv`, or reinstall Python with the launcher option |
| `running scripts is disabled on this system` | PowerShell execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `No module named streamlit` or `No module named pytest` | The command ran outside the project folder, or the environment is not active | `cd` into the project folder first, or double-click `run_app.bat` |
| "This launcher has to run from the extracted project folder" | `run_app.bat` was opened from inside the zip | Right-click the zip, Extract All, then run it from the extracted folder |
| "Windows protected your PC" when opening `run_app.bat` | Windows flags scripts that came from a download | More info, then Run anyway |
| `ZoneInfoNotFoundError` | Time-zone data missing on Windows | `pip install tzdata` (already in requirements) |
| Live data could not be loaded, or "Rate limited by Yahoo Finance" | No internet or Yahoo throttling | Wait a few minutes, press Refresh market data; meanwhile use the cache or demonstration mode |
| A symbol is listed as unavailable | Yahoo returned no rows for it | Run `scripts/validate_symbols.py`; correct or remove the symbol in `config/watchlist.py` |
| LLM error 429 | Free-tier rate limit | The app waits as asked (up to 65 s, twice), then falls back and says so; try again later, or tomorrow if the daily quota is used up |
| LLM error 401 or 403 | Wrong or missing key, or no API credit | Check the key in `.env`; the app falls back to the rule-based engine and says so |
| LLM error 404 or "model not found" | Model name not available to your key | Set `LLM_MODEL` to a model your provider lists |
| Port 8501 already in use | Another copy of the app is running | The launcher moves to 8502 by itself; manually, `streamlit run app.py --server.port 8502` |
| Windows Firewall asks whether to allow Python | Streamlit listens on the network by default | Choose Cancel; the app still works on the laptop. Or run `streamlit run app.py --server.address localhost` |
| Charts look unstyled | Fonts blocked offline | Harmless; the app falls back to Segoe UI |

To reset everything, stop the app and delete the contents of `data/cache` (downloads) and `data/investigations`
(saved reports). Both are recreated automatically.

## Deploying to Streamlit Community Cloud

Status on 20 October 2026: the first version was deployed from the GitHub repository by the team and opened in a
browser that evening. The overview loaded live NSE data; the sidebar said no LLM key was found, because the app's
secrets held only `MS_DEFAULT_MODE`. The Gemini key existed only in the laptop's `.env`, which is never uploaded.
"Updating the hosted app" below fixes that. The steps need your GitHub and Streamlit accounts, so they are yours to
run. Only describe the hosted app as model-directed after step 4 of that section has passed.

### 1. Create an empty repository on GitHub

On github.com choose New repository, give it a name such as `market-sentinel`, and leave "Add a README", ".gitignore"
and "license" unticked so the first push does not conflict. Private is fine; Community Cloud asks for extra permission
to read private repositories when you deploy.

### 2. Push the project

Install Git for Windows if `git --version` is not recognised. Then, in PowerShell:

```powershell
cd "C:\Users\Navin shah\Documents\market_sentinel"
git init
git add .
git update-index --chmod=+x run_app.command
git status
```

`git status` should list about 95 files. It must not list `.env`, anything under `.venv`, cached CSV or JSON files
under `data`, or saved investigations; `.gitignore` excludes them, and only the two `.gitkeep` placeholders under
`data` are kept. Then:

```powershell
git commit -m "Market Sentinel"
git branch -M main
git remote add origin https://github.com/YOUR-USER/market-sentinel.git
git push -u origin main
```

If Git asks who you are, run `git config --global user.name "Your Name"` and
`git config --global user.email "you@example.com"` once and repeat the commit. GitHub Desktop does the same through
buttons if you prefer it.

### 3. Deploy the app

1. Go to https://share.streamlit.io and sign in with GitHub.
2. Click Create app, then "Yup, I have an app".
3. Choose the repository, the branch `main` and the main file path `app.py`. The App URL field is optional.
4. Open Advanced settings. Choose Python 3.12 (the tests pass on 3.11, 3.12, 3.13 and 3.15; 3.12 is also the
   Community Cloud default).
5. Paste your settings into the Secrets field in TOML format. Each value needs quotes. Top-level secrets become
   environment variables when the app starts (`ui/state.py`); app settings written in lower case or inside a table
   are also found. Automated tests check that they configure the app without the key ever being displayed:

   ```toml
   MS_DEFAULT_MODE = "live"
   # For the model-directed agents. GEMINI_API_KEY alone is enough: the provider, Google's OpenAI-compatible
   # endpoint and the model gemini-3.5-flash are then the defaults.
   GEMINI_API_KEY = "your-key"
   # Optional: ask for a passcode before the model is called, so a shared link cannot use up the daily quota.
   # MS_LLM_PASSCODE = "choose-a-phrase"
   # Optional: a different model.
   # LLM_MODEL = "gemini-3.5-flash"
   ```

   The longer form used in `.env` on the laptop (`LLM_PROVIDER = "openai_compatible"`, `LLM_API_KEY`,
   `LLM_BASE_URL`, `LLM_MODEL`) works too. Use one form, not both.

6. Click Save, or the deploy button shown, and wait. The first start installs `requirements.txt` and takes a few
   minutes.

Secrets can be changed later in the app's settings in your Community Cloud workspace.

### 4. Check the public app before quoting it

Open the URL in a private browser window and check:

1. The Market overview loads, the header shows the source and the latest complete NSE session, and the strip shows
   the NIFTY 50.
2. If live data loads, open the Anomaly monitor and the Investigation workspace and run one investigation.
3. If live data fails, the page names the provider error instead of showing invented prices. Switch the sidebar to
   Demonstration data and run one investigation there.
4. The sidebar's Reasoning engine note matches what you configured, and no key appears anywhere.
5. The Export tab downloads the HTML report.

## Updating the hosted app (Gemini on the hosted app, and intraday refresh)

1. Upload the changed files to the GitHub repository (or `git add`, `git commit`, `git push`). Streamlit Community
   Cloud redeploys on its own after a push; wait for the app to restart.
2. In share.streamlit.io, open the app's menu, Settings, Secrets. Keep `MS_DEFAULT_MODE` and add
   `GEMINI_API_KEY = "your-key"`. A separate key for the hosted app (ideally in its own Google project) lets you see
   and limit its use apart from the laptop's. Optionally add `MS_LLM_PASSCODE = "choose-a-phrase"`. Save.
3. From the same menu choose Reboot app, so the new secrets are read at start.
4. Check the reasoning engine:
   - The sidebar shows two engine choices, "Gemini (model-directed)" and "Rule-based protocol", and the caption
     "Configured: gemini-3.5-flash via Google Gemini ... key read from GEMINI_API_KEY". If it says "No LLM credentials
     are configured", open Engine diagnostics: it lists the names of the secrets the app found (never values).
   - If you set a passcode, enter it under the engine choice.
   - Press Test connection. It sends one small request and reports "Connected ... answered with a tool call", or the
     reason it failed (key rejected, daily quota used up with the reset time in IST, model not found, provider busy,
     timeout).
   - Run one investigation. The strip above the report says "Model-directed" with the model name, the model's turns
     and the tool calls it chose. The audit trail starts with an "Engine selection" entry naming the model, the
     endpoint host and the key variable.
5. Check the fallback: choose "Rule-based protocol" in the sidebar and run the same investigation. The strip says
   "Rule-based protocol, selected in the sidebar", and the audit trail has no model turns.
6. Check intraday bars: on the Market overview, press Refresh now under "Intraday watch". The status line shows the
   time of the request, the latest complete 5-minute bar in IST and the source. Outside market hours the status is
   "Waiting for new data", with the reason (session closed, weekend or NSE holiday) and the next open.

### If Yahoo blocks the hosted server

Yahoo throttles cloud-server addresses more often than home connections. If live data fails on the hosted app but
works on the laptop, set `MS_DEFAULT_MODE = "demo"` in the secrets and reboot the app from its menu, so visitors start
in the clearly labelled demonstration mode. Present live data from the laptop.

### If a new package release breaks the hosted app

`requirements.txt` gives tested ranges. `requirements-lock.txt` records the exact versions installed into a fresh
Python 3.12 environment on 20 October 2026, where all tests passed and the app started from a clean clone. Copying it
over `requirements.txt` and pushing makes the hosted app install exactly that set.

### Things to know about the hosted version

- The app runs on Streamlit's server, so live data, news requests and LLM calls all leave from that server, and depend on the providers, your keys, quotas and network availability there. The server's clock is usually UTC; the app shows NSE times in IST whatever the server's time zone.
- The server's disk is temporary. The cache and saved investigations disappear when the app restarts or sleeps.
- Free apps sleep after a period without visitors and take a short time to wake.
- Anyone with the link can use a public app, including your API key's quota. Set `MS_LLM_PASSCODE` so the model is only called after the passcode is entered, use a key with a spending limit, or leave the LLM unset in the hosted version.
- Gemini's free daily quota is counted per Google project and resets at midnight US Pacific time (12:30 IST until 1 November 2026, 13:30 IST after the US clock change). One investigation uses about 9 to 12 model requests.
- Intraday refresh runs only while someone has the Market overview open. The 5-minute bars live in the server's memory, are shared by everyone using the app, and are lost when it restarts or sleeps. Nothing collects bars in the background.
