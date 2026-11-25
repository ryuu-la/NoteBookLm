"""Run local retrieval on the public MTEB/BEIR SciFact dataset (zero-shot scientific claim retrieval).

Downloads `mteb/scifact` (`corpus.jsonl`, `queries.jsonl`, `qrels/test.tsv`) into
`test-results/beir-cache/scifact/` and evaluates Folio's keyword and hybrid
(`EmbeddingGemma 2 + keyword`) retrieval using standard BEIR metrics (`nDCG@10`,
`MRR@10`, `Recall@10`).
"""
import argparse
import csv
import json
import math
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "test-results" / "beir-cache" / "scifact"
os.environ["NOTEBOOK_DATA_DIR"] = str(ROOT / "test-results" / f"beir-scifact-{time.time_ns()}")
os.environ["NOTEBOOK_MODEL_DIR"] = str(ROOT / ".data" / "models")

from local_notebook import storage as db  # noqa: E402
from local_notebook.config import EMBED_DIM, EMBED_MODEL, EMBED_THREADS  # noqa: E402
from local_notebook.evaluation import require_retrieval_mode, retrieval_metrics  # noqa: E402
from local_notebook.ingestion.jobs import add_file, flush  # noqa: E402
from local_notebook.retrieval import vectors  # noqa: E402
from local_notebook.retrieval.search import retrieve  # noqa: E402

BASE_URL = "https://huggingface.co/datasets/mteb/scifact/resolve/main"
FILES = {
    "corpus.jsonl": f"{BASE_URL}/corpus.jsonl",
    "queries.jsonl": f"{BASE_URL}/queries.jsonl",
    "test.tsv": f"{BASE_URL}/qrels/test.tsv",
}


def download_dataset() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for name, url in FILES.items():
            target = CACHE_DIR / name
            if target.exists() and target.stat().st_size > 0:
                continue
            print(f"Downloading {name}...", flush=True)
            response = client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)


def load_dataset():
    download_dataset()
    corpus = []
    with (CACHE_DIR / "corpus.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            title = (row.get("title") or "").strip()
            text = (row.get("text") or "").strip()
            corpus.append({
                "id": str(row["_id"]),
                "text": f"{title}\n{text}" if title else text,
            })
    queries = {}
    with (CACHE_DIR / "queries.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            queries[str(row["_id"])] = row["text"]
    qrels: dict[str, list[str]] = {}
    with (CACHE_DIR / "test.tsv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            score = float(row.get("score", 1))
            if score > 0:
                qrels.setdefault(str(row["query-id"]), []).append(str(row["corpus-id"]))
    test_cases = [{"id": qid, "question": queries[qid], "relevant": rels}
                  for qid, rels in qrels.items() if qid in queries]
    return corpus, test_cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keyword-only", action="store_true", help="Skip semantic indexing and evaluate keyword search only.")
    parser.add_argument("--max-docs", type=int, default=0, help="Evaluate on a subset of N docs including all relevant passages (0 = all).")
    parser.add_argument("--max-queries", type=int, default=0, help="Evaluate at most N test queries (0 = all).")
    parser.add_argument("--output", default="test-results/beir-scifact.json")
    args = parser.parse_args()

    corpus, test_cases = load_dataset()
    if args.max_queries > 0:
        test_cases = test_cases[:args.max_queries]
    if args.max_docs > 0:
        relevant_ids = {cid for case in test_cases for cid in case["relevant"]}
        selected = [doc for doc in corpus if doc["id"] in relevant_ids]
        seen_ids = {doc["id"] for doc in selected}
        for doc in corpus:
            if len(selected) >= args.max_docs:
                break
            if doc["id"] not in seen_ids:
                selected.append(doc)
                seen_ids.add(doc["id"])
        corpus = selected

    db.initialize()
    book = db.create_notebook("BEIR SciFact")
    source = add_file(book, "scifact-corpus.txt", b"MTEB/BEIR SciFact corpus")
    chunks = [{
        "id": f"{source}_{i}",
        "source_id": source,
        "notebook_id": book,
        "ordinal": i,
        "locator": doc["id"],
        "text": doc["text"],
    } for i, doc in enumerate(corpus)]

    semantic = not args.keyword_only
    started = time.perf_counter()
    for start in range(0, len(chunks), 256):
        flush(chunks[start:start + 256], semantic)
        if semantic and ((start // 256) % 4 == 3 or start + 256 >= len(chunks)):
            done = min(start + 256, len(chunks))
            print(f"Indexed {done}/{len(chunks)} passages ({time.perf_counter() - started:.1f}s)", flush=True)
    indexing_seconds = round(time.perf_counter() - started, 2)
    db.execute("UPDATE sources SET status='ready', chunks=? WHERE id=?", (len(chunks), source))

    configs = [("Keyword", False)]
    if semantic:
        configs.append(("EmbeddingGemma 2 + keyword", True))

    results = []
    for name, use_semantic in configs:
        db.save_settings({"semantic": use_semantic})
        vectors.query_vector.cache_clear()
        warm = retrieve(book, "Does vitamin D reduce respiratory infection risk?", limit=10)
        require_retrieval_mode(warm, semantic=use_semantic)

        latencies = []
        recalls, mrrs, ndcgs = [], [], []
        for case in test_cases:
            evidence = retrieve(book, case["question"], limit=10)
            require_retrieval_mode(evidence, semantic=use_semantic)
            found = [p["locator"] for p in evidence.passages]
            metrics = retrieval_metrics(found, case["relevant"], k=10)
            latencies.append(evidence.elapsed_ms)
            recalls.append(metrics["recall_at_8"])
            mrrs.append(metrics["mrr_at_8"])
            ndcgs.append(metrics["ndcg_at_8"])

        ordered = sorted(latencies)
        summary = {
            "name": name,
            "semantic": use_semantic,
            "queries": len(test_cases),
            "recall_at_10": round(statistics.mean(recalls), 4),
            "mrr_at_10": round(statistics.mean(mrrs), 4),
            "ndcg_at_10": round(statistics.mean(ndcgs), 4),
            "p50_ms": round(statistics.median(ordered), 1),
            "p95_ms": ordered[math.ceil(0.95 * len(ordered)) - 1],
        }
        results.append(summary)
        print(json.dumps(summary), flush=True)

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "mteb/scifact (BEIR SciFact test split)",
        "passages": len(corpus),
        "queries": len(test_cases),
        "indexing_seconds": indexing_seconds,
        "embedding_model": EMBED_MODEL if semantic else None,
        "embedding_dimensions": EMBED_DIM if semantic else None,
        "embedding_threads": EMBED_THREADS,
        "results": results,
    }
    target = ROOT / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Saved {target}", flush=True)


if __name__ == "__main__":
    main()
