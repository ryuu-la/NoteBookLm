"""Regression checks for progress, cancellation, recovery, and bounded indexing."""
import pytest

from local_notebook import storage as db
from local_notebook.ingestion import jobs
from local_notebook.ingestion.parsers import Block


def prepare(library, monkeypatch, count=150):
    db.save_settings({"semantic": True})
    source = jobs.add_file(library, "progress.txt", b"Progress fixture")
    monkeypatch.setattr(jobs, "parse", lambda path: (
        Block(f"Independent passage number {n} for indexing.", f"Page {n + 1}", (n + 1) / count)
        for n in range(count)))
    # Exercise checkpoints without downloading an embedding tokenizer/model in CI.
    class Splitter:
        def split_text(self, text):
            return [text]
    monkeypatch.setattr(jobs, 'make_splitter', lambda semantic: Splitter())
    return source


def test_progress_reaches_100_only_after_all_vectors_are_written(library, monkeypatch):
    source = prepare(library, monkeypatch)
    snapshots, batches = [], []
    def insert(rows):
        snapshots.append(db.one("SELECT * FROM sources WHERE id=?", (source,)))
        batches.append([row["id"] for row in rows])
    monkeypatch.setattr(jobs.vectors, "insert", insert)
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    final = db.one("SELECT * FROM sources WHERE id=?", (source,))
    assert final["status"] == "ready" and final["progress"] == 100
    assert final["chunks"] == 150 and len({key for batch in batches for key in batch}) == 150
    assert max(map(len, batches)) <= 64
    assert all(0 < row["progress"] < 100 and row["status"] == "indexing" for row in snapshots)
    assert [row["progress"] for row in snapshots] == sorted(row["progress"] for row in snapshots)
    assert "Ready in" in final["detail"] and final["elapsed_seconds"] >= 0


def test_cancel_during_embedding_is_not_overwritten_by_batch_completion(library, monkeypatch):
    source = prepare(library, monkeypatch)
    calls = []
    def insert(rows):
        calls.append(rows)
        jobs.update(source, status="cancelled")
    monkeypatch.setattr(jobs.vectors, "insert", insert)
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    final = db.one("SELECT * FROM sources WHERE id=?", (source,))
    assert len(calls) == 1 and final["status"] == "cancelled" and final["progress"] < 100


def test_restart_resumes_committed_embedding_checkpoint(library, monkeypatch):
    source = prepare(library, monkeypatch)
    indexed = set()
    calls = 0
    def interrupt(rows):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated shutdown")
        indexed.update(row["id"] for row in rows)
    monkeypatch.setattr(jobs.vectors, "insert", interrupt)
    with pytest.raises(RuntimeError, match="shutdown"):
        jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    assert db.one("SELECT chunks FROM sources WHERE id=?", (source,))["chunks"] == 64
    db.initialize()
    resumed = []
    def finish(rows):
        resumed.extend(row["ordinal"] for row in rows)
        indexed.update(row["id"] for row in rows)
    monkeypatch.setattr(jobs.vectors, "insert", finish)
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    assert resumed == list(range(64, 150)) and len(indexed) == 150
    assert len(db.rows("SELECT * FROM chunks WHERE source_id=?", (source,))) == 150
    assert db.one("SELECT status FROM sources WHERE id=?", (source,))["status"] == "ready"


def test_empty_source_does_not_report_ready(library):
    source = jobs.add_file(library, "empty.txt", b"   \n")
    with pytest.raises(ValueError, match="No readable text"):
        jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    assert db.one("SELECT progress FROM sources WHERE id=?", (source,))["progress"] < 100


def test_embedding_chunks_preserve_tail_without_mutating_shared_tokenizer():
    from tokenizers import Tokenizer, models, pre_tokenizers
    from local_notebook.ingestion.chunking import EmbeddingSplitter
    tokenizer = Tokenizer(models.WordLevel({'[UNK]': 0}, unk_token='[UNK]'))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.enable_truncation(512)
    words = [f'record{i}' for i in range(1600)] + ['critical-tail-fact']
    text = ' '.join(words)
    splitter = EmbeddingSplitter(tokenizer)
    chunks = list(splitter.split_text(text))
    assert len(chunks) > 4 and 'critical-tail-fact' in chunks[-1]
    assert all(word in ' '.join(chunks).split() for word in words)
    assert all(len(splitter.tokenizer.encode(chunk, add_special_tokens=False).ids) <= 384 for chunk in chunks)
    assert tokenizer.truncation['max_length'] == 512


def test_old_index_checkpoint_rebuilds_with_new_chunk_boundaries(library, monkeypatch):
    source = prepare(library, monkeypatch, 90)
    db.execute('UPDATE sources SET chunks=64,index_version=0 WHERE id=?', (source,))
    ordinals = []
    monkeypatch.setattr(jobs.vectors, 'insert', lambda rows: ordinals.extend(row['ordinal'] for row in rows))
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert ordinals == list(range(90))
    assert db.one('SELECT index_version FROM sources WHERE id=?', (source,))['index_version'] == 2
