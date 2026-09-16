Folio · Local Notebook
======================

**Your sources. Your models. Your workspace.**

A local, open-source study application inspired by NotebookLM, authored in Python. Bring documents, ask questions with source citations, and turn the evidence into mind maps, quizzes, reports, and notes. No application account, sharing service, or subscription.

![Folio home](docs/images/home.png)

What works
----------

- Notebook creation, search, grid/list views, renaming, deletion, and restart persistence.
- A dark Sources → Chat → Studio workspace with responsive layouts.
- PDF, DOCX, PPTX, XLSX, CSV, TSV, TXT, Markdown, HTML, JSON, and image ingestion. OCR is available for scans; legacy Office files use an optional LibreOffice conversion adapter.
- Public website/PDF imports, pasted text, browser-based discovery, and optional integrated Wikipedia/Gemini search.
- LlamaIndex sentence chunking and a typed retrieval workflow; local BGE embeddings, LanceDB vectors, SQLite FTS5/BM25, reciprocal rank fusion, and a MiniLM cross-encoder reranker.
- Streaming Gemini chat, selected-source filtering, clickable evidence locations, stop generation, and saved conversations. Without a model connection, matching source excerpts are explicitly labeled.
- Structured, validated mind maps and quizzes; quiz scoring with explanations; source-grounded reports.
- Autosaved Markdown notes, answer-to-note capture, and PDF/Markdown/JSON downloads with retained source references where available.
- Gemini 3.5 Flash and Flash-Lite, plus an OpenAI-compatible adapter for local or remote endpoints.
- OS credential-store support, local data ownership, bounded ingestion batches, duplicate detection, and restart checkpoints.
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

First model setup downloads approximately 100–200 MB of embedding/reranker assets, depending on packaging and cache behavior. Subsequent retrieval runs locally. OCR has an optional package installation; LibreOffice is needed only for old `.doc`, `.ppt`, and `.xls` files. An `advanced` extra reserves Docling/sentence-transformers for future adapters; those packages are not used by the current default pipeline.

Connect a model
---------------

1. Open **Settings**.
2. Choose **Gemini**, enter your API key, and keep `gemini-3.5-flash` / `gemini-3.5-flash-lite` or enter other accessible model IDs.
3. Choose whether to remember the key in the operating-system credential store. Otherwise the key remains in this server process until exit.
4. Test the connection and save. The app also recognizes `GEMINI_API_KEY`.

Gemini chat defaults to **Fast** (your Flash-Lite model); switch to **Main** in the composer when you want Flash. Studio also defaults to the fast model. Settings exposes Gemini thinking effort and a 16- or 40-candidate reranking shortlist. Higher effort and broader reranking take longer. Model service load can still delay the first token.

For a local OpenAI-compatible server, select **Local / compatible**, set its base URL (for example `http://localhost:11434/v1`), and enter a model installed on that server. A remote endpoint must use HTTPS. Compatibility depends on the endpoint's streaming and JSON-output support; the adapter has been checked against a local SSE contract fixture, not every model vendor.

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

- **40 automated tests** passed locally, covering parsing/OCR, isolation, citations, recovery, embedding reuse, candidate budgets, source overviews, PDF export, SSE parsing, and local origin checks.
- An isolated headless Edge run passed **17 browser checks with a real Gemini connection**. Fast chat became visible in **2.40 s**; a small mind map took **3.48 s**, a two-question quiz **2.42 s**, and a short report **2.92 s**. These are single-run observations, not service guarantees.
- Four deterministic browser checks verified a visible waiting state, partial streaming before completion, stopping chat, and cancelling Studio without saving an artifact.
- A **10,000-page synthetic digital PDF** produced 10,000 indexed passages in **126.67 seconds**, with **557.4 MB** peak process RSS across ingestion and reindexing. Cached reindexing took **22.16 s**. Five exact-record retrieval probes measured **27–41 ms** with the reranker off.
- Live Flash and Flash-Lite connections and a public URL import were verified.

These are scoped measurements, not broad accuracy or production-readiness claims. The synthetic benchmark uses short, simple pages and excludes OCR and complex layouts. See [verification details](docs/VERIFICATION.md).

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests scripts benchmarks
.\.venv\Scripts\python.exe scripts\browser_check.py
.\.venv\Scripts\python.exe scripts\streaming_check.py
.\.venv\Scripts\python.exe benchmarks\scale.py --pages 10000 --semantic
.\.venv\Scripts\python.exe benchmarks\retrieval.py
.\.venv\Scripts\python.exe benchmarks\plot.py
```

`scripts/browser_check.py --live` runs generation against a configured real provider and consumes its quota. Browser checks use an isolated library and Edge profile. The browser test script currently targets an installed Microsoft Edge browser.

Retrieval quality and speed
---------------------------

Open **Retrieval benchmarks** in the top bar, or visit `/benchmarks`. The chart compares keyword, hybrid, and two reranking budgets on **54 labeled questions over 40 original study passages**. The fast reranker measured **100% Recall@8**, **1.000 MRR@8**, and **0.9977 nDCG@8**, at **208 ms median / 227 ms p95**. Reranking 40 candidates achieved the same scores at **473 ms median**.

![Retrieval benchmark](docs/images/retrieval-benchmark.png)

This small developer-authored fixture measures finding labeled evidence, **not perfect generated-answer accuracy**. It is not an independent held-out evaluation. The committed [query-level results](src/local_notebook/assets/retrieval-benchmark.json) expose every ranking and timing. See [methodology and limits](docs/RETRIEVAL_BENCHMARK.md).

Data and configuration
----------------------

Runtime data lives under `.data/`, which is excluded from Git. It contains SQLite metadata, originals, search indexes, model caches, and logs. `NOTEBOOK_DATA_DIR`, `NOTEBOOK_MODEL_DIR`, and `NOTEBOOK_PORT` override the defaults. `NOTEBOOK_NO_SAMPLE=1` disables first-run samples. `NOTEBOOK_OFFLINE=1` forces extractive chat for testing; it does not turn a cloud generation endpoint into a local model.

To back up, stop the app and copy the whole data directory. Restore it while the app is stopped. Credential-store keys are outside that directory. The server binds only to loopback and checks HTTP and WebSocket host/origin boundaries. This is a single-user local app, not a shared hosted service.

Known boundaries
----------------

- Integrated Wikipedia search was blocked by the upstream endpoint in this environment. Gemini search returned a provider quota error. Browser search and direct public URL import remain available; neither bypasses paywalls or private documents.
- Broad Studio overviews sample sections within a bounded context. They explicitly warn when not every passage is covered. Full-corpus hierarchical summarization is future work.
- The default compact embedding/reranking models prioritize CPU use and English. Multilingual retrieval quality has not been benchmarked.
- Parsing is best effort. Complex formulas, merged cells, chart semantics, handwritten scans, unsupported encodings, and proprietary formats may need a different source export. Spreadsheet extraction preserves row/sheet context; it is not a spreadsheet calculation engine.
- No audio/video overview generator, login-based Google Drive import, collaboration, or deployment service is included.
- Citation IDs and locations are validated, but this does not prove every generated claim is entailed. Verify important answers against original evidence.

Read the [architecture](docs/ARCHITECTURE.md), [demo and résumé guide](docs/RESUME_GUIDE.md), and [contribution notes](CONTRIBUTING.md). Licensed under [MIT](LICENSE). Independent project; not affiliated with Google or NotebookLM.
