import pytest

from local_notebook import storage as db
from local_notebook.ingestion import jobs
from local_notebook.retrieval import vectors


@pytest.fixture
def library(tmp_path, monkeypatch):
    for directory in (tmp_path / "originals", tmp_path / "vectors"):
        directory.mkdir()
    monkeypatch.setattr(db, "DATA", tmp_path)
    monkeypatch.setattr(jobs, "DATA", tmp_path)
    monkeypatch.setattr(vectors, "DATA", tmp_path)
    db.initialize()
    db.save_settings({"semantic": False, "rerank": False})
    return db.create_notebook("Test notebook")


@pytest.fixture
def indexed(library):
    source_id = jobs.add_file(library, "biology.txt", b"Photosynthesis converts light energy into chemical energy. Chlorophyll captures sunlight in chloroplasts. Plants use carbon dioxide and water to produce sugars and oxygen.")
    source = db.one("SELECT * FROM sources WHERE id=?", (source_id,))
    jobs.ingest(source)
    return library, source_id
