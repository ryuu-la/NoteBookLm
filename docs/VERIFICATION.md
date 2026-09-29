Verification record
===================

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
