Demonstrating Folio
==================

Suggested project description
-----------------------------

**Folio — local AI research and study workspace**

Python · LlamaIndex · NiceGUI/FastAPI · LanceDB · SQLite FTS5 · FastEmbed/ONNX · Gemini · Pydantic

- Built a local document research application with streaming, source-cited answers, interactive mind maps, quizzes, reports, and PDF notes.
- Implemented a LlamaIndex retrieval workflow combining local embeddings, BM25 keyword search, reciprocal rank fusion, and cross-encoder reranking, with notebook-level source isolation.
- Indexed a 10,000-page synthetic digital PDF in 127 seconds and reindexed in 22 seconds using a content-keyed embedding cache; measured 27–41 ms retrieval on five exact-record probes with reranking disabled.
- Built a reproducible 54-question retrieval evaluation and chart; a 16-candidate reranking shortlist preserved the development fixture's quality while reducing median retrieval latency from 473 ms to 208 ms compared with 40 candidates.
- Added durable ingestion checkpoints, duplicate detection, OCR, typed artifact validation, automated tests, and browser checks against live Gemini generation.

Use only statements you understand and can demonstrate. Keep the word **synthetic** in the benchmark claim. Do not claim a production deployment, a broad accuracy percentage, or support for every document format.

Five-minute demonstration
-------------------------

1. Show the home page and explain that no application account is needed.
2. Open a notebook with two or three small sources; upload a new PDF.
3. Ask a specific question and open the supporting citation. Explain that source selection filters retrieval, not merely the prompt.
4. Deselect one source and show that its evidence is excluded.
5. Generate a quiz, answer it, and show the explanation and citations.
6. Generate a mind map; expand a branch and find its supporting source.
7. Save an answer to notes, export a PDF, and reload to prove persistence.
8. Show the architecture and scoped benchmark result, then explain one limitation honestly.

Questions to prepare for
-----------------------

- Why combine BM25 and dense retrieval? Exact identifiers and semantic paraphrases need different matching signals.
- Why rerank? A cross-encoder compares the query with candidate passages jointly, at a higher per-passage cost.
- Why not send all 10,000 pages to the model? Evidence selection controls context size, latency, cost, and traceability.
- What happens after a crash? The durable queue replays incomplete sources, skips committed passage ordinals, and uses idempotent writes.
- What does a citation prove? Its ID and location exist; semantic support still needs evaluation or human verification.
- How is local storage different from local inference? Cloud generation transmits selected evidence; a compatible local model can keep inference on the machine.
- What would you improve next? Broad-corpus hierarchical synthesis, multilingual quality evaluation, stronger layout parsing, parser-process isolation, and packaging.

Before publishing a repository
------------------------------

Review the files to be committed. Exclude `.data`, `.venv`, environment files, credential stores, logs, and personal documents. The included sample sources are original demonstration material. Use the provided MIT license for this code and retain dependency/model license notices.

The source repository is intended for `https://github.com/ryuu-la/NoteBookLm`. The application runs locally; the repository is not a hosted multi-user service. Run `python scripts/check_secrets.py` against staged/tracked files before publishing changes.
