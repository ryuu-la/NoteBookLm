# README_OF_AGENTS — Installation & Setup Guide for AI Agents

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
   If something fails, fix the *environment* (Python version, missing system
   package, missing `.env`), not the source.
2. **Never commit secrets.** `.env` is git-ignored. Only `.env.example` (no
   secret) belongs in Git. Never paste an API key into any tracked file, log,
   issue, or commit message.
3. **Never commit runtime data.** `.venv/`, `.data/` (SQLite DB, LanceDB
   vectors, uploaded originals, downloaded models, logs), `*.log`,
   `.pytest_cache/`, `.ruff_cache/`, `.publish/`, `test-results/` are all
   git-ignored on purpose.
4. **Do not "upgrade" dependencies** unless asked. Version ranges in
   `pyproject.toml` are deliberate (e.g. `nicegui>=3.0,<4`).
5. **Do not change the model IDs.** Only `gemini-3.5-flash-lite` (fast) and
   `gemini-3.8-flash` (main) are accepted by the app (`config.GEMINI_MODELS`).
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
| Language | Python only |
| UI + backend | **[NiceGUI](https://nicegui.io) ≥3,<4** — one single process serves both the web UI and the backend. There is **no separate frontend/backend** to start and **no Node.js/npm** step. |
| Retrieval | LlamaIndex chunking, `BAAI/bge-small-en-v1.5` local embeddings (FastEmbed), LanceDB vectors, SQLite FTS5/BM25, reciprocal-rank fusion, MiniLM cross-encoder reranker |
| LLM | Google Gemini (needs your own API key) **or** any OpenAI-compatible endpoint (e.g. Ollama/LM Studio) |
| Storage | Fully local, in `<project>/.data/` |
| Default URL | http://127.0.0.1:8080 |
| Health check | http://127.0.0.1:8080/health → `{"status":"ok","app":"Folio",...}` |

---

## 2. Requirements

### 2.1 Required

| Requirement | Details |
| --- | --- |
| **OS** | Windows 10/11 (primary, fully verified), Linux, or macOS |
| **Python** | **3.11, 3.12 or 3.13** (`requires-python = ">=3.11,<3.14"`). The project was verified on **3.11.9**. **3.14+ is NOT supported.** |
| **pip** | Bundled with Python (upgrade it: `python -m pip install -U pip`) |
| **venv** | Bundled with Python (on Debian/Ubuntu install `python3-venv`) |
| **Git** | Only needed to clone the repository |
| **Disk space** | ~2–3 GB free (virtualenv + ~100–200 MB embedding/reranker models + your data) |
| **RAM** | 4 GB minimum, 8 GB+ recommended |
| **Internet** | Needed once to install packages and download the embedding/reranker models, and afterwards for Gemini / web search features |
| **An LLM** | A `GEMINI_API_KEY` **or** a local/remote OpenAI-compatible server. Without one the app runs, but chat/Studio generation is disabled and the app tells you to configure `.env`. |
| **Browser** | Any modern browser to open the UI (Chrome/Edge/Firefox) |

### 2.2 Python dependencies (installed automatically)

From `pyproject.toml`:

```
nicegui>=3.0,<4          llama-index-core>=0.12,<0.15   lancedb>=0.20,<0.30
fastembed>=0.6,<0.9      google-genai>=1.0,<3           httpx>=0.28,<1
pypdf>=5,<7              pypdfium2>=4,<6                python-docx>=1.1,<2
python-pptx>=1,<2        openpyxl>=3.1,<4               beautifulsoup4>=4.12,<5
fpdf2>=2.8,<3            python-dotenv>=1,<2            defusedxml>=0.7,<1
ddgs>=9.16,<10
```

Optional extras:

| Extra | Packages | Purpose |
| --- | --- | --- |
| `ocr` | `rapidocr-onnxruntime>=1.4` | OCR for scanned PDFs / images (**recommended**) |
| `dev` | `pytest`, `ruff`, `psutil`, `playwright`, `matplotlib` | Tests, lint, browser checks, benchmark plots |
| `advanced` | `docling`, `sentence-transformers` | Reserved for future adapters — **not used** by the default pipeline; skip it |

### 2.3 Optional system software

| Software | Needed for | Notes |
| --- | --- | --- |
| **LibreOffice** (`soffice` on PATH, or `C:\Program Files\LibreOffice\program\soffice.exe`) | Legacy `.doc`, `.ppt`, `.xls` files only | Modern `.docx/.pptx/.xlsx` do **not** need it |
| **Unicode font** — *Segoe UI* (`C:\Windows\Fonts\segoeui.ttf`, present on Windows) or *DejaVu Sans* (`/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf`) | PDF export | Linux: `sudo apt install fonts-dejavu-core`. macOS: install DejaVu Sans to a path the app checks, or skip PDF export. |
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
cd <PROJECT>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
```

> If PowerShell blocks `run.ps1` later, run once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 4.3 Install dependencies — choose ONE option

**Option A — Recommended (flexible, latest compatible versions):**

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ocr]"
```

(Use `-e .` for runtime only, or `-e ".[ocr]"` for runtime + OCR without dev tools.)

**Option B — Exact reproducible snapshot (Windows only):**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-lock-windows.txt
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
```

`requirements-lock-windows.txt` is the exact verified Windows dependency
snapshot. **Use it on Windows only.**

### 4.4 Download the local retrieval models (one-time, ~100–200 MB)

```powershell
.\.venv\Scripts\python.exe scripts\download_models.py
```

Expected output ends with lines like `Embedding dimensions: 384` and
`Reranker check: 1`. Models are cached under `.data\models\`.
(If you skip this step the models are downloaded lazily on first use, which
makes the first import/question slow.)

### 4.5 Configure the LLM (`.env`)

```powershell
Copy-Item .env.example .env
notepad .env
```

Fill in your key:

```dotenv
GEMINI_API_KEY=your_key_here
GEMINI_FAST_MODEL=gemini-3.5-flash-lite
GEMINI_MAIN_MODEL=gemini-3.8-flash
```

Get a key at https://aistudio.google.com/app/apikey . See §7 for the local /
OpenAI-compatible alternative and for all environment variables.

### 4.6 Run

```powershell
.\run.ps1
```

`run.ps1` simply does `Set-Location $PSScriptRoot` and runs
`.venv\Scripts\python.exe -m local_notebook.main`. Then open
**http://127.0.0.1:8080**. Stop with `Ctrl+C`.

---

## 5. Install — Linux / macOS

### 5.1 System packages (Debian/Ubuntu example)

```bash
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip git fonts-dejavu-core
# optional, only for legacy .doc/.ppt/.xls:
sudo apt install -y libreoffice
```

macOS (Homebrew): `brew install python@3.11 git` (and optionally `brew install --cask libreoffice`).

### 5.2 Virtualenv + install

```bash
cd <PROJECT>
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev,ocr]"
```

> **Do not use `requirements-lock-windows.txt` on Linux/macOS** — it is a
> Windows-only snapshot. Use `pip install -e ".[dev,ocr]"` instead.

### 5.3 Models, config, run

```bash
.venv/bin/python scripts/download_models.py
cp .env.example .env        # then edit .env and set GEMINI_API_KEY
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
* Without a valid `GEMINI_API_KEY` (or a local provider) the UI loads but
  explains that a model connection is missing — that is expected, not a bug.

---

## 7. Configuration reference

### 7.1 `.env` (project root, git-ignored)

| Variable | Default | Meaning |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | Your Google Gemini key. Loaded from the **project** `.env` and it **overrides** any inherited OS variable (even if the `.env` value is blank). |
| `GEMINI_FAST_MODEL` | `gemini-3.5-flash-lite` | Fast model. Only the two allowed IDs are accepted. |
| `GEMINI_MAIN_MODEL` | `gemini-3.8-flash` | Main model. |
| `NOTEBOOK_API_KEY` | *(empty)* | Key for the **Local / compatible** provider if your endpoint needs auth. |

**Restart the app after every `.env` change** — there is no in-app key dialog.

### 7.2 Optional process environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `NOTEBOOK_PORT` | `8080` | HTTP port (host is always `127.0.0.1`) |
| `NOTEBOOK_DATA_DIR` | `<PROJECT>/.data` | Where the DB, vectors, uploads, logs live |
| `NOTEBOOK_MODEL_DIR` | `<DATA>/models` | Embedding/reranker model cache |
| `NOTEBOOK_EMBED_THREADS` | `min(4, cpu/2)` (1–8) | CPU threads used for embeddings |
| `NOTEBOOK_NO_SAMPLE` | unset | `1` = do not seed the sample notebook |
| `NOTEBOOK_OFFLINE` | unset | `1` = force "no model configured" (no cloud calls) |

Example (PowerShell): `$env:NOTEBOOK_PORT = "8090"; .\run.ps1`
Example (bash): `NOTEBOOK_PORT=8090 .venv/bin/python -m local_notebook.main`

### 7.3 Using a local / OpenAI-compatible model instead of Gemini

1. Start your server (e.g. Ollama at `http://localhost:11434/v1`) and pull a model.
2. In the app: **Settings → Provider → "Local / compatible"**, set the base URL
   and the model name.
3. If auth is required, add `NOTEBOOK_API_KEY=...` to `.env` and restart.
4. A **remote** endpoint must use **HTTPS**. The endpoint must support
   streaming and JSON output.

### 7.4 Limits worth knowing

* Max upload size: **150 MB** per file.
* Supported sources: PDF, DOCX, PPTX, XLSX, CSV, TSV, TXT, MD, HTML/HTM, JSON,
  PNG/JPG/JPEG/TIFF (OCR), legacy DOC/PPT/XLS (needs LibreOffice), plus public
  website/PDF URLs and pasted text.
* Studio data tools: source tables up to 50,000 rows / 500,000 cells.

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

An agent's terminal tool often kills child processes when the command ends
(symptom: the browser shows **`ERR_CONNECTION_REFUSED`** right after the
server "started"). Use a **detached** launch:

**Windows (PowerShell):**

```powershell
Start-Process -FilePath ".venv\Scripts\python.exe" `
  -ArgumentList "-m","local_notebook.main" `
  -WorkingDirectory "<PROJECT>" -WindowStyle Hidden `
  -RedirectStandardOutput "<PROJECT>\app.log" `
  -RedirectStandardError  "<PROJECT>\app.err.log"
```

**Windows (project helper — no console window, logs to `.data\logs\app.log`,
PID in `.data\app.pid`):**

```powershell
.\.venv\Scripts\python.exe scripts\launch_background.py
# needs psutil (in the [dev] extra) only when using --replace-pid <PID>
```

**Linux/macOS:**

```bash
nohup .venv/bin/python -m local_notebook.main > app.log 2> app.err.log &
```

`app.log` / `app.err.log` are git-ignored (`*.log`).

### 8.3 Restarting after code changes

The app runs with `reload=False`, so **Python changes need a restart.** Stop the
process that owns port 8080 (e.g. `Stop-Process -Id <PID> -Force`), then start it
again. Static CSS/JS edits are also picked up only after a restart/hard-refresh.

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

# Agent/data-tool tests only
.\.venv\Scripts\python.exe -m pytest tests\test_agent_tools.py -q
```

CI (`.github/workflows/`) runs: `ruff check`, `pytest -q`,
`benchmarks/publish.py --check`, `benchmarks/rag.py --keyword`, `pip check`,
`scripts/check_secrets.py` on Python 3.11.

Optional UI smoke tests (Windows + installed Microsoft Edge, uses Playwright,
deterministic fixtures, no live provider):

```powershell
.\.venv\Scripts\python.exe scripts\browser_check.py
.\.venv\Scripts\python.exe scripts\agent_ui_check.py
```

> `scripts\browser_check.py --live` calls the **real** provider and consumes quota.

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `ERR_CONNECTION_REFUSED` on 127.0.0.1:8080 | Server not running, or it was killed when the launching shell exited | Start it detached (§8.2); confirm with `netstat`/`curl /health` |
| `Create the virtual environment and install dependencies first` (from `run.ps1`) | `.venv\Scripts\python.exe` missing | Do §4.2–4.3 |
| `No matching distribution` / build errors on install | Python 3.14+ or 3.10- | Install Python 3.11–3.13 and recreate `.venv` |
| `Address already in use` / port 8080 busy | Another copy (or other app) is using it | Reuse the running one, stop it, or set `NOTEBOOK_PORT` |
| Chat/Studio says to configure a model | `GEMINI_API_KEY` empty or `.env` missing | Create `.env` from `.env.example`, add key, **restart** |
| Key set in OS env but app ignores it | Project `.env` intentionally overrides (even blank) | Put the key in `.env` |
| First question / first upload very slow | Models downloading lazily | Run `scripts/download_models.py` once |
| `PDF export needs a Unicode font` | No Segoe UI / DejaVu Sans | Linux: `apt install fonts-dejavu-core` |
| `Legacy Office files need LibreOffice` | `.doc/.ppt/.xls` uploaded | Install LibreOffice or re-save as DOCX/PPTX/XLSX |
| Scanned PDF / image gives no text | OCR extra not installed | `pip install -e ".[ocr]"` |
| `403 Only same-origin local access is allowed` | Opened via a LAN IP / different host | Use `http://127.0.0.1:8080` or `http://localhost:8080` |
| Gemini quota / 429 errors | Provider limits | Wait, use another key, or switch to a Local provider |
| PowerShell: `running scripts is disabled` | Execution policy | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Web search blocked / empty | Upstream search engine limits | Retry later; direct URL import still works |

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
│  ├─ providers.py                # Gemini + OpenAI-compatible adapters
│  ├─ chat.py · agent.py          # answers, agent/tool orchestration
│  ├─ studio.py · data_tools.py   # mind maps/quizzes/reports · analytics & spreadsheets
│  ├─ research.py · retrieval/    # web research · embeddings, vectors, rerank, workflow
│  ├─ ingestion/                  # parsers, OCR, legacy Office conversion, job queue
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
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ocr]"
.\.venv\Scripts\python.exe scripts\download_models.py
Copy-Item .env.example .env        # then put your GEMINI_API_KEY in .env
.\run.ps1                          # open http://127.0.0.1:8080
```

## 13. Copy-paste quick start (Linux / macOS)

```bash
git clone https://github.com/ryuu-la/NoteBookLm.git
cd NoteBookLm
python3.11 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e ".[dev,ocr]"
.venv/bin/python scripts/download_models.py
cp .env.example .env               # then put your GEMINI_API_KEY in .env
.venv/bin/python -m local_notebook.main   # open http://127.0.0.1:8080
```

---

### Agent checklist (tick before reporting "installed")

- [ ] Python 3.11–3.13 confirmed (`python --version`)
- [ ] `.venv` created inside `<PROJECT>` and dependencies installed with no errors
- [ ] `pip check` reports no broken requirements
- [ ] `scripts/download_models.py` printed the embedding + reranker lines
- [ ] `.env` exists (copied from `.env.example`), key filled in by the **user**, and **not** tracked by Git
- [ ] `curl http://127.0.0.1:8080/health` returns `"status":"ok"`
- [ ] `pytest -q` and `scripts/check_secrets.py` pass
- [ ] No files under `src/`, `tests/`, `pyproject.toml` were edited for the install
