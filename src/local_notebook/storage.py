import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4

from .config import DATA, RUNINFRA_MODELS, INDEX_VERSION, gemini_models, prepare


def uid() -> str:
    return uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(DATA / "notebook.db", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize() -> None:
    prepare()
    with connect() as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS notebooks (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT DEFAULT '',
            icon TEXT DEFAULT 'auto_stories', color TEXT DEFAULT 'blue',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            name TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL, hash TEXT NOT NULL,
            url TEXT DEFAULT '', status TEXT DEFAULT 'queued', progress INTEGER DEFAULT 0,
            units INTEGER DEFAULT 0, chunks INTEGER DEFAULT 0, error TEXT DEFAULT '',
            selected INTEGER DEFAULT 1, created_at TEXT NOT NULL,
            UNIQUE(notebook_id, hash));
        CREATE TABLE IF NOT EXISTS chunks (
            id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            notebook_id TEXT NOT NULL, ordinal INTEGER NOT NULL, locator TEXT NOT NULL, text TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS chunks_source ON chunks(source_id, ordinal);
        CREATE INDEX IF NOT EXISTS sources_notebook ON sources(notebook_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
            text, content='chunks', content_rowid='rowid', tokenize='unicode61');
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunk_fts(rowid,text) VALUES(new.rowid,new.text); END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunk_fts(chunk_fts,rowid,text) VALUES('delete',old.rowid,old.text); END;
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            role TEXT NOT NULL, text TEXT NOT NULL, citations TEXT DEFAULT '[]', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, notebook_id TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
            kind TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL,
            citations TEXT DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS message_blocks (
            message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            content TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS message_runs (
            message_id TEXT PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
            content TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_cleanup (id TEXT PRIMARY KEY, path TEXT NOT NULL);
        PRAGMA user_version=3;
        """)
        columns = {row[1] for row in db.execute("PRAGMA table_info(sources)")}
        for name, declaration in {"detail": "TEXT DEFAULT ''", "elapsed_seconds": "REAL DEFAULT 0",
                                  "index_version": "INTEGER DEFAULT 0"}.items():
            if name not in columns:
                db.execute(f"ALTER TABLE sources ADD COLUMN {name} {declaration}")
        chunk_columns = {row[1] for row in db.execute("PRAGMA table_info(chunks)")}
        if "image" not in chunk_columns:
            db.execute("ALTER TABLE chunks ADD COLUMN image TEXT NOT NULL DEFAULT ''")
        if "vector_ready" not in chunk_columns:
            db.execute("ALTER TABLE chunks ADD COLUMN vector_ready INTEGER NOT NULL DEFAULT 0")
            # Previous versions committed vectors in ordinal order. Preserve those
            # checkpoints when switching to length-grouped batches.
            db.execute("""UPDATE chunks SET vector_ready=1 WHERE EXISTS (
                SELECT 1 FROM sources s WHERE s.id=chunks.source_id
                AND s.index_version=? AND chunks.ordinal<s.chunks)""", (INDEX_VERSION,))
        if "token_count" not in chunk_columns:
            db.execute("ALTER TABLE chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0")
        db.execute("CREATE INDEX IF NOT EXISTS chunks_pending_tokens ON chunks(source_id,vector_ready,token_count,ordinal)")
        db.execute("DROP INDEX IF EXISTS chunks_pending")
        if "detail" not in columns:
            # Older imports used a different PDF extractor and interleaved checkpoints.
            db.execute("UPDATE sources SET chunks=0, progress=0 WHERE status IN ('queued','parsing','indexing')")
        db.execute("UPDATE sources SET status='queued', error='' WHERE status IN ('parsing','indexing')")
        db.execute("DELETE FROM settings WHERE key IN ('api_key', 'fallback_model')")
        db.execute("DELETE FROM settings WHERE key IN ('rerank', 'rerank_candidates')")
        semantic = db.execute("SELECT value FROM settings WHERE key='semantic'").fetchone()
        if semantic is None or json.loads(semantic[0]):
            # Old vectors cannot be queried with the new model. Preserve originals,
            # chat and citation snapshots; the worker rebuilds each source once.
            db.execute("""UPDATE sources SET status='queued', chunks=0, progress=0,
                error='', detail='Updating the search index for EmbeddingGemma 2'
                WHERE status='ready' AND index_version!=?""", (INDEX_VERSION,))
        db.execute("PRAGMA user_version=3")


def rows(sql: str, args=()) -> list[dict]:
    with connect() as db:
        return [dict(row) for row in db.execute(sql, args).fetchall()]


def one(sql: str, args=()) -> dict | None:
    result = rows(sql, args)
    return result[0] if result else None


def execute(sql: str, args=()) -> None:
    with connect() as db:
        db.execute(sql, args)


def notebooks() -> list[dict]:
    return rows("""SELECT n.*, COUNT(s.id) AS source_count FROM notebooks n
        LEFT JOIN sources s ON s.notebook_id=n.id GROUP BY n.id ORDER BY n.updated_at DESC""")


def create_notebook(title="Untitled notebook", description="", icon="auto_stories", color="blue") -> str:
    identifier = uid()
    execute("INSERT INTO notebooks VALUES (?,?,?,?,?,?,?)",
            (identifier, title, description, icon, color, now(), now()))
    return identifier


def touch(notebook_id: str) -> None:
    execute("UPDATE notebooks SET updated_at=? WHERE id=?", (now(), notebook_id))


def sources(notebook_id: str) -> list[dict]:
    return rows("SELECT * FROM sources WHERE notebook_id=? ORDER BY created_at", (notebook_id,))


def messages(notebook_id: str) -> list[dict]:
    return rows("SELECT * FROM messages WHERE notebook_id=? ORDER BY created_at", (notebook_id,))


def add_message(notebook_id: str, role: str, text: str, citations=()) -> str:
    identifier = uid()
    execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
            (identifier, notebook_id, role, text, json.dumps(list(citations)), now()))
    touch(notebook_id)
    return identifier


def replace_turn(notebook_id: str, user_id: str, question: str, answer: str, citations=()) -> str:
    """Commit an edited/retried branch only after an answer is available."""
    with connect() as connection:
        history = connection.execute(
            "SELECT id,role FROM messages WHERE notebook_id=? ORDER BY created_at", (notebook_id,)
        ).fetchall()
        index = next((i for i, row in enumerate(history) if row["id"] == user_id and row["role"] == "user"), None)
        if index is None:
            raise ValueError("This question is no longer in the notebook. Reload and try again.")
        connection.executemany("DELETE FROM messages WHERE id=? AND notebook_id=?",
                               [(row["id"], notebook_id) for row in history[index + 1:]])
        connection.execute("UPDATE messages SET text=? WHERE id=? AND notebook_id=?", (question, user_id, notebook_id))
        timestamp = now()
        identifier = uid()
        connection.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
                           (identifier, notebook_id, "assistant", answer, json.dumps(list(citations)), timestamp))
        connection.execute("UPDATE notebooks SET updated_at=? WHERE id=?", (timestamp, notebook_id))
        return identifier


def save_artifact(notebook_id: str, kind: str, title: str, content: str, citations=()) -> str:
    identifier = uid()
    execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)",
            (identifier, notebook_id, kind, title, content, json.dumps(list(citations)), now(), now()))
    touch(notebook_id)
    return identifier


def settings() -> dict:
    defaults = {"provider": "Gemini", "model": "gemini-3.8-flash",
                "fast_model": "gemini-3.5-flash-lite", "endpoint": "http://localhost:11434/v1",
                "semantic": True, "thinking_level": "minimal", "studio_fast": True}
    defaults.update({row["key"]: json.loads(row["value"]) for row in rows("SELECT * FROM settings")})
    defaults.pop("fallback_model", None)
    defaults.pop("api_key", None)
    defaults.pop("rerank", None)
    defaults.pop("rerank_candidates", None)
    if defaults["provider"] == "Gemini":
        defaults.update(gemini_models())
    elif defaults['provider'] == 'RunInfra':
        selected = defaults.get('runinfra_model', 'glm-5-3-flash')
        if selected not in RUNINFRA_MODELS:
            selected = 'glm-5-3-flash'
        defaults.update(runinfra_model=selected, model=selected, fast_model=selected,
                        studio_fast=False, endpoint='https://api.runinfra.ai/v1')
    return defaults


def save_settings(values: dict) -> None:
    with connect() as db:
        db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)",
                       [(key, json.dumps(value)) for key, value in values.items()
                        if key not in {"api_key", "fallback_model", "rerank", "rerank_candidates"}])
