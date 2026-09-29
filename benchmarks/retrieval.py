"""Run real local retrieval over a public labeled fixture and export auditable metrics."""
import argparse
import hashlib
import json
import math
import os
import platform
import random
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["NOTEBOOK_DATA_DIR"] = str(ROOT / "test-results" / f"retrieval-{time.time_ns()}")
os.environ["NOTEBOOK_MODEL_DIR"] = str(ROOT / ".data" / "models")

from corpus import dataset  # noqa: E402
from local_notebook import storage as db  # noqa: E402
from local_notebook.config import EMBED_THREADS  # noqa: E402
from local_notebook.evaluation import require_retrieval_mode, retrieval_metrics  # noqa: E402
from local_notebook.ingestion.jobs import add_file, flush  # noqa: E402
from local_notebook.retrieval import vectors  # noqa: E402
from local_notebook.retrieval.search import retrieve  # noqa: E402


def metrics(found, relevant, k=8):
    return {key: value for key, value in retrieval_metrics(found, relevant, k).items() if key != 'abstained'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--seed', type=int, default=20260929)
    parser.add_argument('--output', default='src/local_notebook/assets/retrieval-benchmark.json')
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
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
    rng = random.Random(args.seed)
    samples_by_name = {config[0]: [] for config in configurations}
    warmups = {config[0]: [] for config in configurations}
    execution_order = []
    for repeat in range(args.repeats):
        order = list(configurations)
        rng.shuffle(order)
        execution_order.append([config[0] for config in order])
        for name, semantic, rerank, candidates in order:
            db.save_settings({"semantic": semantic, "rerank": rerank})
            vectors.query_vector.cache_clear()
            warm = retrieve(book, "A warmup question about classification", candidate_limit=candidates)
            require_retrieval_mode(warm, semantic=semantic, rerank=rerank)
            warmups[name].append(warm.elapsed_ms)
            cases = list(queries)
            rng.shuffle(cases)
            for case in cases:
                evidence = retrieve(book, case["question"], candidate_limit=candidates)
                require_retrieval_mode(evidence, semantic=semantic, rerank=rerank)
                found = [row["locator"] for row in evidence.passages]
                samples_by_name[name].append({**case, 'repeat': repeat + 1, "retrieved": found,
                                             "latency_ms": evidence.elapsed_ms, **metrics(found, case["relevant"])})
            print(f'Completed repetition {repeat + 1}/{args.repeats}: {name}', flush=True)
    results = []
    for name, semantic, rerank, candidates in configurations:
        samples = samples_by_name[name]
        latencies = sorted(row["latency_ms"] for row in samples)
        summary = {key: round(statistics.mean(row[key] for row in samples), 4)
                   for key in ("recall_at_8", "mrr_at_8", "ndcg_at_8")}
        summary.update(p50_ms=round(statistics.median(latencies), 1),
                       p95_ms=latencies[math.ceil(.95 * len(latencies)) - 1], warmup_ms=warmups[name])
        result = {"name": name, "semantic": semantic, "rerank": rerank, "candidates": candidates,
                  **summary, 'sample_count': len(samples),
                  'per_repeat_p50_ms': [statistics.median(c['latency_ms'] for c in samples if c['repeat'] == i + 1)
                                        for i in range(args.repeats)], "cases": samples}
        results.append(result)
        print(json.dumps({key: value for key, value in result.items() if key != "cases"}), flush=True)
    output = {"created_at": datetime.now(timezone.utc).isoformat(), "corpus": "Original authored study notes v1",
              "passages": len(passages), "queries": len(queries), "indexing_seconds": round(indexing, 2),
              "fixture_sha256": hashlib.sha256(json.dumps(dataset(), sort_keys=True).encode()).hexdigest(),
              "python": platform.python_version(), "platform": platform.platform(),
              'repeats': args.repeats, 'seed': args.seed, 'execution_order': execution_order,
              'embedding_threads': EMBED_THREADS,
              "protocol": f"{args.repeats} repetitions per configuration, warm models, query cache cleared before each configuration/repetition, top 8. Seeded randomized configuration and question order. Scores and latency quantiles aggregate all repetitions; repetition medians are also saved. Same indexed corpus. No LLM/API calls.",
              "limitations": "Small developer-authored fixture, not held-out external evaluation. Prepared chunks bypass parsing and chunking. Recall measures labeled passage coverage, not generated-answer factual accuracy. No unanswerable-query or OCR evaluation. Warm latencies exclude model loading. Repetitions share a process and index; they are not independent machine-level trials or confidence intervals. Candidate ablation uses the same engine in both configurations.",
              "results": results}
    target = ROOT / args.output
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Saved {target.name}", flush=True)


if __name__ == "__main__":
    main()
