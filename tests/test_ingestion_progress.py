"""Regression checks for progress, cancellation, recovery, and bounded indexing."""
import pytest

from local_notebook import storage as db
from local_notebook.ingestion import jobs
from local_notebook.ingestion.parsers import Block


def prepare(library, monkeypatch, count=150):
    db.save_settings({"semantic": True})
    source = jobs.add_file(library, "progress.txt", b"Progress fixture")
    monkeypatch.setattr(jobs, "parse", lambda path, **kwargs: (
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
    assert max(map(len, batches)) <= jobs.EMBED_BATCH_SIZE
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


def test_visual_cancellation_stops_before_processing_later_images(library, monkeypatch, multimodal):
    source = prepare(library, monkeypatch)
    monkeypatch.setattr(jobs, 'parse', lambda path, **kwargs: (
        Block('', f'Image {i}', i / 3, {'path': str(path), 'frame': i}) for i in range(3)))
    images = []
    def insert(rows):
        images.extend(row for row in rows if row.get('image'))
        jobs.update(source, status='cancelled')
    monkeypatch.setattr(jobs.vectors, 'insert', insert)
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert len(images) == 1
    assert db.one('SELECT status FROM sources WHERE id=?', (source,))['status'] == 'cancelled'


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
    assert db.one("SELECT chunks FROM sources WHERE id=?", (source,))["chunks"] == jobs.EMBED_BATCH_SIZE
    db.initialize()
    resumed = []
    def finish(rows):
        resumed.extend(row["ordinal"] for row in rows)
        indexed.update(row["id"] for row in rows)
    monkeypatch.setattr(jobs.vectors, "insert", finish)
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    assert resumed == list(range(jobs.EMBED_BATCH_SIZE, 150)) and len(indexed) == 150
    assert len(db.rows("SELECT * FROM chunks WHERE source_id=?", (source,))) == 150
    assert db.one("SELECT status FROM sources WHERE id=?", (source,))["status"] == "ready"


def test_empty_source_does_not_report_ready(library):
    source = jobs.add_file(library, "empty.txt", b"   \n")
    with pytest.raises(ValueError, match="No readable text"):
        jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    assert db.one("SELECT progress FROM sources WHERE id=?", (source,))["progress"] < 100


def test_batches_follow_tokens_not_character_length_and_preserve_checkpoints(library, monkeypatch):
    source = prepare(library, monkeypatch, 20)
    texts = ['word ' * (25 - i) for i in range(20)]
    counts = {text: i + 1 for i, text in enumerate(texts)}

    class Splitter:
        def split_text(self, text):
            return [text]

        def token_count(self, text):
            return counts[text]

    monkeypatch.setattr(jobs, 'make_splitter', lambda semantic: Splitter())
    monkeypatch.setattr(jobs, 'parse', lambda path, **kwargs: (
        Block(text, f'Page {i + 1}', (i + 1) / 20) for i, text in enumerate(texts)))
    completed = []

    def interrupted(rows):
        if completed:
            raise RuntimeError('interrupted')
        completed.extend(row['ordinal'] for row in rows)

    monkeypatch.setattr(jobs.vectors, 'insert', interrupted)
    with pytest.raises(RuntimeError, match='interrupted'):
        jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert completed == list(range(jobs.EMBED_BATCH_SIZE))
    # A pre-migration checkpoint has no token lengths yet. Re-parsing backfills
    # lengths while retaining committed vectors and original source locations.
    db.execute('UPDATE chunks SET token_count=0 WHERE source_id=?', (source,))
    db.initialize()
    monkeypatch.setattr(jobs.vectors, 'insert', lambda rows: completed.extend(r['ordinal'] for r in rows))
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert completed == list(range(20))
    rows = db.rows('SELECT * FROM chunks WHERE source_id=? ORDER BY ordinal', (source,))
    assert [r['token_count'] for r in rows] == list(range(1, 21))
    assert [r['text'] for r in rows] == texts
    assert all(r['vector_ready'] for r in rows)


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
    assert len(chunks) >= 4 and 'critical-tail-fact' in chunks[-1]
    assert all(word in ' '.join(chunks).split() for word in words)
    assert all(len(splitter.tokenizer.encode(chunk, add_special_tokens=False).ids) <= 512 for chunk in chunks)
    assert all(splitter.token_count(chunk) <= 512 for chunk in chunks)
    assert tokenizer.truncation['max_length'] == 512


def test_old_index_checkpoint_rebuilds_with_new_chunk_boundaries(library, monkeypatch):
    source = prepare(library, monkeypatch, 90)
    db.execute('UPDATE sources SET chunks=64,index_version=0 WHERE id=?', (source,))
    ordinals = []
    monkeypatch.setattr(jobs.vectors, 'insert', lambda rows: ordinals.extend(row['ordinal'] for row in rows))
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert ordinals == list(range(90))
    assert db.one('SELECT index_version FROM sources WHERE id=?', (source,))['index_version'] == jobs.INDEX_VERSION


def test_delete_during_embedding_is_immediate_and_cleans_after_worker(library, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from threading import Event

    source = prepare(library, monkeypatch)
    original = db.one('SELECT * FROM sources WHERE id=?', (source,))
    entered, release = Event(), Event()
    removed = []
    def insert(rows):
        entered.set()
        assert release.wait(5)
    monkeypatch.setattr(jobs.vectors, 'insert', insert)
    monkeypatch.setattr(jobs.vectors, 'remove', removed.append)
    jobs._active.add(source)
    try:
        with ThreadPoolExecutor() as pool:
            task = pool.submit(jobs.ingest, original)
            try:
                assert entered.wait(5)
                jobs.delete_source(source)
                assert not db.one('SELECT * FROM sources WHERE id=?', (source,))
                assert not db.rows('SELECT * FROM chunks WHERE source_id=?', (source,))
                jobs.cleanup_deleted()
                assert Path(original['path']).exists()
                assert db.one('SELECT * FROM source_cleanup WHERE id=?', (source,))
            finally:
                release.set()
            task.result(timeout=5)
    finally:
        jobs._active.discard(source)
    jobs.cleanup_deleted()
    assert not Path(original['path']).exists()
    assert not db.rows('SELECT * FROM source_cleanup')
    assert removed[-1] == source


def test_delete_notebook_cancels_all_sources_and_cleanup_survives_restart(library, monkeypatch):
    from pathlib import Path

    first = prepare(library, monkeypatch)
    second = jobs.add_file(library, 'other.txt', b'Another import')
    originals = [Path(s['path']) for s in db.sources(library)]
    db.execute("UPDATE sources SET status='indexing' WHERE id=?", (first,))
    db.add_message(library, 'user', 'A saved question')
    monkeypatch.setattr(jobs.vectors, 'remove', lambda identifier: None)
    jobs.delete_notebook(library)
    assert not db.one('SELECT * FROM notebooks WHERE id=?', (library,))
    assert not db.sources(library) and not db.messages(library)
    db.initialize()
    assert {s['id'] for s in db.rows('SELECT * FROM source_cleanup')} == {first, second}
    jobs.cleanup_deleted()
    assert all(not p.exists() for p in originals)


def test_late_parser_flush_cannot_recreate_deleted_source(library):
    source = jobs.add_file(library, 'late.txt', b'Late parser')
    jobs.delete_source(source)
    jobs.flush([{'id': 'late', 'source_id': source, 'notebook_id': library,
                 'ordinal': 0, 'locator': 'Page 1', 'text': 'Late parser result'}], False)
    assert not db.rows('SELECT * FROM chunks')


def test_length_grouped_batches_resume_without_skipping_original_locations(library, monkeypatch):
    source = prepare(library, monkeypatch, 30)
    monkeypatch.setattr(jobs, 'parse', lambda path, **kwargs: (
        Block(('Long content. ' * (31 - n)) if n % 2 else 'Short.', f'Page {n}', (n + 1) / 30)
        for n in range(30)))
    completed = []
    def interrupt(rows):
        if completed:
            raise RuntimeError('restart after noncontiguous batch')
        completed.extend(row['ordinal'] for row in rows)
    monkeypatch.setattr(jobs.vectors, 'insert', interrupt)
    with pytest.raises(RuntimeError, match='restart'):
        jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert completed == list(range(0, 16, 2))
    db.initialize()
    def finish(rows):
        completed.extend(row['ordinal'] for row in rows)
    monkeypatch.setattr(jobs.vectors, 'insert', finish)
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (source,)))
    assert sorted(completed) == list(range(30))
    assert db.one('SELECT chunks,status FROM sources WHERE id=?', (source,)) == {'chunks': 30, 'status': 'ready'}
