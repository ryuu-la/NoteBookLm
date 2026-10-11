Folio · Local Notebook
======================

**Your sources. Your models. Your workspace.**

A local, open-source study application inspired by NotebookLM, authored in Python. Bring documents, ask questions with source citations, and turn the evidence into mind maps, quizzes, reports, and notes. No application account, sharing service, or subscription.

![Folio home](docs/images/home.png)

What works
----------

- Notebook creation, search, grid/list views, renaming, deletion, and restart persistence.
- A charcoal Sources → Chat → Studio workspace with collapsible sidebars, remembered layouts, mobile panel tabs, source search, and reduced-motion support.
- Simple Indexing/Ready status, cancellation, and animated generation feedback.
- Text-only PDF, DOCX, PPTX, XLSX, CSV, TSV, TXT, Markdown, HTML, and JSON ingestion. Images and OCR are currently disabled; PDFs must contain selectable text. Legacy Office files use an optional LibreOffice conversion adapter.
- Public website/PDF imports, pasted text, browser-based discovery, and optional integrated Wikipedia/Gemini search.
- Tokenizer-aware text chunking; local EmbeddingGemma 2 text embeddings (vision/audio disabled), LanceDB vectors, SQLite FTS5/BM25, and reciprocal rank fusion.
- Optimized full-precision CPU inference, cached model compilation, indexing batches grouped by actual token count, and reuse of existing embeddings for duplicate documents.
- Streaming Gemini chat, selected-source filtering, clickable evidence locations, stop generation, and saved conversations. Without a model connection, the app explains how to configure .env; it never substitutes excerpts for an answer.
- Structured, validated mind maps and quizzes; quiz scoring with explanations; source-grounded reports.
- Agent-callable Studio tools: Data Analytics, Spreadsheet, and Deep Research, with inline charts/tables, Excel/CSV downloads, and saved results.
- Autosaved Markdown notes, answer-to-note capture, and PDF/Markdown/JSON downloads with retained source references where available.
- `gemini-3.8-flash` and `gemini-3.5-flash-lite`, plus an OpenAI-compatible adapter for local or remote endpoints.
- Project `.env` configuration, local data ownership, bounded ingestion batches, duplicate detection, and restart checkpoints.
- Fast/Main chat switch, visible streaming status, reusable local embedding cache, and a retrieval benchmark dashboard with downloadable judgments.

![Folio workspace](docs/images/workspace.png)

Run on this computer
--------------------

The project environment and local models are already installed in `E:\NoteBookLM`.

```powershell
cd E:\NoteBookLM
.\run.ps1
```

Open **http://127.0.0.1:8080**. If it is already running, open that address directly instead of starting a second server. Stop a foreground server with Ctrl+C.

Use the sun/moon button in the header to switch between dark and white themes; the choice is saved locally. Notebook cards have a trash button with a confirmation before deletion.

**Agent** and **Auto** use selected sources for ordinary questions. Broad requests such as "create a proper learning guide here" sample the selected sources directly, without web searches, query-planning calls, or narrow keyword matching. Ask explicitly to search online for web evidence; genuine follow-ups to web answers can also reuse that route. **Sources** mode never searches the web. Explicit document-versus-web comparisons retrieve both and check their citations; other answers do not receive comparison instructions. Unselected documents remain excluded. **Web pages are read in memory, never imported or indexed by the agent.**

A compact progress line shows the current action. Expand it for factual steps such as reading sources or building a chart; it is not a private reasoning transcript. Completed answers retain a collapsed activity summary and elapsed time. Quick web research makes no LLM planning calls: one search (an alternative engine only if needed), then up to four page reads concurrently. Each search has an eight-second deadline and each page a ten-second deadline. Requested document retrieval runs alongside web I/O. Stop cancels the async run. Failed pages are excluded from evidence. Deep Research retains the longer search/refine loop for explicit research requests.

Agentic Studio
--------------

Every Studio tool dialog has a minimize button in its top-right corner. Minimized jobs continue while you use the notebook, with status entries in Studio to restore or cancel them. Completed jobs stay minimized until you open them; their outputs are saved normally. Keep the notebook page open while jobs run (these are page-session tasks, not durable jobs across reloads or server restarts).

Open the tools in **Studio**, or ask in chat: "Quick search Avatar cast and production details, chart its box-office revenue, and create a spreadsheet." Explicit tools are routed directly without an extra model planning call. Independent mind-map and data generation run concurrently; a weekly chart waits for the weekly map it summarizes. Charts and spreadsheets share one prepared dataset. Only Deep Research pays for a topic planner and parallel research branches. Compatible API connections are pooled, and streaming UI updates are batched to avoid re-rendering for every token.

- **Data Analytics:** tables, bar/line/pie charts, grouped sum/mean/count/min/max, and calculated summaries. CSV/TSV/XLSX calculations read the original selected tables rather than sampled retrieval passages. The first row is treated as headers; blank numeric cells are excluded from numerical aggregates. XLSX formulas use saved cached values. Other documents and websites use quoted, cited extracted rows, clearly marked as incomplete datasets.
- **Spreadsheet:** formatted Excel with Data, Summary, and Sources sheets, plus supporting quotes when extracted from evidence; CSV download is also available. Raw data strings cannot become spreadsheet formulas. The first version selects one table per request; it does not implement joins, arbitrary Python, pivot tables, or unrestricted transformations.
- **Deep Research:** explicitly requested multi-query search, website reading, linked-page exploration, and a detailed cited report. Each task is bounded to 10 searches, 24 page reads, 26 decisions, and seven minutes; the report uses the available context and discloses gaps. It requires web access and does not run in Sources-only mode.

Results appear below the chat answer and are saved in Studio. Chat charts and downloads persist after reload; deleting a Studio artifact does not remove its saved chat snapshot. Stop cancels in-flight async tasks. A failed research branch does not discard successful branches. Source tables are limited to 50,000 rows / 500,000 cells, and charts to 200 points; oversized inputs are rejected rather than silently producing partial totals. Downloads contain all result rows; the UI previews up to 500.

Run `python -m pytest tests/test_agent_tools.py -q` for tool checks and `python scripts/agent_ui_check.py` for the isolated Windows/Edge UI smoke test. The latter uses deterministic model/search fixtures and does not verify live provider or website availability.

Fresh installation
------------------

Python 3.11 is the tested runtime. The UI and business logic are Python; NiceGUI supplies its browser runtime. No separate JavaScript project or Node build is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev,ocr]'
.\.venv\Scripts\python.exe scripts\download_models.py
.\.venv\Scripts\python.exe -m local_notebook.main
```

On Linux/macOS, use `.venv/bin/python` instead. PDF export needs DejaVu Sans on Linux or the installed Segoe UI font on Windows. The exact verified Windows dependency snapshot is in `requirements-lock-windows.txt`; use that file only on Windows, then install this package with `pip install -e . --no-deps`.

First setup downloads the EmbeddingGemma 2 checkpoint and PyTorch runtime; allow several GB of disk space. Retrieval runs locally with the text and vision encoders, with audio disabled. Semantic imports index images and visual PDF pages directly, without requiring OCR. Optional OCR remains available for keyword-only scanned imports. LibreOffice is needed for old `.doc`, `.ppt`, and `.xls` files. The `advanced` extra reserves Docling for future adapters.

Connect a model
---------------

1. Open the project [`.env`](.env). On a fresh checkout, copy `.env.example` to `.env` first.
2. Fill in `GEMINI_API_KEY` with your own key:

   ```dotenv
   GEMINI_API_KEY=your_key_here
   GEMINI_FAST_MODEL=gemini-3.5-flash-lite
   GEMINI_MAIN_MODEL=gemini-3.8-flash
   ```

3. Restart the server, then open **Settings → Test connection**.

The project `.env` is loaded at startup, regardless of the working directory. Values in the project file take precedence over inherited process variables, including a blank key. This prevents a previous environment key from silently taking over your new setup. Only the two Gemini model IDs above are allowed. Gemini settings in the database cannot override them. A transient failure can retry the selected model once before any text arrives; it never switches models automatically. There is no key-entry dialog or credential-store fallback. `.env` is ignored by Git; `.env.example` contains no secret.

Gemini chat defaults to **Fast** (your Flash-Lite model); switch to **Main** in the composer when you want Flash. Studio also defaults to the fast model. Settings exposes Gemini thinking effort. Retrieval uses one EmbeddingGemma 2 model with keyword fusion; there is no separate reranker. Higher generation effort takes longer. Model service load can still delay the first token.

For a local OpenAI-compatible server, select **Local / compatible**, set its base URL (for example `http://localhost:11434/v1`), and enter a model installed on that server. If authentication is required, set `NOTEBOOK_API_KEY` in `.env` and restart. A remote endpoint must use HTTPS. Compatibility depends on the endpoint's streaming and JSON-output support; the adapter has been checked against a local SSE contract fixture, not every model vendor.

The application is free. Cloud API usage, search quotas, and provider account requirements are controlled by the provider. Cloud generation sends your question and retrieved evidence to that provider. Local storage does not make a cloud model offline.

Try a three-minute demo
-----------------------

1. Open the included **The science of learning** notebook. Its sample texts are original demonstration notes, clearly labeled as such.
2. Ask “How do retrieval practice and spaced practice work together?”
3. Open a citation, then deselect a source and ask a follow-up.
4. Generate a mind map, a two-question quiz, and a short report from Studio.
5. Save an answer as a note, edit it, export a PDF, and reload to demonstrate persistence.

Verification
------------

The chat RAG workflow now has a separate [conversation and answer evaluation suite](docs/RAG_EVALUATION.md), including follow-ups, topic switches, full-index lookup, source isolation, unanswerable questions, and live citation/claim checks. Open `/benchmarks` for per-case results. Missing model access no longer substitutes pasted source excerpts for an answer.

The September UI/indexing refresh reduced the isolated 1,000-page ingestion fixture from **14.57 s to 8.68 s**. These historical fixture timings do **not** measure a full EmbeddingGemma 2 import. Dense books require substantially more CPU work to embed their text. See the [UI changes, benchmark comparison, and validation scope](docs/UI_REFRESH.md).

- **163 automated tests** passed locally, covering parsing/OCR, isolation, citations, migration, image provenance, recovery, embedding reuse, source overviews, PDF export, streaming, and local origin checks.
- An isolated headless Edge run passed **17 browser checks with a real Gemini connection**. Fast chat became visible in **2.40 s**; a small mind map took **3.48 s**, a two-question quiz **2.42 s**, and a short report **2.92 s**. These are single-run observations, not service guarantees.
- Four deterministic browser checks verified a visible waiting state, partial streaming before completion, stopping chat, and cancelling Studio without saving an artifact.
- A **10,000-page synthetic digital PDF** exercises ingestion and cached reindexing, followed by five exact-record probes with the reranker off. See the [generated measurement table and raw results](docs/VERIFICATION.md#10000-page-benchmark) for historical timings, memory, and probe outcomes; those pre-migration measurements do not describe Gemma performance.
- Live Flash and Flash-Lite connections and a public URL import were verified.

These are scoped measurements, not broad accuracy or production-readiness claims. The synthetic benchmark uses short, simple pages and excludes OCR and complex layouts. See [verification details](docs/VERIFICATION.md).

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts benchmarks
.\.venv\Scripts\python.exe scripts\browser_check.py
.\.venv\Scripts\python.exe scripts\streaming_check.py
.\.venv\Scripts\python.exe scripts\ux_check.py
.\.venv\Scripts\python.exe benchmarks\scale.py --pages 10000 --semantic
.\.venv\Scripts\python.exe benchmarks\retrieval.py
.\.venv\Scripts\python.exe benchmarks\rag.py
.\.venv\Scripts\python.exe benchmarks\plot.py
```

`scripts/browser_check.py --live` runs generation against a configured real provider and consumes its quota. Browser checks use an isolated library and Edge profile. The browser test script currently targets an installed Microsoft Edge browser.

System design
-------------

See the [architecture diagrams and runtime flows](docs/ARCHITECTURE.md) and [updated implementation plan](PROJECT_PLAN.md). They distinguish the current implementation from planned improvements.

Retrieval quality and speed
---------------------------

Open **Retrieval benchmarks** in the top bar, or visit `/benchmarks`. Compare keyword search with EmbeddingGemma 2 hybrid retrieval on **54 labeled questions over 40 authored passages**. Reports identify the model used; older reports are historical measurements. The [measured results table](docs/RETRIEVAL_BENCHMARK.md) and chart are generated from the same saved JSON. Current runs use three repetitions with randomized configuration and question order; this remains a small development fixture.

![Retrieval benchmark](docs/images/retrieval-benchmark.png)

The separate live answer report currently **fails its evaluation gates** and needs judge review. It is not a validated answer-accuracy score.

This small developer-authored fixture measures finding labeled evidence, **not perfect generated-answer accuracy**. It is not an independent held-out evaluation. The committed [query-level results](src/local_notebook/assets/retrieval-benchmark.json) expose every ranking and timing. See [methodology and limits](docs/RETRIEVAL_BENCHMARK.md).

Data and configuration
----------------------

EmbeddingGemma 2 is the only retrieval model (`google/embeddinggemma-2`, pinned revision, 768 dimensions). Text is split using its tokenizer into 512-token passages with 64-token overlap. On restart, existing ready sources using an older index are queued for rebuilding from their originals; chats and stored citation snapshots are preserved. Images selected as evidence are sent to your configured answer provider, which must support image input. Up to four retrieved images are attached per answer.

Runtime data lives under `.data/`, which is excluded from Git. It contains SQLite metadata, originals, search indexes, model caches, and logs. `NOTEBOOK_DATA_DIR`, `NOTEBOOK_MODEL_DIR`, and `NOTEBOOK_PORT` override the defaults. `NOTEBOOK_EMBED_THREADS` controls local embedding CPU threads (1–8; defaults to at most 4). `NOTEBOOK_NO_SAMPLE=1` disables first-run samples. `NOTEBOOK_OFFLINE=1` disables model generation for testing; chat asks for a model connection rather than returning raw excerpts.

To back up, stop the app and copy the whole data directory. Restore it while the app is stopped. Credential-store keys are outside that directory. The server binds only to loopback and checks HTTP and WebSocket host/origin boundaries. This is a single-user local app, not a shared hosted service.

Known boundaries
----------------

- Integrated Wikipedia search was blocked by the upstream endpoint in this environment. Gemini search returned a provider quota error. Browser search and direct public URL import remain available; neither bypasses paywalls or private documents.
- Broad Studio overviews sample sections within a bounded context. They explicitly warn when not every passage is covered. Full-corpus hierarchical summarization is future work.
- EmbeddingGemma 2 runs in float32 on CPU or bfloat16 on supported GPUs. Multilingual and visual retrieval quality must be measured on your own material; an embedding similarity score is not proof that a passage answers a question.
- Parsing is best effort. Complex formulas, merged cells, chart semantics, handwritten scans, unsupported encodings, and proprietary formats may need a different source export. Spreadsheet extraction preserves row/sheet context; it is not a spreadsheet calculation engine.
- No audio/video overview generator, login-based Google Drive import, collaboration, or deployment service is included.
- Citation IDs and locations are validated, but this does not prove every generated claim is entailed. Verify important answers against original evidence.

Read the [architecture](docs/ARCHITECTURE.md), [demo and résumé guide](docs/RESUME_GUIDE.md), and [contribution notes](CONTRIBUTING.md). Licensed under [MIT](LICENSE). Independent project; not affiliated with Google or NotebookLM.

RunInfra provider
----------------

Set `RUNINFRA_API_KEY` in the project `.env`, restart Folio, and select **Settings → Model provider → RunInfra**. Choose GLM 5.3 Flash (`glm-5-3-flash`), Qwen 3.8 27B (`Qwen/Qwen3.8-27B`), or DeepSeek V4.1 Flash (`deepseek-ai/DeepSeek-V4.1-Flash`) in Settings or directly in the chat composer. RunInfra uses one selected model for chat, planning, and Studio, without Fast/Main modes. Model switches are saved immediately from the composer and need no restart. Each request to `https://api.runinfra.ai/v1` carries a unique `X-Client-Request-Id`. Streaming and JSON tool output reuse the existing compatible client, so no extra SDK is needed. Keys stay in the environment, not the settings database. Use **Test connection** after adding your key.

The light and dark themes include coordinated Studio gradients, accent borders, composer focus feedback, and short entrance/hover animations. System reduced-motion preferences disable animations and transitions.

Harness checks: `python benchmarks/harness.py` measures local source retrieval and simulated web I/O without provider calls. Results are written to `test-results/harness-latency.json`; they exclude real network and model latency. `python scripts/harness_ui_check.py` checks the learning-guide regression, compact progress, streaming, and persistence with deterministic fixtures.
