import hashlib
import logging
import threading
from pathlib import Path

from .. import storage as db
from ..config import DATA, MAX_UPLOAD
from ..retrieval import vectors
from .parsers import SUPPORTED, parse

logger = logging.getLogger(__name__)
_wake = threading.Event()
_stop = threading.Event()
_worker = None
_active = set()


def add_file(notebook_id: str, name: str, data: bytes, url="") -> str:
    if not db.one("SELECT id FROM notebooks WHERE id=?", (notebook_id,)):
        raise ValueError("Notebook no longer exists")
    if len(data) > MAX_UPLOAD:
        raise ValueError("Maximum file size is 150 MB. Split larger files before importing.")
    safe_name = Path(name.replace("\\", "/")).name
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED:
        raise ValueError("Unsupported format. Use PDF, Office, text, CSV, HTML, JSON, or an image.")
    digest = hashlib.sha256(data).hexdigest()
    existing = db.one("SELECT id FROM sources WHERE notebook_id=? AND hash=?", (notebook_id, digest))
    if existing:
        return existing["id"]
    identifier = db.uid()
    path = DATA / "originals" / (identifier + extension)
    path.write_bytes(data)
    db.execute("""INSERT INTO sources
        (id,notebook_id,name,kind,path,hash,url,created_at) VALUES (?,?,?,?,?,?,?,?)""",
               (identifier, notebook_id, safe_name, extension[1:], str(path), digest, url, db.now()))
    db.touch(notebook_id)
    _wake.set()
    return identifier


def update(identifier: str, **fields) -> None:
    allowed = {"status", "progress", "units", "chunks", "error"}
    if not set(fields) <= allowed:
        raise ValueError("Invalid source update")
    db.execute("UPDATE sources SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
               (*fields.values(), identifier))


def is_cancelled(identifier: str) -> bool:
    row = db.one("SELECT status FROM sources WHERE id=?", (identifier,))
    return _stop.is_set() or row is None or row["status"] == "cancelled"


def ingest(source: dict) -> None:
    from llama_index.core.node_parser import SentenceSplitter
    splitter = SentenceSplitter(chunk_size=600, chunk_overlap=70)
    identifier = source["id"]
    checkpoint = source["chunks"]
    update(identifier, status="parsing", error="")
    if not checkpoint:
        vectors.remove(identifier)
        db.execute("DELETE FROM chunks WHERE source_id=?", (identifier,))
    ordinal, batch, units = 0, [], 0
    semantic = db.settings()["semantic"]
    for units, block in enumerate(parse(Path(source["path"])), 1):
        if is_cancelled(identifier):
            return
        if not block.text.strip():
            continue
        for text in splitter.split_text(block.text):
            if ordinal < checkpoint:
                ordinal += 1
                continue
            batch.append({"id": f"{identifier}_{ordinal}", "source_id": identifier,
                          "notebook_id": source["notebook_id"], "ordinal": ordinal,
                          "locator": block.locator, "text": text})
            ordinal += 1
        if len(batch) >= 128:
            flush(batch, semantic)
            batch = []
            update(identifier, status="indexing", chunks=ordinal, units=units)
    if batch:
        flush(batch, semantic)
    if is_cancelled(identifier):
        return
    if not ordinal:
        raise ValueError("No readable text was found in this source.")
    update(identifier, status="ready", progress=100, chunks=ordinal, units=units)


def flush(chunks: list[dict], semantic: bool) -> None:
    if semantic:
        vectors.insert(chunks)
    with db.connect() as connection:
        connection.executemany("INSERT OR IGNORE INTO chunks VALUES (?,?,?,?,?,?)",
                               [(row["id"], row["source_id"], row["notebook_id"], row["ordinal"],
                                 row["locator"], row["text"]) for row in chunks])


def loop() -> None:
    while not _stop.is_set():
        source = db.one("SELECT * FROM sources WHERE status='queued' ORDER BY created_at LIMIT 1")
        if not source:
            _wake.wait(2)
            _wake.clear()
            continue
        try:
            _active.add(source["id"])
            ingest(source)
        except Exception as exc:
            logger.exception("Source ingestion failed for %s", source["id"])
            update(source["id"], status="error", error=str(exc)[:500])
        finally:
            _active.discard(source["id"])


def start() -> None:
    global _worker
    if _worker is None or not _worker.is_alive():
        _stop.clear()
        _worker = threading.Thread(target=loop, name="ingestion", daemon=True)
        _worker.start()


def stop() -> None:
    _stop.set()
    _wake.set()


def retry(identifier: str) -> None:
    if identifier in _active:
        raise ValueError("This source is still being processed. Cancel it and wait before reindexing.")
    update(identifier, status="queued", error="", progress=0, chunks=0, units=0)
    _wake.set()


def delete_source(identifier: str) -> None:
    source = db.one("SELECT * FROM sources WHERE id=?", (identifier,))
    if not source:
        return
    if source["status"] in {"parsing", "indexing"} or identifier in _active:
        update(identifier, status="cancelled")
        raise ValueError("Import cancelled. Remove it again after the worker finishes its current batch.")
    vectors.remove(identifier)
    db.execute("DELETE FROM sources WHERE id=?", (identifier,))
    path = Path(source["path"])
    if path.is_relative_to(DATA / "originals"):
        path.unlink(missing_ok=True)
