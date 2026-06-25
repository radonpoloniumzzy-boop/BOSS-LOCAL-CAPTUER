# Recruiting Candidate Capture & AI Screen

Windows local desktop tool for:

- collecting candidate cards from Boss "Recommended Talent" and Liepin recommended pages
- deduplicating and storing them in SQLite
- exporting CSV
- screening collected candidates with a JD or custom prompt
- returning a compact UR / SSR / SR / R / N rating and one-line evidence-based persona

Current V1 uses a Chrome extension for recruiting page collection. Boss blocks Playwright-controlled pages on this machine, so the app keeps Playwright only for the generic automation foundation and switches page collection to:

`normal Chrome page + extension popup + local Python API`

## Environment

- Windows 10/11
- Official CPython 3.12
- Chrome or Chromium
- PySide6
- Playwright
- SQLite

Do not use an Anaconda-derived `venv` for this project. PySide6 often fails to load Qt DLLs in that setup.

## Install

```powershell
cd boss_local_tool
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```powershell
cd boss_local_tool
.\.venv\Scripts\Activate.ps1
python app.py
```

You can also launch the app by double-clicking either:

- `launch_boss_local_tool.vbs` in the project root
- `Boss Local Capture Tool.lnk` on your Windows desktop

First launch creates:

- `data/config.json`
- `data/boss_local_tool.db`
- `data/browser_profile/`
- `data/exports/`
- `logs/app.log`

## Collection Workflow

1. Start the desktop app and keep it running.
2. Open `Settings` and confirm the local API port, local API token, default export path, and target URL.
3. Load the unpacked extension from `extension/` in Chrome.
4. Open Boss or Liepin in a normal Chrome window and log in manually.
5. Go to the recommended talent page, such as Boss recommended talent or `https://lpt.liepin.com/recommend`.
6. Use the extension popup to:
   - collect the current loaded cards, or
   - auto-scroll and then collect
7. The extension sends cards to the local app.
8. The app deduplicates, writes to SQLite, and lets you export CSV.

## Load The Extension

1. Open Chrome and go to `chrome://extensions`.
2. Turn on `Developer mode`.
3. Click `Load unpacked`.
4. Select:

```text
D:\codex\BOSS-LOCAL-CAPTURE-review\extension
```

5. Pin the extension if you want easier access.

The extension popup lets you set:

- job title
- local API base, default `http://127.0.0.1:17863`
- local API token copied from the desktop app `Settings` page
- scroll mode
- scroll step
- wait milliseconds
- max rounds
- stop-after-no-new-rounds

## UI Pages

- `Dashboard`: open browser, show status, show local API endpoint, export latest batch
- `Automation Flow`: choose a saved screening profile and automatically screen each newly collected batch
- `Candidates`: search, filter, inspect details, export current result set
- `Settings`: browser path, export path, selectors path, local API port, logging, scroll config
- `AI Screen`: manage role JDs/prompts, choose candidate scope and AI model, run or stop screening, review result history
- `Review`: V3 placeholder

## Automated Collection And Screening

1. Create and save the target role in `AI Screen`, including its JD and screening prompt.
2. Open `Automation Flow` and select that saved screening profile.
3. Set the collection job title, recruiting page, AI provider, model, API key source, and optional candidate limit.
4. Save the automation settings in the desktop app. The desktop app no longer opens the recruiting page for this workflow.
5. Open the recruiting page yourself and click `AUTO: Scroll + Collect + AI Screen` in the Chrome extension.
6. When the extension import finishes, the desktop app immediately screens that exact capture batch.
7. Review the automation history and sort candidates by rating from UR to N or in reverse order.

Automation API keys remain in process memory and are never written to `config.json`. Non-secret automation settings are persisted so ordinary collection can continue to trigger screening after the workflow is enabled.

## AI Screening Workflow

1. Collect candidates from Boss or Liepin first.
2. Open `AI Screen` and enter the role name.
3. Upload or paste the JD. Uploading a JD immediately creates an editable default screening prompt.
4. Optionally upload your own prompt. The app appends a fixed compact JSON output contract.
5. Select the collected role or batch to screen.
6. Select `OpenAI`, `DeepSeek`, or a custom OpenAI-compatible endpoint, then choose or type a model name.
7. Enter an API key, or configure its environment variable, and click `Test Connection`.
8. Click `Start AI Screening`. Results are stored by run and sorted from UR to N.

API keys entered in the AI page are kept only in process memory. They are not written to SQLite or `config.json`.

AI ratings are assistive ranking signals and require human review. The app rejects prompts that use age, sex, marriage/childbearing, health/disability, photos, appearance, or image/temperament as automated employment screening criteria.

## Local API

The desktop app starts a local HTTP server for the extension:

- `GET /health`
- `POST /api/import/cards`
- `GET /api/automation/status`
- `POST /api/automation/start`

Default endpoint:

```text
http://127.0.0.1:17863
```

If you change the port in `Settings`, update the extension popup too.
All `/api/*` endpoints require the `X-Boss-Local-Token` header. Copy the token from the desktop app `Settings` page into the extension popup.

## Project Structure

```text
boss_local_tool/
  app.py
  build.ps1
  requirements.txt
  README.md
  extension/
  ui/
  automation/
  storage/
  ai/
  review/
  core/
  assets/
  data/
  logs/
  tests/
```

## Tests

```powershell
cd boss_local_tool
python -m unittest discover -s tests -v
```

## Package

```powershell
cd boss_local_tool
.\.venv\Scripts\Activate.ps1
.\build.ps1
```

Output goes to `dist\BossLocalTool\`.

## FAQ

### Why does the app say Boss cannot be opened in a Playwright-controlled browser?

Because Boss is redirecting controlled pages to `about:blank` on this machine. The app now uses a normal Chrome page plus extension mode for Boss.

### Why does clicking "Start Capture" in the app not start Boss collection?

For Boss and Liepin recruiting URLs, capture is triggered from the Chrome extension popup. The desktop app stays responsible for ingest, dedupe, storage, export, and logs.

### Where is the data stored?

- SQLite: `data/boss_local_tool.db`
- Logs: `logs/app.log`
- CSV exports: `data/exports/`

### Why keep Playwright in the project?

It still supports the original automation architecture, tests, and future non-Boss integrations. Boss itself is currently routed through extension mode.

## Current Scope

- V2 uses the candidate text already collected from recommendation cards.
- Full resume files and chat transcripts are not yet imported into the screening context.
- V3 remains the manual review workspace and review-history phase.
