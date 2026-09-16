Local Notebook — Project Plan
=============================

Status: initial design, retained for context. The working v0.1 implementation is documented in README.md and docs/ARCHITECTURE.md; measured verification is in docs/VERIFICATION.md. Planned items below are not all claims of shipped functionality.
Working name: Local Notebook. Target: a free, open-source, single-user NotebookLM-style study application.

Product commitments
-------------------

- Python application logic, backend, ingestion, AI workflows, and UI definitions.
- NiceGUI renders the browser interface; its bundled browser dependencies and small dedicated CSS files provide styling. No separately maintained React/Next.js application or Node build pipeline.
- Closely reproduce the supplied screenshots' layout, spacing, dark palette, rounded panels, source selection, chat flow, and studio interactions, using our own name and assets.
- No application account, signup, subscriptions, sharing, public discovery feed, or collaboration system.
- Notebooks, originals, extracted text, indexes, conversations, and generated study materials stay in a local data directory.
- Bring your own API key. The application is free; provider fees, quotas, and provider account requirements still apply.
- Cloud generation sends the question and selected evidence to the configured provider. Fully offline generation requires a local model endpoint; local storage alone does not make a cloud API private or offline.
- MIT license for our code; retain dependency and model license notices.

Interface and user journeys
---------------------------

1. Home: notebook card grid/list, search, sorting, recent notebooks, create, rename, and delete. Locally pinned notebooks can occupy the featured-card area.
2. Notebook: compact header with editable title, home navigation, create notebook, and settings.
3. Sources panel: upload/drop files, paste text, add URLs, search the web, select sources, inspect extraction, retry failed imports, and remove sources.
4. Chat panel: notebook overview, suggested questions, streaming answers, stop generation, follow-up questions, inline citations, and save answer as a note.
5. Studio panel: Mind Map, Quiz, Reports, and Notes cards, plus a saved-artifact list and progress states.
6. Settings: provider, endpoint, API key, separate main/fast models, local embedding profile, language, storage, and generation budgets.
7. Source viewer: open the cited PDF page, slide, sheet/range, text section, or captured web passage with its provenance.

Desktop uses three resizable/collapsible panels with an approximate 25% / 48% / 27% starting split. Smaller screens switch between panels. Use the screenshots' charcoal backgrounds, subtle borders, pill buttons, muted blue accents, and pastel studio cards. Include keyboard navigation, visible focus, accessible labels, reduced motion, empty states, and actionable error states. Keep text entry and navigation responsive during ingestion.

Feature scope for the first complete release
------------------------------------------

| Feature | Intended behavior |
| --- | --- |
| Grounded chat | Answers from selected notebook sources with clickable evidence; explicitly state when evidence is insufficient. |
| Mind map | Expand/collapse a topic hierarchy, pan/zoom, open evidence from nodes, and export structured JSON plus a visual export. |
| Quiz | Choose topic, question count, and difficulty; answer questions, receive scores, explanations, and citations; retry locally. |
| Reports | Study guide, briefing, topic comparison, FAQ, or a custom prompt; editable output with citations. |
| Notes | Create/edit/autosave notes, save chat answers, organize per notebook, and export Markdown or PDF. |
| PDF export | Unicode-capable notes/reports with headings, lists, tables, page numbers, and source references; visually verify exported samples. |
| Internet sources | Import public URLs; discover candidate pages with a configured search provider, preview results, and select pages to ingest. |
| Local persistence | Restart without losing imports, chats, notes, artifacts, or indexing progress. |

Audio/video overview generation, slide generation, public sharing, and accounts are outside this release. Audio/video source transcription is an optional ingestion extension after the required document formats work.

Source support
--------------

| Source | Extraction plan |
| --- | --- |
| PDF | Fast text extraction for straightforward files; Docling layout/table extraction where needed; OCR for scanned pages. |
| DOCX | Paragraphs, headings, lists, and tables; retain section and paragraph locations. |
| PPTX | Slide text, tables, speaker notes where available, and optional image understanding; cite slide numbers. |
| XLSX / CSV / TSV | Sheet-aware and row-batched extraction with repeated headers, cell/range provenance, and bounded previews. |
| TXT / Markdown / HTML / JSON | Encoding-aware parsing, logical sections, and deterministic locators. |
| PNG / JPEG / TIFF | Local OCR; optional cloud image interpretation explicitly enabled by the user. |
| DOC / PPT / XLS | Conversion adapters using locally installed LibreOffice where required; explain missing converter dependencies. |
| Web pages and web PDFs | Download, extract readable content, retain title/URL/retrieval time, and store an evidence snapshot. |
| Google Docs / Slides / Sheets | Public readable/export links when accessible; otherwise import an exported file without introducing Google login. |

Use an extensible parser registry. Unsupported, encrypted, corrupt, or inaccessible inputs must report a useful error instead of pretending extraction succeeded. Arbitrary file support is not a promise that every binary format, diagram, formula, or scanned page can be read perfectly. Preserve tables structurally; use constrained dataframe operations for numerical questions rather than asking the language model to invent calculations.

Selected Python stack
---------------------

| Layer | Choice | Purpose |
| --- | --- | --- |
| UI and web server | NiceGUI / FastAPI | Python-authored interactive interface and local endpoints. |
| Schemas and persistence | Pydantic, SQLAlchemy, SQLite, Alembic | Validated objects, notebook metadata, jobs, and migrations. |
| RAG orchestration | LlamaIndex | Ingestion transformations, retrieval composition, and source-aware synthesis. |
| Document understanding | Docling plus focused format adapters | Layout, tables, OCR, and metadata-preserving extraction. |
| Local search storage | Embedded LanceDB | Persistent vector and full-text indexes without a cloud database account. |
| Embeddings | BAAI/bge-m3 via a Python model adapter | Local multilingual dense embeddings; benchmark on the target machine. |
| Reranking | BAAI/bge-reranker-v2-m3 | Local second-stage relevance scoring of retrieved candidates. |
| Gemini integration | google-genai | Native Gemini streaming and structured generation. |
| Other model providers | Provider protocol with OpenAI-compatible HTTP adapter | Custom endpoint/model/key and a path to Ollama or other local servers. |
| Background processing | Separate Python worker processes and SQLite-backed durable jobs | Bounded parsing/OCR/embedding work, retries, cancellation, and restart recovery. |
| Export | Python PDF renderer with bundled licensed Unicode fonts | Consistent local PDF output. |
| Quality tooling | uv, Ruff, pytest, Python Playwright | Reproducible dependencies, linting, functional checks, and browser verification. |

The two BGE models are the quality profile, not a claim of instant performance on every laptop. Provide a lighter CPU profile after comparing quality and memory use. Download models once and cache them locally; report download sizes before optional installation. Indexes record embedding model, revision, dimensions, and chunking version; changing these requires a controlled rebuild.

API configuration
-----------------

- Main model: `gemini-3.5-flash` for grounded answers, synthesis, reports, quizzes, and mind maps.
- Fast model: `gemini-3.5-flash-lite` for optional query rewriting, titles, and small summaries.
- Both identifiers are documented by Google as of the planning check on 2026-09-16; validate actual access with the supplied key.
- Keep identifiers editable; surface unavailable-model errors and never silently switch to a more expensive model.
- Providers implement capability flags for streaming, structured outputs, images, and token accounting. An arbitrary API needs a compatible protocol or a dedicated adapter; a key alone cannot make all APIs interchangeable.
- Keep keys in memory by default; optional persistence uses the operating-system credential store. Never store keys in notebook exports, client storage, or logs.
- Handle timeouts, rate limits, backoff, stop requests, partial generations, usage counts, and configurable output/context budgets.

RAG architecture for 10,000-page notebooks
----------------------------------------

Capacity target: at least 10,000 pages across a notebook's sources, with a separate stress case for one very large PDF. This is a release benchmark to demonstrate, not an already achieved guarantee. Page density, tables, OCR, language, hardware, and model choice affect throughput and memory.

Ingestion path:

1. Stream originals to local storage, validate format/size, hash content, and create a durable job.
2. Parse in bounded page/row batches. Limit concurrent OCR and embedding jobs; never hold all document images or embeddings in RAM.
3. Preserve notebook/source/version IDs, physical PDF page, printed page label when available, slide, sheet/range, heading, and text offsets.
4. Split along sections/paragraphs, initially around 500–900 tokens with modest overlap; preserve parent sections and table headers. Tune using retrieval evaluation.
5. Embed in batches; write persistent dense and lexical indexes. Maintain source filters and exclude incomplete source versions from retrieval.
6. Cache extraction and embeddings by content hash plus pipeline version. Reimport changed content incrementally; maintain stable citation targets.
7. Checkpoint progress so interrupted jobs resume. Publish an indexed source version only when its metadata and indexes are consistent.
8. Create optional section/document summaries as background work, with visible model usage and original-evidence links.

Question-answering path:

1. Resolve follow-ups using bounded conversation history; apply notebook and selected-source filters to every retrieval branch.
2. Retrieve semantic candidates and lexical matches; combine rankings with reciprocal rank fusion.
3. Rerank a bounded candidate pool, initially 40–80 passages; tune quality versus latency on measured hardware.
4. Expand useful adjacent/parent context, deduplicate overlap, retain source diversity, and fit evidence into a token budget.
5. Generate with explicit source IDs and evidence-only instructions. Validate citation IDs and render exact locations; do not claim citation validity proves every statement is true.
6. For broad requests such as “summarize all sources,” use hierarchical section/document synthesis with coverage tracking rather than treating a few nearest passages as the whole library.
7. For comparison or multi-part questions, retrieve evidence for each sub-question and surface contradictions or missing evidence.

Reports, quizzes, and mind maps share the evidence pipeline. Validate generated structures against Pydantic schemas; retain supporting passage IDs on questions, nodes, and report sections. Treat imported text as untrusted evidence rather than instructions to run tools or expose keys.

Scale and quality gates
-----------------------

- Benchmark 100, 1,000, and 10,000 pages with digital text, scans, tables, multilingual material, and duplicate imports.
- Record corpus tokens/chunks, disk use, peak memory, extraction/embedding throughput, retrieval p50/p95, reranking latency, and answer latency separately.
- Initial reference profile: Windows, SSD, 16 GB RAM, CPU-only; measure an optional GPU profile separately. Adjust batch sizes rather than assume a GPU.
- Provisional retrieval goal: p95 under 3 seconds before generation on the documented reference corpus/hardware; report reranking separately and revise transparently if measured results require it.
- Curate at least 100 answerable and unanswerable questions with evidence labels; target evidence Recall@20 >= 90% and manually verified citation support >= 95%. These are acceptance targets, not measured results.
- Test notebook/source isolation, filtered retrieval, cross-document comparisons, unsupported questions, multilingual queries, and citation navigation.
- Test cancellation, restart recovery, concurrent reads during ingestion, repeated uploads, source replacement, and index cleanup after deletion.
- Track generation cost and time for whole-library synthesis; avoid automatically sending thousands of pages to an API on import.

Local operation and reliability
-------------------------------

- Bind to loopback by default, validate host/origin on browser mutations, and keep assets/fonts local. No telemetry or app analytics.
- Separate application code from configurable runtime data: originals, extracted blocks, SQLite, indexes, artifacts, and caches.
- Use safe filenames and bounded parsers; disable document macros and never execute imported code.
- URL imports permit supported public HTTP(S) resources; restrict private-network targets and recheck redirects, timeouts, and download limits.
- Keep remote provider calls limited to configured endpoints and selected content. An explicit local-provider mode should run offline after required model downloads.
- Sanitize rendered document/model HTML and Markdown. Keep local filesystem paths and secrets out of UI error details.
- Deletion removes original content, derived chunks, vectors, and summaries; warn when existing notes/artifacts still quote the deleted source and allow their removal.
- Provide local backup/restore with schema versions and index rebuild instructions; exclude secrets by default.

Code organization and conventions
---------------------------------

```text
src/local_notebook/
  main.py
  config/
  ui/pages/
  ui/components/
  ui/styles/
  domain/
  storage/repositories/
  storage/migrations/
  ingestion/parsers/
  ingestion/workers/
  retrieval/
  providers/
  chat/
  studio/
  exports/
tests/
  unit/
  integration/
  browser/
  retrieval_eval/
benchmarks/
docs/
```

Aim for 100–250 lines per implementation module; refactor around 350 lines when responsibilities grow. No thousand-line application files. Separate UI components, business services, parsers, prompts, provider adapters, and persistence. Prefer type hints and descriptive names; use comments only for non-obvious reasoning or constraints. Pin tested dependencies in a lockfile. Keep real user data and credentials out of version control.

Implementation milestones
-------------------------

| Phase | Deliverable | Exit check |
| --- | --- | --- |
| 1. Foundation and UI | Python package, local launch, SQLite notebooks, settings, screenshot-matched home and three-panel workspace. | Create/rename/reopen notebooks; responsive layout and keyboard smoke test. |
| 2. Sources | Required file adapters, URL imports, extraction preview, durable jobs, and provenance. | Representative files parse correctly; errors, cancellation, and restart recovery work. |
| 3. RAG and chat | Persistent embeddings/full-text indexes, source filtering, reranker, Gemini providers, streaming, and citations. | Answer real questions with correct source locations; isolation and insufficient-evidence checks pass. |
| 4. Study studio | Mind maps, quizzes, reports, notes, and PDF/Markdown export. | Every tool generates, saves, reopens, and exports real source-grounded output. |
| 5. Provider flexibility and internet discovery | OpenAI-compatible/local endpoints, provider capability handling, configurable search, and selected-result ingestion. | Switch providers without rebuilding unchanged local embeddings; search failures have useful recovery. |
| 6. Scale and release | 10,000-page benchmark, quality evaluation, security checks, install/run docs, MIT license, and polished UI. | Publish measured results and known limits; clean install succeeds on Windows. |

Each phase delivers working behavior before the next layer is added. Release completion requires the full requested feature set and scale evidence, not only a visual mockup.

Technical references checked for this plan
------------------------------------------

- [NiceGUI: Python UI framework](https://github.com/zauberzeug/nicegui)
- [LlamaIndex ingestion pipeline](https://developers.llamaindex.ai/python/framework/module_guides/loading/ingestion_pipeline/)
- [Docling parsing and local execution](https://docling-project.github.io/docling/)
- [LanceDB hybrid search](https://docs.lancedb.com/search/hybrid-search)
- [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3)
- [BGE reranker model card](https://huggingface.co/BAAI/bge-reranker-v2-m3)
- [Gemini 3.5 Flash model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash)
- [Gemini 3.5 Flash-Lite model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite)
