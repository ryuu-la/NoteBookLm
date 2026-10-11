# Folio implementation plan

Updated October 11, 2026. The [system architecture](docs/ARCHITECTURE.md) documents the implemented components, data flow, and recovery. The active configuration is text-only.

## Product decisions

- Keep a local Sources / streaming Chat / Studio workspace.
- Use `gemini-3.5-flash-lite` for Fast and `gemini-3.8-flash` for Main. No older-model backup or automatic cross-model fallback.
- Offer RunInfra with one selected model and a Local / compatible adapter. Keep EmbeddingGemma 2 as the only retrieval model; disable images/audio/OCR in the current product.
- Load the key and Gemini models from project `.env`, with project-file precedence. The user supplies the key. No browser key entry, per-notebook key requirement, or credential-store lookup.
- Preserve originals, locations, conversations and artifacts locally. Send only selected evidence and bounded conversation context to the chosen model.
- Extraction is one ingestion stage. Answers require retrieval, evidence selection, generation and citation validation.
- Distinguish searchable document coverage from bounded answer context. Do not claim exhaustive synthesis from a sampled overview.

## Implemented foundation

- [x] NiceGUI workspace, streaming chat, copy/edit/retry actions, notes and artifacts.
- [x] Durable text ingestion, document adapters, token-aware chunks, locations and per-record restart checkpoints. OCR helpers are retained but inactive.
- [x] FTS5 + local EmbeddingGemma 2 vectors in LanceDB, rank fusion and source/notebook isolation; BGE/MiniLM removed.
- [x] Full-index targeted retrieval, contextual follow-ups, distributed overview coverage and cited prompts.
- [x] Embedding reuse, batches of eight grouped by token count, cached OpenVINO FP32 CPU inference and configurable CPU thread budget.
- [x] Same-model retry before output, partial-answer preservation, actionable failures and cancellation.
- [x] Structured mind maps and quizzes, colored branches, independent expansion, free panning, movable topics, mouse/touch zoom and exports.
- [x] Searchable parsed text during semantic indexing, immediate metadata deletion with durable cleanup, and actionable website errors with paste-text recovery.
- [x] Data Analytics, Spreadsheet and Deep Research tools, deterministic table operations, exports and page-session Studio jobs.
- [x] Blank local `.env`, public example, restricted Gemini pair and removal of old credential/model fallback.
- [x] Retrieval regressions, conversation fixtures, claim/citation evaluations and browser/streaming checks.

## Current acceptance checks

1. Create a notebook without entering a key; generation without a key explains `.env` setup.
2. Gemini Fast/Main use the configured pair even when SQLite contains obsolete names; RunInfra uses its selected model consistently within a run.
3. Timeout/503 retries the same request once before output; missing-model errors stop. Partial text never triggers an automatic replacement answer.
4. `.env` stays untracked, the example contains no secret, and browser status reveals only key presence.
5. Regression and isolated browser checks pass. Verify live access only after the user supplies a key.

## Next engineering work, not yet implemented

| Priority | Work | Acceptance evidence |
| --- | --- | --- |
| 1 | Evaluate the configured pair using the user's key | First-token timing, error rate, generator/judge report; no replacement model |
| 2 | Calibrate retrieval on representative textbooks | Held-out labeled questions across chapters; recall, abstention, claim support and latency |
| 3 | Hierarchical synthesis for explicitly exhaustive overviews | Per-section summaries linked to passages, coverage accounting, resumable jobs, cost/time measurements |
| 4 | Broaden indexing performance evidence | Separate parse/chunk/embed/write timings on cold import and cached reindex; extend the measured OpenVINO/token-batching samples without reducing coverage |
| 5 | Evaluate optional GPU inference and parser isolation | Measured end-to-end gains, CPU fallback, cancellation and memory limits |
| 6 | Broader retrieval scale | Evaluate approximate indexes and worker coordination when corpus size requires them; retain isolation and recovery |

These are roadmap items, not claims of completed functionality. Do not substitute synthetic PDF timings for textbook/OCR performance, hide an outage behind an endless loader, or call citation-number validation proof of factual support.

## Data tools: implemented scope and remaining work

CSV/TSV/XLSX analysis, grouped aggregates, charts, structured research tables and
Excel/CSV exports are implemented. Source tables are bounded to 50,000 rows /
500,000 cells; the initial tool selects one table per request. Extracted web or
document rows are cited and do not imply complete datasets. Studio jobs can be
minimized and cancelled while the notebook page stays open.

Remaining work includes durable job resume across reload/restart, broader table
joins and transformations, workbook-preserving change tracking, and evaluation
on representative research tasks. Arbitrary model-written code and external
database execution are not implemented. Do not claim exhaustive web coverage.

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
