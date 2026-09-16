"""Reproducible synthetic PDF ingestion benchmark; never touches the user's notebooks."""
import argparse
import json
import os
import platform
import threading
import time
from pathlib import Path

import psutil

parser = argparse.ArgumentParser()
parser.add_argument("--pages", type=int, default=10000)
parser.add_argument("--semantic", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
run_dir = root / "test-results" / f"scale-{args.pages}-{'hybrid' if args.semantic else 'lexical'}-{time.time_ns()}"
run_dir.mkdir(parents=True, exist_ok=True)
os.environ["NOTEBOOK_DATA_DIR"] = str(run_dir / "data")

from fpdf import FPDF
from local_notebook import storage as db
from local_notebook.ingestion import jobs
from local_notebook.retrieval import vectors
from local_notebook.retrieval.search import retrieve

db.initialize()
db.save_settings({"semantic": args.semantic, "rerank": False})
if args.semantic:
    from fastembed import TextEmbedding
    vectors._model = TextEmbedding("BAAI/bge-small-en-v1.5", cache_dir=str(root / ".data" / "models"), threads=2)
book = db.create_notebook(f"Synthetic benchmark {args.pages}")
pdf_path = run_dir / "corpus.pdf"
document = FPDF()
document.set_font("Helvetica", size=10)
for number in range(1, args.pages + 1):
    document.add_page()
    document.multi_cell(0, 6, f"Research record ZX{number:06d}. Experiment {number} examines solar energy storage. "
                        f"The measured capacity is {number % 997 + 1} units. This synthetic page is generated "
                        "for retrieval testing and is not a scientific claim.")
document.output(pdf_path)
del document
process = psutil.Process()
peak = {"rss": process.memory_info().rss}
finished = threading.Event()


def monitor():
    while not finished.wait(.2):
        peak["rss"] = max(peak["rss"], process.memory_info().rss)


threading.Thread(target=monitor, daemon=True).start()
started = time.perf_counter()
source_id = jobs.add_file(book, "synthetic-corpus.pdf", pdf_path.read_bytes())
source = db.one("SELECT * FROM sources WHERE id=?", (source_id,))
jobs.ingest(source)
elapsed = time.perf_counter() - started
reindex_started = time.perf_counter()
jobs.ingest({**db.one("SELECT * FROM sources WHERE id=?", (source_id,)), "chunks": 0})
reindex_elapsed = time.perf_counter() - reindex_started
latencies, correct = [], 0
for number in [1, 17, max(1, args.pages // 2), max(1, args.pages - 1), args.pages]:
    result = retrieve(book, f"ZX{number:06d} capacity")
    latencies.append(result.elapsed_ms)
    correct += any(passage["locator"] == f"Page {number}" for passage in result.passages)
finished.set()
source = db.one("SELECT * FROM sources WHERE id=?", (source_id,))
output = {"corpus": "Synthetic digital PDF, 40 words per page; no OCR or complex layout",
          "pages": args.pages, "chunks": source["chunks"], "mode": "hybrid" if args.semantic else "lexical",
          "ingestion_seconds": round(elapsed, 2), "pages_per_second": round(args.pages / elapsed, 2),
          "cached_reindex_seconds": round(reindex_elapsed, 2),
          "peak_process_rss_mb": round(peak["rss"] / 1024**2, 1), "retrieval_ms": latencies,
          "exact_record_recall_at_8": correct / 5, "python": platform.python_version(),
          "platform": platform.platform(), "logical_cpus": psutil.cpu_count(),
          "machine_ram_gb": round(psutil.virtual_memory().total / 1024**3, 1)}
(run_dir / "result.json").write_text(json.dumps(output, indent=2))
print(json.dumps(output, indent=2), flush=True)
