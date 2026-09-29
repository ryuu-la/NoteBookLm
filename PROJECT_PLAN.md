# Folio implementation plan

Updated September 29, 2026. This replaces the original credential-store and arbitrary Gemini model configuration. The [system architecture](docs/ARCHITECTURE.md) documents the implemented components, data flow, and recovery.

## Product decisions

- Keep a local Sources / streaming Chat / Studio workspace.
- Use `gemini-3.5-flash-lite` for Fast and `gemini-3.8-flash` for Main. No older-model backup or automatic cross-model fallback.
- Load the key and Gemini models from project `.env`, with project-file precedence. The user supplies the key. No browser key entry, per-notebook key requirement, or credential-store lookup.
- Preserve originals, locations, conversations and artifacts locally. Send only selected evidence and bounded conversation context to the chosen model.
- Extraction is one ingestion stage. Answers require retrieval, evidence selection, generation and citation validation.
- Distinguish searchable document coverage from bounded answer context. Do not claim exhaustive synthesis from a sampled overview.

## Implemented foundation

- [x] NiceGUI workspace, streaming chat, copy/edit/retry actions, notes and artifacts.
- [x] Durable ingestion queue, document adapters, optional OCR, token-aware chunks, locations and restart recovery.
- [x] FTS5 + local BGE vectors in LanceDB, rank fusion, MiniLM reranking and source/notebook isolation.
- [x] Full-index targeted retrieval, contextual follow-ups, distributed overview coverage and cited prompts.
- [x] Embedding reuse, bounded batches, length-aware inference and configurable CPU thread budget.
- [x] Same-model retry before output, partial-answer preservation, actionable failures and cancellation.
- [x] Structured mind maps and quizzes, colored branches, individual/all expansion, zoom and exports.
- [x] Blank local `.env`, public example, restricted Gemini pair and removal of old credential/model fallback.
- [x] Retrieval regressions, conversation fixtures, claim/citation evaluations and browser/streaming checks.

## Current acceptance checks

1. Create a notebook without entering a key; generation without a key explains `.env` setup.
2. Fast/Main use the configured pair even when SQLite contains obsolete model names.
3. Timeout/503 retries the same request once before output; missing-model errors stop. Partial text never triggers an automatic replacement answer.
4. `.env` stays untracked, the example contains no secret, and browser status reveals only key presence.
5. Regression and isolated browser checks pass. Verify live access only after the user supplies a key.

## Next engineering work, not yet implemented

| Priority | Work | Acceptance evidence |
| --- | --- | --- |
| 1 | Evaluate the configured pair using the user's key | First-token timing, error rate, generator/judge report; no replacement model |
| 2 | Calibrate retrieval on representative textbooks | Held-out labeled questions across chapters; recall, abstention, claim support and latency |
| 3 | Hierarchical synthesis for explicitly exhaustive overviews | Per-section summaries linked to passages, coverage accounting, resumable jobs, cost/time measurements |
| 4 | Attribute real indexing bottlenecks | Separate parse/OCR/chunk/embed/write timings on cold import and cached reindex without reducing coverage |
| 5 | Evaluate optional GPU inference and parser isolation | Measured end-to-end gains, CPU fallback, cancellation and memory limits |
| 6 | Broader retrieval scale | Evaluate approximate indexes and worker coordination when corpus size requires them; retain isolation and recovery |

These are roadmap items, not claims of completed functionality. Do not substitute synthetic PDF timings for textbook/OCR performance, hide an outage behind an endless loader, or call citation-number validation proof of factual support.

## Deferred: data analysis and research spreadsheets

Planned for later; not implemented in this update:

- Analyze uploaded CSV/XLSX files with deterministic cleaning, grouping, calculations, and charts; export a real XLSX workbook preserving original data and a change log.
- Research a bounded list of entities into a structured comparison table, with source URLs, supporting excerpts, retrieval dates, and explicit missing or conflicting values.
- Run these as separate Studio background tasks with progress, bounded concurrency, cancellation, resume, and partial export, keeping normal chat fast.
- Start with file analysis, then research tables for 10–20 entities. Defer arbitrary model-written code, external database integrations, and larger jobs.
- Reuse existing research and Studio capabilities. Preserve workbook structure rather than relying on text chunks. Do not claim exhaustive internet coverage or verified accuracy.

## Validation commands

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check src tests scripts benchmarks
.venv/Scripts/python.exe scripts/browser_check.py
.venv/Scripts/python.exe scripts/streaming_check.py
.venv/Scripts/python.exe benchmarks/rag.py --keyword --output test-results/rag-keyword.json
.venv/Scripts/python.exe benchmarks/rag.py --output test-results/rag-hybrid.json

# After adding GEMINI_API_KEY to .env; consumes provider quota.
.venv/Scripts/python.exe benchmarks/rag.py --answers --model gemini-3.5-flash-lite --judge-model gemini-3.8-flash --output test-results/rag-live.json
```

Keep regression libraries and generated reports under `test-results/`. Do not use private notebook content as a public fixture. Keep logs, runtime databases, original documents, and credentials out of version control.
