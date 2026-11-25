import asyncio

from local_notebook import chat, storage as db
from local_notebook.ingestion import jobs
from local_notebook.retrieval.search import retrieve
from local_notebook.retrieval.workflow import ResearchWorkflow


def test_keyword_evidence_has_source_location(indexed):
    notebook, source = indexed
    result = retrieve(notebook, "photosynthesis")
    assert result.passages[0]["source_id"] == source
    assert "Lines" in result.passages[0]["locator"]
    assert "chemical energy" in result.passages[0]["text"]


def test_source_selection_filters_before_search(indexed):
    notebook, source = indexed
    db.execute("UPDATE sources SET selected=0 WHERE id=?", (source,))
    assert not retrieve(notebook, "photosynthesis").passages


def test_notebook_isolation(indexed):
    _, _source = indexed
    other = db.create_notebook("Separate")
    assert not retrieve(other, "photosynthesis").passages


def test_unrelated_query_has_no_lexical_evidence(indexed):
    assert not retrieve(indexed[0], "astrophysics nebula").passages


def test_import_is_idempotent(indexed):
    notebook, source = indexed
    original = db.one("SELECT * FROM sources WHERE id=?", (source,))
    from pathlib import Path
    assert jobs.add_file(notebook, "renamed.txt", Path(original["path"]).read_bytes()) == source
    assert len(db.sources(notebook)) == 1


def test_deleted_source_disappears_from_search(indexed):
    notebook, source = indexed
    jobs.delete_source(source)
    assert not retrieve(notebook, "photosynthesis").passages
    assert not db.rows("SELECT * FROM chunk_fts WHERE chunk_fts MATCH 'photosynthesis'")


def test_reindex_does_not_duplicate_chunks(indexed):
    notebook, source = indexed
    jobs.ingest(db.one("SELECT * FROM sources WHERE id=?", (source,)))
    assert len(retrieve(notebook, "photosynthesis").passages) == 1


def test_real_llamaindex_workflow(indexed):
    async def run():
        return await ResearchWorkflow(timeout=30).run(notebook_id=indexed[0], query="chlorophyll")
    assert asyncio.run(run()).passages


def test_unknown_citations_are_marked(indexed):
    evidence = retrieve(indexed[0], "photosynthesis")
    assert chat.validate_citations("Valid [1], invalid [88].", evidence) == "Valid [1], invalid [unverified reference]."
    assert len(chat.cited_passages("Claim [1] [88]", evidence)) == 1


def test_extracts_never_claim_to_be_generated(indexed):
    answer = chat.extractive_answer(retrieve(indexed[0], "photosynthesis"))
    assert "Source excerpts" in answer and "Connect a model" in answer


def test_restart_keeps_data_and_recovers_jobs(indexed):
    notebook, source = indexed
    db.execute("UPDATE sources SET status='indexing' WHERE id=?", (source,))
    db.initialize()
    assert db.sources(notebook)[0]["status"] == "queued"


def test_compound_and_comparison_queries_in_keyword_mode(library):
    sid = jobs.add_file(library, "guide.txt", b"Fixture")
    jobs.flush([
        {"id": db.uid(), "source_id": sid, "notebook_id": library, "ordinal": 0,
         "locator": "P1", "text": "FastAPI validates request bodies with Pydantic."},
        {"id": db.uid(), "source_id": sid, "notebook_id": library, "ordinal": 1,
         "locator": "P2", "text": "Decision trees split observations recursively."},
        {"id": db.uid(), "source_id": sid, "notebook_id": library, "ordinal": 2,
         "locator": "P3", "text": "Random forests aggregate many decision trees."},
    ], False)
    db.execute("UPDATE sources SET status='ready' WHERE id=?", (sid,))
    compound = retrieve(library, "How does fast api validate?")
    assert compound.passages and compound.passages[0]["locator"] == "P1"
    compared = retrieve(library, "Compare decision trees with random forests")
    locators = {p["locator"] for p in compared.passages}
    assert {"P2", "P3"} <= locators
