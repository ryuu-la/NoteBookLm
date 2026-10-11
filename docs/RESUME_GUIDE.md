Demonstrating Folio
==================

Suggested project description
-----------------------------

**Folio — local AI research and study workspace**

Python · LlamaIndex · NiceGUI/FastAPI · LanceDB · SQLite FTS5 · EmbeddingGemma 2 · OpenVINO/PyTorch · Gemini/RunInfra · Pydantic

- Built a local document research application with streaming, source-cited answers, interactive mind maps, quizzes, reports, and PDF notes.
- Implemented text-only Gemma embeddings, BM25 keyword search and reciprocal rank fusion with notebook/source isolation, without a separate reranker.
- Added cached OpenVINO FP32 CPU inference, token-based batch ordering and reusable embeddings; measured the embedding stage separately from full import time.
- Built a reproducible 54-question retrieval fixture and a separate conversation/citation evaluation; report developer-fixture results with their scope and limitations.
- Added durable per-record ingestion checkpoints, duplicate detection, typed artifact validation and automated/browser checks. OCR/image helpers are inactive in the current text-only product.
- Built a free-panning mind-map canvas with independent topic dragging, connected curves, pointer-anchored zoom and mobile touch gestures.

Use only statements you understand and can demonstrate. Historical 10,000-page and reranker timings in the verification archive describe older pipelines; do not present them as current Gemma performance. Keep **synthetic** and the original model/setup when citing those records. Do not claim production deployment or broad answer accuracy.

Five-minute demonstration
-------------------------

1. Show the home page and explain that no application account is needed.
2. Open a notebook with two or three small sources; upload a new PDF.
3. Ask a specific question and open the supporting citation. Explain that source selection filters retrieval, not merely the prompt.
4. Deselect one source and show that its evidence is excluded.
5. Generate a quiz, answer it, and show the explanation and citations.
6. Generate a mind map; drag the canvas and a topic, zoom, expand a branch and inspect its supporting source.
7. Save an answer to notes, export a PDF, and reload to prove persistence.
8. Show the architecture and scoped benchmark result, then explain one limitation honestly.

Questions to prepare for
-----------------------

- Why combine BM25 and dense retrieval? Exact identifiers and semantic paraphrases need different matching signals.
- Why no separate reranker? The current simpler pipeline combines one Gemma model with keyword rank fusion; evaluate its quality on representative questions rather than assuming a universal tradeoff.
- Why not send all 10,000 pages to the model? Evidence selection controls context size, latency, cost, and traceability.
- What happens after a crash? The queue reparses incomplete sources, skips records with committed vectors and uses idempotent upserts, even when token-based batching changes document order.
- What does a citation prove? Its ID and location exist; semantic support still needs evaluation or human verification.
- How is local storage different from local inference? Cloud generation transmits selected evidence; a compatible local model can keep inference on the machine.
- What would you improve next? Broad-corpus hierarchical synthesis, multilingual quality evaluation, stronger layout parsing, parser-process isolation, and packaging.

Before publishing a repository
------------------------------

Review the files to be committed. Exclude `.data`, `.venv`, environment files, credential stores, logs, and personal documents. The included sample sources are original demonstration material. Use the provided MIT license for this code and retain dependency/model license notices.

The source repository is intended for `https://github.com/ryuu-la/NoteBookLm`. The application runs locally; the repository is not a hosted multi-user service. Run `python scripts/check_secrets.py` against staged/tracked files before publishing changes.
