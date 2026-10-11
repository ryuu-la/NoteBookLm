Verification record
===================

Current checks and behavior · 2026-10-11
--------------------------------------

The active app uses text-only EmbeddingGemma 2, index version 4, a cached
OpenVINO FP32 graph on eligible x86 CPUs and PyTorch on the other supported
execution paths. Vision/audio, image uploads, OCR and LLM image attachments are
disabled. Records below are historical milestones; their model configuration,
test counts and performance apply to the recorded run, not automatically to the
current application. In particular, old multimodal and BGE/MiniLM results are
not current enabled features or current Gemma speed measurements.

- **204 automated tests** passed, with two upstream test-client deprecation
  warnings. Ruff, dependency consistency, the keyword RAG gate, benchmark
  table/chart consistency and staged-secret checks also passed before publication.
- **19 deterministic map/Studio browser checks** passed without JavaScript
  errors. Coverage includes a collapsed map moving freely, independent topic
  dragging, live connector endpoints, pointer-anchored wheel zoom, keyboard
  movement, resize preservation, touch panning/pinch, exports and generation
  recovery. Run `python scripts/mindmap_check.py` to reproduce.
- The website browser check confirmed a simulated HTTP 403 becomes a website
  error, retry remains enabled, Paste article text selects the text panel and
  pasted text indexes successfully. This fixture does not establish live website
  availability. A separate live Wikipedia request returned 403 from this connection.
- Actual token counts now order batches of eight. On the same 64-section local
  sample, two character-ordered runs averaged **29.79 s** and two token-ordered
  runs averaged **25.90 s**: **13.1% less embedding time**, or 1.15x throughput.
  Run order was reversed for the second pair. Minimum output cosine agreement
  was **0.99999976**; maximum absolute vector difference was **1.79e-7**.
  These are sample embedding timings and numerical-agreement checks, not a
  full-document speedup or retrieval-accuracy evaluation. The full source's
  calculated padded input count fell from 430,624 to 363,712 tokens.
  `python scripts/indexing_batch_check.py` writes the local, ignored report to
  `test-results/indexing-token-batching.json`; it waits for active imports first.

The documentation was audited against current code on October 11. That review
does not certify fresh installation on every platform or rerun historical live
provider benchmarks. See [the setup guide](../README_OF_AGENTS.md) for current
dependencies, configuration and reproducible commands.

Faster CPU indexing · 2026-10-10
-------------------------------

On x86 CPUs, text-only Gemma now uses an OpenVINO FP32 graph with the same
checkpoint, prompts, tokenizer, mean pooling and normalization. The graph is
compiled once and cached locally. CUDA retains the PyTorch path. The override
`NOTEBOOK_EMBED_BACKEND=pytorch` is available for comparison/debugging.

Indexing groups similar text lengths and stores completion per text record,
so restarting cannot skip records after the order changes. Existing sequential
checkpoints are migrated. Fully cached imports do not initialize either model
runtime. Source locations, embedding keys, and vector dimensions are unchanged.

A local sample of 64 text sections from an uploaded PDF took 38.59 seconds in
the previous runtime/order and 25.13 seconds with the new runtime/order: 1.54x
throughput, or 35% less embedding time. No embedding-result cache was used in
either measurement. Minimum output cosine agreement was 0.99999988 and maximum
absolute vector difference was 2.98e-7. This measures the sample's embedding
stage, not whole-library or first-install timing. First graph conversion and
loading took 23.23 seconds and is already cached on this machine.

Integrated Intel graphics was tested but did not provide enough additional
benefit to replace the full-precision CPU path. Quantization was not enabled.
The local timing report is `test-results/indexing-speed.json`.
179 automated tests, Ruff and dependency checks passed. An isolated browser
deleted a notebook during real indexing in 604.5 ms; health checks took 1.8–3.2 ms,
cleanup completed and no JavaScript errors occurred.

Text-only operation · 2026-10-10
-------------------------------

The active configuration now disables vision/audio loading, image uploads,
image indexing, OCR, image evidence retrieval, image previews and LLM image
attachments. Native document text uses the same Gemma model and embedding cache.
Index version 4 rebuilds older source indexes with new citation IDs; originals
and saved answers remain intact. Scanned PDFs need selectable text supplied
before import. Retained multimodal helpers are tested only with an explicit
test fixture that disables text-only mode. 177 tests and Ruff passed.

Simpler indexing and answer compatibility · 2026-10-10
----------------------------------------------------

The source panel now shows Indexing/Ready without passage counts or batch details.
The cached tokenizer makes extracted text available before loading Gemma's weights.
On this six-core CPU, an eight-text/image probe took 4.85/3.70 seconds with six
threads versus 5.76/4.38 seconds with four (about 15% less time, not a whole-file
benchmark). CPU indexing of image-heavy books still takes minutes. An experimental
INT8 conversion changed embeddings too much and was not enabled.

A live synthetic-image probe confirmed that RunInfra's DeepSeek V4.1 Flash
deployment accepts text only. Chat and Studio now use extracted text from the
same source page for that deployment, preserving real citations and avoiding
unsupported image payloads. Image-only evidence reports the model limitation.
A live synthetic-text check successfully streamed a cited answer. 173 automated
tests and Ruff passed.

Indexing responsiveness fix · 2026-10-10
---------------------------------------

- Split model inference from vector-table locking; queries have priority between
  small indexing batches. Checkpoints now commit every eight text passages.
- Source and notebook deletion immediately remove the database records, with
  durable file/vector cleanup after the import releases its resources.
- Extracted text is searchable while embeddings build. Document-description
  questions use source coverage without waiting for a query embedding.
- Removed the forced 1,120-token image setting and restored the checkpoint's
  native 280-token budget. Text embedding caches remain reusable; image cache
  keys include the budget. Small image details may have lower retrieval fidelity;
  extracted PDF text and answer attachments keep their existing resolution.
- 171 tests and Ruff passed. Four authored raster diagrams still ranked first;
  this is a small regression fixture, not a general accuracy measurement.
- An isolated Edge check deleted a notebook during real Gemma indexing and
  navigated home in 645 ms. Five health requests during indexing took 1.3–2.7 ms.
  Deferred cleanup completed and no JavaScript errors were recorded.

Reproduce the active-import UI check with `python scripts/responsiveness_check.py`.
CPU embedding still takes time; deletion and browsing no longer wait for it.

EmbeddingGemma 2 migration · 2026-10-10
-------------------------------------

EmbeddingGemma 2 is now the only retrieval model, with text and vision enabled and
audio disabled. BGE/FastEmbed and MiniLM reranking were removed from runtime code,
dependencies and settings. Old downloaded checkpoints were moved out of the active
model cache into a reversible local archive.

- 163 automated tests, Ruff and `pip check` passed.
- 15 isolated offline Edge checks passed, including upload/indexing, settings,
  benchmark charts/downloads and mobile width; no JavaScript errors were recorded.
- Three repetitions of 54 authored text questions: recall@8 1.0000, MRR@8 0.9630,
  nDCG@8 0.9684; warm median retrieval 63 ms and p95 144 ms on this machine.
- The 12-case conversation fixture recovered all labeled answerable evidence and
  rejected both unanswerable cases, with scope and routing checks passing.
- Four authored raster diagrams were each retrieved first without OCR. After the
  image relevance gate, each query attached only its matching diagram.

These are development fixtures, not general or held-out accuracy claims. Generated
answer quality was not evaluated in this migration. Existing personal PDFs were not
modified by the tests; on next startup, their old indexes are queued for rebuilding.
Originals, chat and stored citation snapshots remain; old citation IDs are never
reused for different chunk boundaries. Visual indexing runs on CPU here and takes
longer than text indexing.

Earlier records below describe the previous retrieval pipeline; their performance
and live-answer measurements do not establish Gemma performance or answer quality.

Verified locally on 2026-09-16 using Python 3.11.9 on Windows, with 12 logical CPUs and approximately 15.8 GB RAM. This record describes measured behavior, not every aspiration in the initial project plan.

Benchmark audit update · 2026-09-29
----------------------------------

The current benchmark changes passed **108 automated tests**, Ruff, `pip check`, and
`python benchmarks/publish.py --check`. Two existing test-client deprecation warnings remain.
The retrieval benchmark was rerun with three repetitions per configuration; the 10,000-page
scale run and both API-free RAG modes also completed successfully. A one-page scale run
verified that probe counts stay unique and within the generated page range.

An isolated, offline headless Edge check verified the benchmark page's failed-evaluation
status, raw judge verdicts, fixed-refusal disclosure, expandable judgments, current JSON
download, and mobile width, with no page errors. No live provider evaluation was rerun.
The failed historical live report and earlier retrieval/scale measurements remain available
in `docs/benchmark-history`. The sections below retain older broader verification records;
the generated benchmark tables show the current measured values.

Automated checks
----------------

`python -m pytest -q`: **40 passed**.

Coverage includes PDF page provenance, DOCX paragraphs/tables, PPTX slides, XLSX sheets/rows, CSV headers, HTML extraction, local image/scanned-PDF OCR, upload filenames, notebook/source isolation, duplicate imports, reindexing, deletion from FTS, restart recovery, the LlamaIndex workflow, invalid citation handling, quiz/map schema validation, PDF pagination/text extraction, compatible-provider SSE parsing, and HTTP/WebSocket origin restrictions.

`ruff check src tests scripts benchmarks` and `pip check` are the release checks. Two upstream test-client deprecation warnings occur with the installed FastAPI/Starlette versions; they do not fail the tests.

Browser checks
--------------

An isolated headless Microsoft Edge profile exercised a separate test data directory. No personal notebook was used as test material.

| Flow | Result |
| --- | --- |
| Home rendering and notebook creation | Passed |
| Actual browser file upload and background indexing | Passed |
| Offline, explicitly labeled source excerpts | Passed |
| Live Gemini chat with source citation | Passed |
| Note autosave and PDF browser download | Passed |
| Reload persistence for notes and conversations | Passed |
| Live generated mind map, quiz, and report | Passed |
| Quiz answers, score, and explanations | Passed |
| Settings dialog and mobile page width | Passed |
| JavaScript page errors | None recorded |

The latest real-provider run passed 17 named browser checks, including both benchmark charts, JSON download, and benchmark mobile width. It measured 2.40 s to the first visible Fast-mode answer, 3.48 s for a three-leaf mind map, 2.42 s for a two-question quiz, and 2.92 s for a short report. Earlier offline checks covered explicitly labeled excerpts. Four additional deterministic browser checks use a delayed local SSE fixture to verify waiting-state visibility, partial streaming, chat cancellation, and Studio cancellation without saving an artifact. Screenshots are in `docs/images`; raw local test output is in the ignored `test-results` folder.

Live network checks
-------------------

- Gemini `gemini-3.5-flash`: previously verified for chat, quiz, map, and report generation. During current latency probes it reported high demand once; two successful short answers delivered their first tokens in 11.67 s and 9.31 s.
- Gemini `gemini-3.5-flash-lite`: verified for actual chat, quiz, map, and report generation in the latest browser run. Separate short-answer probes delivered first tokens in 1.22 s and 1.77 s.
- Public website import: `https://www.python.org/about/` extracted a 2,353-byte readable source snapshot.
- Wikipedia integrated search: upstream HTTP error in this environment.
- Gemini integrated search: provider returned HTTP 429 / quota unavailable. Ordinary generation and search have distinct availability/quota constraints.
- Browser-search links provide a manual discovery path; direct URL ingestion remains available.

An additional optional key-free search-endpoint probe was not executed because automatic approval review reported a session usage limit. No success claim is made for that probe.

10,000-page benchmark
---------------------

Command: `python benchmarks/scale.py --pages 10000 --semantic`

<!-- scale-results:start -->
Measured 2026-09-29 · single run · hybrid · reranker disabled.

| Measurement | Observed |
| --- | ---: |
| Synthetic PDF pages | 10,000 |
| Indexed passages | 10,000 |
| Ingestion including local embeddings | 76 s |
| Average ingestion throughput | 131.59 pages/s |
| Cached reindexing | 10.24 s |
| Peak process RSS across ingestion, reindex and probes | 479.7 MB |
| Retrieval latency | 122, 116, 138, 128, 131 ms |
| Requested page found in top eight | 5 / 5 |

Generated from [raw scale measurements](benchmark-result.json).
<!-- scale-results:end -->

The fixture has approximately 40 words per page, a unique record identifier, and simple text layout. It exercises parsing, chunking, local embedding, vector writes, lexical indexing, filtering, and fused retrieval over a large page count. The reranker was disabled for this timing. The embedding model was loaded before timing. PDF fixture generation and model loading were outside the timed ingestion interval. Process RSS was sampled every 200 ms across ingestion, reindexing and probes, so very brief peaks can be missed.

This is not a 10,000-page scan, dense textbook, or mixed-format collection. Five exact-record probes are a smoke test, not a semantic relevance benchmark. They do not establish 100% general retrieval accuracy. End-to-end model generation time and cloud costs are outside these retrieval timings. Peak memory refers to the benchmark process, not total operating-system usage.

The current run checks ingestion completeness and refuses degraded retrieval. Earlier runs lacked the fallback guard. The committed current raw result is [benchmark-result.json](benchmark-result.json). The earlier run is retained as [benchmark-baseline.json](benchmark-baseline.json): 143.64 s initial ingestion and 516.8 MB peak RSS. These are single-run observations with different memory measurement intervals; they are not a controlled confidence interval. Rerunning creates a fresh isolated library under `test-results`; it does not add the synthetic corpus to the user's notebooks.

Labeled retrieval evaluation
----------------------------

The 54-question, 40-passage development fixture measures retrieval quality separately from page-count scaling. Current measured scores and timings are generated from the raw report in [RETRIEVAL_BENCHMARK.md](RETRIEVAL_BENCHMARK.md). The chart and table are checked against that report; earlier single-pass values are retained in benchmark history. This fixture bypasses document parsing and chunking.

The preceding 10,000-page result (126.67 s ingestion, 557.4 MB RSS) is retained in
[benchmark history](benchmark-history/scale-10000-previous.json). Differences from the
current run are observations across project versions and machine conditions, not an
isolated causal measurement of these benchmark-audit changes.

Remaining evaluation work
-------------------------

Before broader scale/quality claims, build a labeled mixed-format corpus with long paragraphs, tables, scans, multilingual material, contradictions, semantic paraphrases, and unanswerable questions. Measure retrieval Recall@K, citation entailment, ingestion failures, latency distributions, and OCR quality on that corpus. Test additional real compatible providers and legacy LibreOffice conversions on machines where they are installed.
