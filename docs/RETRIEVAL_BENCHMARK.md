Retrieval benchmark · September 2026
===================================

The benchmark runs the actual SQLite FTS5, BGE-small embedding, LanceDB, reciprocal rank fusion, and MiniLM reranking pipeline. No language-model API participates in this measurement. The UI at `/benchmarks` reads the committed result and offers the complete JSON for download.

![Quality and latency](images/retrieval-benchmark.png)

| Configuration | Recall@8 | MRR@8 | nDCG@8 | Median | p95 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Keyword | 1.0000 | 0.9312 | 0.9404 | 4 ms | 5 ms |
| Hybrid | 1.0000 | 0.9815 | 0.9848 | 13 ms | 15 ms |
| Hybrid + 40 reranked | 1.0000 | 1.0000 | 0.9977 | 473 ms | 498 ms |
| Hybrid + 16 reranked | 1.0000 | 1.0000 | 0.9977 | 208 ms | 227 ms |

The smaller shortlist was 56% faster at the median while preserving these fixture scores. The 40-candidate configuration remains available in Settings because other collections may need broader candidate coverage.

Protocol
--------

- The original fixture in `benchmarks/corpus.py` contains 24 study passages, 16 distractors, 48 direct/paraphrased questions, and 6 questions requiring two passages. Topics cover machine learning, retrieval, databases, and study techniques.
- Relevance judgments are authored with the fixture. A relevant passage is identified by its stable fixture ID. Comparisons require both labeled passages.
- Each configuration searches the same isolated index. Every question is run once, with model sessions warmed by a different question. Query-embedding caches are cleared before each configuration; measured questions are unique within a configuration.
- Recall@8 is the fraction of labeled passages found in the first eight results. MRR@8 is the reciprocal rank of the first relevant passage. nDCG@8 evaluates placement of all relevant passages with binary relevance and logarithmic rank discounts. Scores are macro-averaged over questions.
- Median and nearest-rank p95 cover retrieval only. Indexing, initial model loading, network requests, generation, and browser rendering are excluded. The JSON includes warmup time separately.
- Both reranker configurations use the optimized engine; this is a shortlist ablation, not a historical software-version comparison. Their cross-encoder batches contain eight passages.
- Python 3.11.9, Windows, 12 logical CPUs, approximately 16 GB RAM; ONNX model sessions use two inference threads. All query rankings, timings, platform details, and the fixture SHA-256 are in the result file.

Limits
------

This is a small **developer-authored development fixture**, not an independent held-out test. Short passages and a compact candidate pool make it easier than a full textbook library. Several queries share vocabulary with their evidence. Perfect Recall@8 on this fixture does not establish perfect retrieval, entailment, factual accuracy, or answer completeness on user documents.

Unanswerable questions, multilingual text, OCR errors, contradictory evidence, dense tables, and long-document semantic accuracy are not evaluated here. A dense retriever can return neighbors even when no answer exists. The generation prompt asks for abstention, but this benchmark does not measure that behavior. Future evaluation should use a larger independent corpus with explicit negative judgments and citation-support scoring.

Reproduce
---------

```powershell
.\.venv\Scripts\python.exe benchmarks\retrieval.py
.\.venv\Scripts\python.exe benchmarks\plot.py
```

Run after installing the project development extra and downloading the local embedding/reranker models. The runner uses a fresh `test-results` directory and refuses to report degraded keyword fallback as hybrid results. It replaces `src/local_notebook/assets/retrieval-benchmark.json`; the plotter creates PNG and SVG figures in `docs/images`. A rerun on another machine will have different timings.

Additional measured improvements
--------------------------------

A timing-only check on an existing 437-passage PDF reduced warm retrieval from approximately 3.7 s to 1.3 s across the same three queries. Its contents and query-level evidence are not published. This diagnostic is separate from the public relevance fixture.

The same synthetic 10,000-page generator used by the earlier release measured 126.67 s for initial indexing, versus an earlier 143.64 s observation. Cached reindexing measured 22.16 s. These are single-run observations, not a controlled multi-run confidence interval; page text is short and no OCR is involved. The cache is content- and model-keyed, and batching now writes approximately 128 passages per checkpoint.

An isolated live browser run measured 2.40 s until the first visible Fast-mode answer, 3.48 s for a three-leaf mind map, 2.42 s for a two-question quiz, and 2.92 s for a short report. These use one short original source and Flash-Lite. During separate probes Flash reported high demand and took 9–12 s to deliver the first token, while Flash-Lite took 1.2–1.8 s. Provider demand and answer size affect latency independently of retrieval.

Gemini's official [thinking documentation](https://ai.google.dev/gemini-api/docs/thinking) describes the latency/reasoning tradeoff. The app exposes thinking effort and uses `minimal` for supported Gemini Flash models by default. The Fast/Main control makes the chosen model explicit.
