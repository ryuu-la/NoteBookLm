import hashlib
import json
import logging
import threading
import time
from pathlib import Path

from .. import storage as db
from ..config import DATA, MAX_UPLOAD, INDEX_VERSION, TEXT_ONLY
from ..retrieval import vectors
from .parsers import SUPPORTED, IMAGE_TYPES, parse
from .chunking import make_splitter

logger = logging.getLogger(__name__)
EMBED_BATCH_SIZE = 8
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
    if TEXT_ONLY and extension in IMAGE_TYPES:
        raise ValueError('Text-only mode: upload a document containing selectable text.')
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
    allowed = {"status", "progress", "units", "chunks", "error", "detail", "elapsed_seconds"}
    if not set(fields) <= allowed:
        raise ValueError("Invalid source update")
    db.execute("UPDATE sources SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
               (*fields.values(), identifier))


def is_cancelled(identifier: str) -> bool:
    row = db.one("SELECT status FROM sources WHERE id=?", (identifier,))
    return _stop.is_set() or row is None or row["status"] == "cancelled"


def ingest(source: dict) -> None:
    # Keep one connection open for the job. Closing the last WAL connection
    # after every progress update forces repeated checkpoints on Windows.
    # Commit each checkpoint explicitly so cancellation/recovery remain durable.
    with db.connect() as connection:
        _ingest(source, connection)


def _ingest(source: dict, connection) -> None:
    identifier = source["id"]
    checkpoint = source["chunks"] if source.get('index_version') == INDEX_VERSION else 0
    started = time.perf_counter()
    last_poll = 0.0
    last_report = 0.0
    semantic = db.settings()["semantic"]

    def cancelled(force=False):
        nonlocal last_poll
        now = time.perf_counter()
        if _stop.is_set():
            return True
        if force or now - last_poll >= .2:
            last_poll = now
            return is_cancelled(identifier)
        return False

    def report(**fields):
        # A completed batch must never turn a cancelled job back into an active job.
        fields["elapsed_seconds"] = round(time.perf_counter() - started, 1)
        connection.execute("UPDATE sources SET " + ",".join(f"{key}=?" for key in fields)
                           + " WHERE id=? AND status!='cancelled'", (*fields.values(), identifier))
        connection.commit()

    if cancelled(True):
        return
    report(status="parsing", progress=0, error="", chunks=checkpoint,
           index_version=INDEX_VERSION if semantic else -INDEX_VERSION,
           detail="Reading and organizing your document…")
    splitter = make_splitter(semantic)
    count_tokens = getattr(splitter, 'token_count', len)
    if not checkpoint:
        vectors.remove(identifier)
        db.execute("DELETE FROM chunks WHERE source_id=?", (identifier,))
    ordinal, batch, units = 0, [], 0
    # Stage text on disk first: bounded memory, early progress, and a known embedding total.
    blocks = parse(Path(source["path"]), visual=semantic and not TEXT_ONLY, ocr=not TEXT_ONLY)
    try:
        for units, block in enumerate(blocks, 1):
            if cancelled():
                return
            if block.image and not TEXT_ONLY:
                batch.append({"id": f"{identifier}_g{INDEX_VERSION}_{ordinal}", "source_id": identifier,
                              "notebook_id": source["notebook_id"], "ordinal": ordinal,
                              "locator": block.locator, "text": '',
                              "image": json.dumps({**block.image, "digest": source["hash"]})})
                ordinal += 1
            if block.text.strip():
                for text in splitter.split_text(block.text):
                    batch.append({"id": f"{identifier}_g{INDEX_VERSION}_{ordinal}", "source_id": identifier,
                                  "notebook_id": source["notebook_id"], "ordinal": ordinal,
                                  "locator": block.locator, "text": text, "token_count": count_tokens(text)})
                    ordinal += 1
                    if len(batch) >= 256:
                        flush(batch, False)
                        batch = []
            if len(batch) >= 256:
                flush(batch, False)
                batch = []
            now = time.perf_counter()
            if now - last_report >= .25:
                last_report = now
                report(progress=int(block.progress * (30 if semantic else 95)), units=units,
                       detail=f"Reading {block.locator.lower()} · {ordinal:,} passages found")
        if batch:
            flush(batch, False)
    finally:
        blocks.close()
    if cancelled(True):
        return
    if not ordinal:
        raise ValueError("No readable text was found. Upload a document containing selectable text.")
    if semantic:
        indexed = db.one('SELECT COUNT(*) n FROM chunks WHERE source_id=? AND vector_ready=1', (identifier,))['n']
        report(status="indexing", progress=30 + int(69 * indexed / ordinal), units=units,
               detail=f"Indexing {indexed:,} of {ordinal:,} passages")
        # Modest batches keep cancellation responsive and avoid monopolizing the UI CPU.
        while indexed < ordinal:
            if cancelled(True):
                return
            rows = db.rows("""SELECT * FROM chunks WHERE source_id=? AND vector_ready=0
                ORDER BY token_count,ordinal LIMIT ?""", (identifier, EMBED_BATCH_SIZE))
            if not rows:
                raise ValueError("The import checkpoint is incomplete. Reindex this source.")
            # Commit progress after each image rather than blocking cancellation
            # behind many expensive visual inferences in a mixed batch.
            for position, row in enumerate(rows):
                if row.get('image'):
                    rows = rows[:position] if position else rows[:1]
                    break
            vectors.insert(rows)
            if cancelled(True):
                return
            connection.executemany('UPDATE chunks SET vector_ready=1 WHERE id=?', [(row['id'],) for row in rows])
            indexed += len(rows)
            report(chunks=indexed, progress=30 + int(69 * indexed / ordinal),
                   detail=f"Indexed {indexed:,} of {ordinal:,} passages · {time.perf_counter() - started:.0f}s")
    if cancelled(True):
        return
    elapsed = time.perf_counter() - started
    report(status="ready", progress=100, chunks=ordinal, units=units,
           detail=f"Ready in {elapsed:.1f}s · {ordinal:,} searchable passages")


def flush(chunks: list[dict], semantic: bool) -> None:
    if semantic:
        vectors.insert(chunks)
    with db.connect() as connection:
        connection.executemany("""INSERT INTO chunks
            (id,source_id,notebook_id,ordinal,locator,text,image,token_count)
            SELECT ?,?,?,?,?,?,?,? WHERE EXISTS (SELECT 1 FROM sources WHERE id=?)
            ON CONFLICT(id) DO UPDATE SET token_count=excluded.token_count
            WHERE chunks.token_count=0""",
                               [(row["id"], row["source_id"], row["notebook_id"], row["ordinal"],
                                 row["locator"], row["text"], row.get("image", ''), row.get('token_count', 0),
                                 row["source_id"]) for row in chunks])


def loop() -> None:
    while not _stop.is_set():
        cleanup_deleted()
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
            if not is_cancelled(source["id"]):
                update(source["id"], status="error", error=str(exc)[:500], detail="Import needs attention")
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
    update(identifier, status="queued", error="", progress=0, chunks=0, units=0, detail="Waiting to start", elapsed_seconds=0)
    _wake.set()


def delete_source(identifier: str) -> None:
    # Removing the database row cancels ingestion and hides all evidence immediately.
    # The durable queue survives restarts and cleans files after the worker releases them.
    with db.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO source_cleanup SELECT id,path FROM sources WHERE id=?",
                           (identifier,))
        connection.execute("DELETE FROM sources WHERE id=?", (identifier,))
    _wake.set()


def delete_notebook(identifier: str) -> None:
    with db.connect() as connection:
        connection.execute("INSERT OR IGNORE INTO source_cleanup SELECT id,path FROM sources WHERE notebook_id=?",
                           (identifier,))
        connection.execute("DELETE FROM notebooks WHERE id=?", (identifier,))
    _wake.set()


def cleanup_deleted() -> None:
    for source in db.rows("SELECT * FROM source_cleanup"):
        if source['id'] in _active:
            continue
        try:
            vectors.remove(source['id'])
            path = Path(source['path']).resolve()
            if path.is_relative_to((DATA / 'originals').resolve()):
                path.unlink(missing_ok=True)
            db.execute("DELETE FROM source_cleanup WHERE id=?", (source['id'],))
        except Exception:
            logger.exception("Deferred source cleanup failed for %s", source['id'])
