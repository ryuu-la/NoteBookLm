"""Run real local retrieval over a public labeled fixture and export auditable metrics."""
import hashlib
import json
import math
import os
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["NOTEBOOK_DATA_DIR"] = str(ROOT / "test-results" / f"retrieval-{time.time_ns()}")
os.environ["NOTEBOOK_MODEL_DIR"] = str(ROOT / ".data" / "models")

from corpus import dataset  # noqa: E402
from local_notebook import storage as db  # noqa: E402
from local_notebook.ingestion.jobs import add_file, flush  # noqa: E402
from local_notebook.retrieval import vectors  # noqa: E402
from local_notebook.retrieval.search import retrieve  # noqa: E402


def metrics(found, relevant, k=8):
    relevant = set(relevant)
    hits = [int(key in relevant) for key in found[:k]]
    recall = sum(hits) / len(relevant)
    reciprocal = next((1 / (i + 1) for i, hit in enumerate(hits) if hit), 0)
    dcg = sum(hit / math.log2(i + 2) for i, hit in enumerate(hits))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return {"recall_at_8": recall, "mrr_at_8": reciprocal, "ndcg_at_8": dcg / ideal}


def main():
    db.initialize()
    book = db.create_notebook("Public retrieval benchmark")
    passages, queries = dataset()
    source = add_file(book, "authored-study-notes.txt", b"Original benchmark fixture")
    chunks = [{"id": f"{source}_{i}", "source_id": source, "notebook_id": book, "ordinal": i,
               "locator": passage["id"], "text": passage["title"] + "\n" + passage["text"]}
              for i, passage in enumerate(passages)]
    started = time.perf_counter()
    flush(chunks, True)
    indexing = time.perf_counter() - started
    db.execute("UPDATE sources SET status='ready',chunks=? WHERE id=?", (len(chunks), source))
    configurations = [("Keyword", False, False, 40), ("Hybrid", True, False, 40),
                      ("Hybrid + 40 reranked", True, True, 40), ("Hybrid + 16 reranked", True, True, 16)]
    results = []
    for name, semantic, rerank, candidates in configurations:
        db.save_settings({"semantic": semantic, "rerank": rerank})
        vectors.query_vector.cache_clear()
        warm = retrieve(book, "A warmup question about classification", candidate_limit=candidates)
        samples = []
        for case in queries:
            evidence = retrieve(book, case["question"], candidate_limit=candidates)
            if evidence.warning:
                raise RuntimeError("Benchmark refused a degraded retrieval path: " + evidence.warning)
            found = [row["locator"] for row in evidence.passages]
            samples.append({**case, "retrieved": found, "latency_ms": evidence.elapsed_ms,
                            **metrics(found, case["relevant"])})
        latencies = sorted(row["latency_ms"] for row in samples)
        summary = {key: round(statistics.mean(row[key] for row in samples), 4)
                   for key in ("recall_at_8", "mrr_at_8", "ndcg_at_8")}
        summary.update(p50_ms=round(statistics.median(latencies), 1),
                       p95_ms=latencies[math.ceil(.95 * len(latencies)) - 1], warmup_ms=warm.elapsed_ms)
        result = {"name": name, "semantic": semantic, "rerank": rerank, "candidates": candidates,
                  **summary, "cases": samples}
        results.append(result)
        print(json.dumps({key: value for key, value in result.items() if key != "cases"}), flush=True)
    output = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus": "Original authored study notes v1",
              "passages": len(passages), "queries": len(queries), "indexing_seconds": round(indexing, 2),
              "fixture_sha256": hashlib.sha256(json.dumps(dataset(), sort_keys=True).encode()).hexdigest(),
              "python": platform.python_version(), "platform": platform.platform(),
              "protocol": "One pass per configuration, warm model, unique uncached queries, top 8. Same indexed corpus. No LLM/API calls.",
              "limitations": "Small developer-authored fixture, not held-out external evaluation. Recall measures labeled passage coverage, not generated-answer factual accuracy. No unanswerable-query or OCR evaluation. Warm latencies exclude model loading. Candidate ablation uses the same optimized engine in both configurations.",
              "results": results}
    target = ROOT / "src" / "local_notebook" / "assets" / "retrieval-benchmark.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Saved {target.name}", flush=True)


if __name__ == "__main__":
    main()
