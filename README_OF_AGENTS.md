# README_OF_AGENTS — Installation & Setup Guide for AI Agents

Audited against the current repository on **October 11, 2026**. The active app
is **text-only**. Historical benchmark records describe their original setup,
not necessarily today's pipeline.

This file is written for **AI coding agents** (and humans) who need to set up
**Folio · Local Notebook** on a **brand-new PC** and get it running without
breaking anything. Follow it top to bottom. Every command below was derived
from this repository's `pyproject.toml`, `requirements-lock-windows.txt`,
`run.ps1`, `.env.example`, `src/local_notebook/config.py` and
`src/local_notebook/main.py`.

---

## 0. Ground rules for agents (read first)

1. **Do NOT modify core project code just to install or run it.** Installation
   never requires editing anything under `src/local_notebook/`, `tests/`,
   `benchmarks/`, `pyproject.toml` or `requirements-lock-windows.txt`.
   Diagnose the interpreter, dependencies, configuration and logs first. If the
   failure is a code defect, report it instead of silently changing models or
   weakening checks to claim setup succeeded.
2. **Never commit secrets.** `.env` is git-ignored. Only `.env.example` (no
   secret) belongs in Git. Never paste an API key into any tracked file, log,
   issue, or commit message.
3. **Never commit runtime data.** `.venv/`, `.data/` (SQLite DB, LanceDB
   vectors, uploaded originals, downloaded models, logs), `*.log`,
   `.pytest_cache/`, `.ruff_cache/`, `.publish/`, `test-results/` are all
   git-ignored on purpose. Incomplete `*.partial.json` reports are also ignored.
   Preserve an existing `.env`, notebook database, uploads and model cache.
4. **Do not "upgrade" dependencies** unless asked. Version ranges in
   `pyproject.toml` are deliberate (e.g. `nicegui>=3.0,<4`).
5. **Do not replace the configured models to install the app.** The Gemini slots
   accept only `gemini-3.5-flash-lite` and `gemini-3.8-flash`. RunInfra has its
   own selection (§7); compatible endpoints accept their installed model IDs.
   EmbeddingGemma 2 is the only embedding model; BGE and MiniLM are removed.
6. **The app binds to `127.0.0.1` only** and rejects non-local origins
   (`LocalOnlyMiddleware` in `main.py`). Do not change this to `0.0.0.0`.
7. **One server at a time.** Before starting, check whether port `8080` is
   already in use (see §8) instead of launching a second copy.

---

## 1. What this project is

| Item | Value |
| --- | --- |
| Name | Folio · Local Notebook (`local-notebook` v0.2.0) |
| What | Local, NotebookLM-style study app: upload sources → chat with citations → Studio (mind maps, quizzes, reports, notes, data analytics, spreadsheets, deep research) |
| Language | Python application, with a small Vue/JavaScript mind-map component and CSS |
| UI + backend | **[NiceGUI](https://nicegui.io) ≥3,<4** — one single process serves both the web UI and the backend. There is **no separate frontend/backend** to start and **no Node.js/npm** step. |
| Retrieval | Gemma-tokenizer chunking, `google/embeddinggemma-2` local text embeddings, LanceDB, SQLite FTS5/BM25 and reciprocal-rank fusion; no separate reranker. Keyword-only mode uses LlamaIndex splitting. |
| Text-only mode | `TEXT_ONLY=True` in `config.py`: image uploads, OCR, vision/audio inference and LLM image attachments disabled |
| LLM | Gemini, RunInfra, or a Local / compatible endpoint selected in Settings |
| Storage | Fully local, in `<project>/.data/` |
| Default URL | http://127.0.0.1:8080 |
| Health check | http://127.0.0.1:8080/health → `{"status":"ok","app":"Folio",...}` |

---

## 2. Requirements

### 2.1 Required

| Requirement | Details |
| --- | --- |
| **OS** | Windows is the recorded local environment; CI is configured for Ubuntu. Linux/macOS instructions are not certification of every OS/architecture/package combination. |
| **Python** | **3.11, 3.12 or 3.13** (`requires-python = ">=3.11,<3.14"`). The project was verified on **3.11.9**. **3.14+ is NOT supported.** |
| **pip** | Bundled with Python (upgrade it: `python -m pip install -U pip`) |
| **venv** | Bundled with Python (on Debian/Ubuntu install `python3-venv`) |
| **Git** | Only needed to clone the repository |
| **Disk space** | Several GB free (PyTorch runtime + EmbeddingGemma 2 checkpoint + your data) |
| **RAM** | No measured minimum is established by the project; allow room for PyTorch/OpenVINO, model weights and inference buffers. |
| **Internet** | Needed for dependency/model downloads, cloud answer providers and web features; local text indexing can reuse a complete model cache. |
| **An LLM** | Gemini with `GEMINI_API_KEY`, RunInfra with `RUNINFRA_API_KEY`, or a compatible server. Without a configured provider, the UI and local indexing still run; answer generation needs a connection. |
| **Browser** | Any modern browser to open the UI (Chrome/Edge/Firefox) |

### 2.2 Python dependencies (installed automatically)

From `pyproject.toml`:

```
nicegui>=3.0,<4          llama-index-core>=0.12,<0.15   lancedb>=0.20,<0.30
sentence-transformers[image]==6.1.0      google-genai>=1.0,<3           httpx>=0.28,<1
transformers==5.19.0     torch>=2.5,<3
openvino==2026.4.1; platform_machine == 'AMD64' or platform_machine == 'x86_64'
pypdf>=5,<7              pypdfium2>=4,<6                python-docx>=1.1,<2
python-pptx>=1,<2        openpyxl>=3.1,<4               beautifulsoup4>=4.12,<5
fpdf2>=2.8,<3            python-dotenv>=1,<2            defusedxml>=0.7,<1
ddgs>=9.16,<10
```

Optional extras:

| Extra | Packages | Purpose |
| --- | --- | --- |
| `ocr` | `rapidocr-onnxruntime>=1.4` | Retained helper dependency; unnecessary for text-only setup. Installing it does not enable OCR. |
| `dev` | `pytest`, `ruff`, `psutil`, `playwright`, `matplotlib` | Tests, lint, browser checks, benchmark plots |
| `advanced` | `docling` | Reserved for future adapters — **not used** by the default pipeline; skip it |

The `sentence-transformers[image]` dependency remains installed, but its package
extra does not enable image features in the app.

### 2.3 Optional system software

| Software | Needed for | Notes |
| --- | --- | --- |
| **LibreOffice** (`soffice` on PATH, or `C:\Program Files\LibreOffice\program\soffice.exe`) | Legacy `.doc`, `.ppt`, `.xls` files only | Modern `.docx/.pptx/.xlsx` do **not** need it |
| **Unicode font** — Segoe UI at `C:/Windows/Fonts/segoeui.ttf` or DejaVu Sans at `/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf` | PDF export | These are the exact two paths checked by `exports.py`; fonts installed elsewhere are not automatically discovered. Debian/Ubuntu: `fonts-dejavu-core`. macOS needs separate font-path setup before PDF export can pass. |
| **Microsoft Edge** | `scripts/browser_check.py`, `scripts/agent_ui_check.py` (UI smoke tests only) | Not needed to run the app |

---

## 3. Get the code

```bash
git clone https://github.com/ryuu-la/NoteBookLm.git
cd NoteBookLm
```

> The rest of this guide calls that folder `<PROJECT>`. Run every command from
> inside `<PROJECT>`. (On the original machine it is `E:\NoteBookLM`.)

---

## 4. Install — Windows (PowerShell)

### 4.1 Verify Python

```powershell
python --version        # must print 3.11.x, 3.12.x or 3.13.x
```

If missing or too new/old, install Python 3.11 from https://www.python.org/downloads/
(tick **"Add python.exe to PATH"**). If several versions exist, use
`py -3.11 -m venv .venv` below.

### 4.2 Create the virtual environment

```powershell
# Run inside the cloned project; preserve an existing .venv.
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
```

> If PowerShell blocks `run.ps1`, run `.venv\Scripts\python.exe -m local_notebook.main`
> directly. No execution-policy change is needed.

### 4.3 Install dependencies — choose ONE option

**Option A — Install the declared dependency ranges and pinned model runtimes:**

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

(Use `-e .` for runtime only. Do not add OCR for the current text-only app.)

**Option B — Exact reproducible snapshot (Windows only):**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock-windows.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

`requirements-lock-windows.txt` is the exact verified Windows dependency
snapshot. **Use it on Windows only.**

### 4.4 Download EmbeddingGemma 2 (one-time, allow several GB for model and runtime)

```powershell
.\.venv\Scripts\python.exe scripts\download_models.py
```

Expected output ends with lines like `Embedding dimensions: 768` and
`EmbeddingGemma 2 ready for local text retrieval (vision and audio disabled).`. Models are cached under `.data\models\` unless `NOTEBOOK_MODEL_DIR` overrides this.
(If you skip this step the models are downloaded lazily on first use, which
makes the first import/question slow.)

The model is pinned to revision `914f7f89142e33e77833254d9c9b90c3cef7303b`.
On x86 CPU, an existing snapshot uses a cached **OpenVINO FP32** text graph under
`embeddinggemma2-openvino-f32-v1/<revision>/` in the model cache. A fresh download
can initially use PyTorch; a subsequent process then exports/compiles OpenVINO
once. Allow additional startup time and disk space for this conversion.

Other CPU architectures use PyTorch float32. CUDA uses PyTorch bfloat16 where
supported, otherwise float32; the code does not select Apple's MPS backend.
Set `NOTEBOOK_EMBED_BACKEND=pytorch` to diagnose an OpenVINO issue, then restart.
There is no automatic fallback if OpenVINO initialization fails. Retain caches
rather than deleting them to fix ordinary indexing slowness.

### 4.5 Configure the LLM (`.env`)

```powershell
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
notepad .env
```

Fill in your key:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_FAST_MODEL=gemini-3.5-flash-lite
GEMINI_MAIN_MODEL=gemini-3.8-flash
```

See §7 for RunInfra and Local / compatible alternatives. Select the matching
provider in Settings and test the connection; configured model IDs do not
guarantee account access or quota.

### 4.6 Run

```powershell
.\run.ps1
```

`run.ps1` simply does `Set-Location $PSScriptRoot` and runs
`.venv\Scripts\python.exe -m local_notebook.main`. Then open
**http://127.0.0.1:8080**. Stop with `Ctrl+C`.

---

## 5. Install — Linux / macOS

### 5.1 System prerequisites

Install Git and Python 3.11–3.13 through your OS's package manager. Some Linux
distributions package `venv` separately. The examples below assume `python3.11`
exists; use your compatible interpreter's actual command. LibreOffice is
optional; check §2.3 for PDF-export fonts. If a pinned package has no wheel for
your platform, report the exact failure instead of silently changing versions.

### 5.2 Virtualenv + install

```bash
# Run inside the cloned project.
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
```

> **Do not use `requirements-lock-windows.txt` on Linux/macOS** — it is a
> Windows-only snapshot. Use `pip install -e ".[dev]"` instead. OpenVINO's
> dependency marker covers `AMD64`/`x86_64`; ARM CPUs use the PyTorch path.

### 5.3 Models, config, run

```bash
.venv/bin/python scripts/download_models.py
test -e .env || cp .env.example .env   # then edit locally for the selected provider
.venv/bin/python -m local_notebook.main
```

Open **http://127.0.0.1:8080**.

---

## 6. First run — what to expect

* Starting the app prints: `NiceGUI ready to go on http://127.0.0.1:8080`.
* On the very first start the app creates `<PROJECT>/.data/` (SQLite DB,
  LanceDB vectors, uploaded originals, model cache) and **seeds a sample
  notebook** called *"The science of learning"* (original demo notes). Set
  `NOTEBOOK_NO_SAMPLE=1` to skip the sample.
* Quick smoke test after opening the UI:
  1. Open the sample notebook.
  2. Ask *"How do retrieval practice and spaced practice work together?"*
  3. Click a citation.
  4. Studio → generate a mind map / quiz / report.
* Without a configured Gemini, RunInfra or compatible provider, the UI loads but
  explains that a model connection is missing — that is expected, not a bug.

---

## 7. Configuration reference

### 7.1 `.env` (project root, git-ignored)

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | Your Google Gemini key. Loaded from the **project** `.env` and it **overrides** any inherited OS variable (even if the `.env` value is blank). |
| `GEMINI_FAST_MODEL` | `gemini-3.5-flash-lite` | Fast model. Only the two allowed IDs are accepted. |
| `GEMINI_MAIN_MODEL` | `gemini-3.8-flash` | Main model. |
| `RUNINFRA_API_KEY` | *(empty)* | Key for the RunInfra provider selected in Settings. |
| `NOTEBOOK_API_KEY` | *(empty)* | Key for the **Local / compatible** provider if your endpoint needs auth. |

**Restart the app after every `.env` change** — there is no in-app key dialog.
Project-file precedence applies to every loaded variable, not only API keys.
Keep test data/port overrides out of `.env` when running isolated browser checks:
the file would override their process-environment settings. Cloud generation
sends selected evidence and the question to the configured provider.

### 7.2 Optional process environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `NOTEBOOK_PORT` | `8080` | HTTP port (host is always `127.0.0.1`) |
| `NOTEBOOK_DATA_DIR` | `<PROJECT>/.data` | Where the DB, vectors, uploads, logs live |
| `NOTEBOOK_MODEL_DIR` | `<DATA>/models` | Model and compiled-graph cache; use an absolute custom path |
| `NOTEBOOK_EMBED_THREADS` | Half logical CPUs, rounded down, minimum 1, maximum 6 | Explicit integers are clamped to 1–8 |
| `NOTEBOOK_EMBED_BACKEND` | `openvino` for eligible CPU execution | Set `pytorch` for the installed PyTorch path. CUDA uses PyTorch regardless. |
| `NOTEBOOK_NO_SAMPLE` | unset | `1` = do not seed the sample notebook |
| `NOTEBOOK_OFFLINE` | unset | `1` = provider configuration check returns false. Not a network sandbox: does not prevent model downloads or all website requests. |

For model-cache-only operation after setup, Hugging Face's `HF_HUB_OFFLINE=1`
and `TRANSFORMERS_OFFLINE=1` require a complete local cache; they do not block
unrelated network access. Embedding model/revision/dimensions and `TEXT_ONLY`
are code constants, not environment model-picker settings.

Example (PowerShell): `$env:NOTEBOOK_PORT = "8090"; .\run.ps1`
Example (bash): `NOTEBOOK_PORT=8090 .venv/bin/python -m local_notebook.main`

### 7.3 Using a local / OpenAI-compatible model instead of Gemini

1. Start your server (e.g. Ollama at `http://localhost:11434/v1`) and pull a model.
2. In the app: **Settings → Provider → "Local / compatible"**, set the base URL
   and the model name.
3. If auth is required, add `NOTEBOOK_API_KEY=...` to `.env` and restart.
4. A **remote** endpoint must use **HTTPS**. The endpoint must support
   streaming and JSON output.

### 7.4 RunInfra

Set `RUNINFRA_API_KEY` in `.env`, restart, and select **Settings → Model provider
→ RunInfra**. The current app lists:

| Label | ID |
| --- | --- |
| GLM 5.3 Flash | `glm-5-3-flash` |
| Qwen 3.8 27B | `Qwen/Qwen3.8-27B` |
| DeepSeek V4.1 Flash | `deepseek-ai/DeepSeek-V4.1-Flash` |

RunInfra uses `https://api.runinfra.ai/v1` and one selected model for chat,
planning and Studio, without Fast/Main modes. Changing the selection in Settings
or the composer needs no restart. Use Test connection; this is a real provider
request and may incur usage charges. These are app-configured IDs, not a guarantee
of current provider access. Keys are not saved in the settings database.

### 7.5 Limits worth knowing

* Max upload size: **150 MB** per file.
* Supported sources: PDF, DOCX, PPTX, XLSX, CSV, TSV, TXT, MD, HTML/HTM, JSON,
  legacy DOC/PPT/XLS (needs LibreOffice), plus public website/PDF URLs and pasted text.
* Images, audio, video and OCR are disabled. PDFs need selectable text. For scans,
  supply a searchable PDF or externally extracted text; installing `ocr` does not enable it.
* Website downloads: **25 MB**, six redirect attempts, public addresses only.
* Studio data tools: source tables up to 50,000 rows / 500,000 cells.

### 7.6 Indexing and map behavior

Text is staged first, then embedded in batches of eight grouped by actual token
count. Semantic sections use 512 tokens with 64-token overlap. Existing vectors
are reused by content/model identity. Dense books can take minutes on CPU;
historical short-page fixtures are not full-book timing estimates.

Parsed sources are searchable while embeddings build; semantic coverage is
incomplete until Ready. Overviews use distributed text coverage. Each LLM answer
still sees a bounded evidence set, not the whole book. Restart recovery reparses
the source and skips individually committed vectors. Index version **4** rebuilds
older ready indexes while preserving originals and saved citation snapshots.
Deletion removes metadata immediately and queues durable file/vector cleanup.
Do not clear databases/caches or repeatedly reindex to accelerate an import.

The Semantic + keyword search switch does not instantly generate missing vectors
for existing sources; reindex affected sources when enabling semantic search.

Mind maps support canvas panning, independent topic dragging, wheel/pinch zoom,
Fit map and Reset layout. Connections follow topic positions. Arrow keys pan the
focused canvas; Shift + arrows nudge a topic. Manual positions are view state,
not saved artifact content. Click a topic for its explanation and evidence.

---

## 8. Running the app reliably (for agents)

### 8.1 Is it already running?

```powershell
# Windows
netstat -ano | findstr :8080
```
```bash
# Linux/macOS
lsof -i :8080
```

Health check from any shell:

```bash
curl http://127.0.0.1:8080/health
```

### 8.2 Starting as a *background* process

Some agent hosts clean up child processes when a command ends. Verify `/health`
after launch rather than assuming every terminal detaches identically.

**Windows (project helper — no console window, logs to `.data\logs\app.log`,
PID in `.data\app.pid`):**

```powershell
.\.venv\Scripts\python.exe scripts\launch_background.py
# needs psutil (in the [dev] extra) only when using --replace-pid <PID>
```

The helper appends logs and checks health. Its log/PID paths always use the
project `.data`, even when `NOTEBOOK_DATA_DIR` changes the application's storage.

**Linux/macOS:**

```bash
nohup .venv/bin/python -m local_notebook.main >> app.log 2>&1 &
```

`app.log` / `app.err.log` are git-ignored (`*.log`).

### 8.3 Restarting after code changes

The app runs with `reload=False`. Restart after Python or `.env` changes;
restart and refresh the browser after component JS/CSS changes. For a foreground
server, use Ctrl+C. For a server started by the project helper:

```powershell
$notebookServerPid = [int](Get-Content -LiteralPath .data/app.pid)
.\.venv\Scripts\python.exe scripts\launch_background.py --replace-pid $notebookServerPid
```

The helper checks command line and working directory before replacing a process.
A missing/stale PID must be investigated; never kill an unrelated listener.
Document imports have durable checkpoints, but Studio jobs are page-session
tasks: keep the notebook page open while they run. They do not survive a browser
reload or server restart.

---

## 9. Verify the installation

Run these from `<PROJECT>` (needs the `dev` extra). Windows paths shown;
on Linux/macOS replace `.\.venv\Scripts\python.exe` with `.venv/bin/python`.

```powershell
# Dependency consistency
.\.venv\Scripts\python.exe -m pip check

# Unit / integration tests
.\.venv\Scripts\python.exe -m pytest -q

# Lint (same as CI)
.\.venv\Scripts\python.exe -m ruff check src tests scripts benchmarks

# Secret / blocked-path scan (same as CI) — must print PASS
.\.venv\Scripts\python.exe scripts\check_secrets.py

# Committed benchmark consistency and API-free keyword regression gate
.\.venv\Scripts\python.exe benchmarks\publish.py --check
.\.venv\Scripts\python.exe benchmarks\rag.py --keyword --output test-results/rag-keyword.json

# Agent/data-tool tests only
.\.venv\Scripts\python.exe -m pytest tests\test_agent_tools.py -q
```

CI (`.github/workflows/`) runs: `ruff check`, `pytest -q`,
`benchmarks/publish.py --check`, `benchmarks/rag.py --keyword`, `pip check`,
`scripts/check_secrets.py` on Python 3.11.

The secret scanner examines Git's staged/tracked content, not every untracked
file or historical commit. Stage intended changes and rerun before publishing.
It checks runtime paths, credential patterns and configured provider/HF key values
without printing them.

Optional UI smoke tests (Windows + installed Microsoft Edge, uses Playwright,
isolated libraries, no live answer provider). Run sequentially because some
scripts share ports. Checks using real local embeddings need the model cache;
"no provider API" does not necessarily mean "no model download":

```powershell
.\.venv\Scripts\python.exe scripts\browser_check.py
.\.venv\Scripts\python.exe scripts\agent_ui_check.py
.\.venv\Scripts\python.exe scripts\mindmap_check.py
.\.venv\Scripts\python.exe scripts\website_import_check.py
.\.venv\Scripts\python.exe scripts\responsiveness_check.py
.\.venv\Scripts\python.exe scripts\harness_ui_check.py
```

The map check uses a deterministic local provider and tests mouse/touch gestures.
The website check simulates HTTP 403, then indexes pasted text using cached Gemma
with Hugging Face offline flags. The old `benchmarks/multimodal.py` targets an
inactive image path and is not a setup check for the current text-only app.

`scripts/indexing_batch_check.py` waits for active imports, reads a local text
sample without modifying its index, and measures real model inference. It writes
an ignored report under `test-results/`; it is not a full-document accuracy test.

Latest recorded checks: **204 tests**, Ruff, dependency and benchmark checks;
**19 map/Studio browser checks**, with no JavaScript errors. See
[verification](docs/VERIFICATION.md) for dates and scope. Reproduce the checks
you need instead of treating a recorded count as a guarantee on another machine.
The recorded local environment included the retained OCR helper; a fresh `dev`
install can skip its optional helper test without enabling OCR in the product.

> `scripts\browser_check.py --live` calls the **real** provider and consumes quota.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ERR_CONNECTION_REFUSED` on 127.0.0.1:8080 | Server not running, or it was killed when the launching shell exited | Start it detached (§8.2); confirm with `netstat`/`curl /health` |
| `Create the virtual environment and install dependencies first` (from `run.ps1`) | `.venv\Scripts\python.exe` missing | Do §4.2–4.3 |
| `No matching distribution` / build errors on install | Python 3.14+ or 3.10- | Install Python 3.11–3.13 and recreate `.venv` |
| `Address already in use` / port 8080 busy | Another copy (or other app) is using it | Reuse the running one, stop it, or set `NOTEBOOK_PORT` |
| Chat/Studio says to configure a model | Selected provider is unconfigured | Preserve/create `.env`, set that provider's key where needed, restart, and test the selected connection |
| Key set in OS env but app ignores it | Project `.env` intentionally overrides (even blank) | Put the key in `.env` |
| First question / first upload very slow | Model download or initial OpenVINO conversion/compilation | Run `scripts/download_models.py`; allow the first CPU graph build and retain caches |
| Dense PDF takes minutes | CPU inference over large text volume | Use parsed text while embeddings finish; do not reset/reindex repeatedly or use historical synthetic-page timings as an estimate |
| OpenVINO initialization fails | Runtime/platform or cached-graph problem | Record the error; set `NOTEBOOK_EMBED_BACKEND=pytorch` and restart to diagnose using the installed alternative |
| `PDF export needs a Unicode font` | No Segoe UI / DejaVu Sans | Linux: `apt install fonts-dejavu-core` |
| `Legacy Office files need LibreOffice` | `.doc/.ppt/.xls` uploaded | Install LibreOffice or re-save as DOCX/PPTX/XLSX |
| Scanned PDF has no text / image upload rejected | Text-only mode is intentional | Supply a searchable PDF or extracted text. Installing the OCR extra will not enable it. |
| `403 Only same-origin local access is allowed` | Opened via a LAN IP / different host | Use `http://127.0.0.1:8080` or `http://localhost:8080` |
| Provider quota / 429 errors | Provider limits | Wait or deliberately select another configured provider; there is no automatic cross-model fallback |
| PowerShell: `running scripts is disabled` | Execution policy | Run `.venv\Scripts\python.exe -m local_notebook.main` directly |
| Website 401/403, 429 or timeout | Website blocks access, rate-limits or does not respond | Follow the source-specific error; wait or use Paste article text. LLM settings cannot fix that website block. |
| Web search blocked / empty | Upstream search limits | Retry later or import/paste an accessible article; direct URLs can also be blocked |
| Mind map moved off-screen | Panning or topic dragging | Fit map recenters; Reset layout clears manual positions |

---

## 11. Repository map (read-only orientation — do not restructure)

```
<PROJECT>/
├─ pyproject.toml                 # deps, extras, ruff/pytest config
├─ requirements-lock-windows.txt  # exact Windows snapshot
├─ run.ps1                        # Windows launcher
├─ .env.example                   # secret-free template  (copy to .env)
├─ src/local_notebook/
│  ├─ main.py                     # entrypoint: NiceGUI app, /health, local-only middleware
│  ├─ config.py                   # .env loading, paths, model IDs, env vars
│  ├─ providers.py                # Gemini, RunInfra and compatible adapters
│  ├─ chat.py · agent.py          # answers, agent/tool orchestration
│  ├─ studio.py · data_tools.py   # mind maps/quizzes/reports · analytics & spreadsheets
│  ├─ research.py · retrieval/    # web research · embeddings, vectors, fusion, workflow
│  ├─ ingestion/                  # text parsers, website imports, legacy conversion, job queue
│  ├─ retrieval/cpu_encoder.py    # cached OpenVINO FP32 text graph
│  ├─ storage.py · seed.py        # SQLite layer · sample notebook
│  └─ ui/                         # NiceGUI pages, components, mindmap.js, styles/*.css
├─ tests/                         # pytest suite
├─ scripts/                       # model download, checks, background launcher
├─ benchmarks/                    # retrieval/RAG benchmarks
├─ docs/                          # architecture, verification, benchmarks
└─ .data/                         # (created at runtime, git-ignored) DB, vectors, uploads, models, logs
```

Further reading: `README.md` (features), `docs/ARCHITECTURE.md`,
`docs/VERIFICATION.md`, `CONTRIBUTING.md`.

---

## 12. Copy-paste quick start (Windows, everything at once)

```powershell
git clone https://github.com/ryuu-la/NoteBookLm.git
cd NoteBookLm
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe scripts\download_models.py
if (-not (Test-Path -LiteralPath .env)) { Copy-Item -LiteralPath .env.example -Destination .env }
# Edit .env locally for your selected provider, then:
.\.venv\Scripts\python.exe -m local_notebook.main   # open http://127.0.0.1:8080
```

## 13. Copy-paste quick start (Linux / macOS)

```bash
git clone https://github.com/ryuu-la/NoteBookLm.git
cd NoteBookLm
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python scripts/download_models.py
test -e .env || cp .env.example .env   # then edit locally for your selected provider
.venv/bin/python -m local_notebook.main   # open http://127.0.0.1:8080
```

---

### Agent checklist (tick before reporting "installed")

- [ ] Python 3.11–3.13 confirmed (`python --version`)
- [ ] `.venv` created inside `<PROJECT>` and dependencies installed with no errors
- [ ] `pip check` reports no broken requirements
- [ ] `scripts/download_models.py` printed the EmbeddingGemma 2 readiness lines
- [ ] Existing `.env` preserved or created from the template; selected provider configured; keys not printed or tracked
- [ ] `curl http://127.0.0.1:8080/health` returns `"status":"ok"`
- [ ] `pytest -q` and `scripts/check_secrets.py` pass
- [ ] A small text source, cited answer and Studio artifact work with the selected provider, or unavailable provider access is explicitly reported
- [ ] No files under `src/`, `tests/`, `pyproject.toml` were edited for the install
