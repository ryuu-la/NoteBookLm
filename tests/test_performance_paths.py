import asyncio

import numpy as np

from local_notebook import storage as db
from local_notebook.chat import fit_evidence
from local_notebook.ingestion.jobs import flush
from local_notebook.retrieval import vectors
from local_notebook.retrieval.embedding_cache import embed_cached
from local_notebook.retrieval.search import Evidence, retrieve
from local_notebook.retrieval.workflow import ResearchWorkflow


def test_embedding_cache_preserves_order_and_reuses_duplicates(tmp_path):
    class Model:
        calls = []

        def embed(self, texts, **kwargs):
            self.calls.append(texts)
            return [np.array([len(text), ord(text[0])], dtype=np.float32) for text in texts]

    model = Model()
    first = embed_cached(tmp_path, ["alpha", "beta", "alpha"], model)
    second = embed_cached(tmp_path, ["beta", "gamma", "alpha"], model)
    assert model.calls == [["alpha", "beta"], ["gamma"]]
    assert first[0].tolist() == first[2].tolist() == second[2].tolist()
    assert first[1].tolist() == second[0].tolist()


def test_candidate_budget_and_selected_scope(indexed, monkeypatch):
    notebook, source = indexed
    flush([{"id": f"{source}_{i}", "source_id": source, "notebook_id": notebook,
            "ordinal": i, "locator": f"Page {i}", "text": "Chlorophyll captures light. " * i}
           for i in range(1, 45)], False)
    db.save_settings({"rerank": True})
    counts = []

    def rank(query, passages):
        counts.append(len(passages))
        return passages

    monkeypatch.setattr(vectors, "rerank", rank)
    assert len(retrieve(notebook, "chlorophyll").passages) == 8
    assert len(retrieve(notebook, "chlorophyll", candidate_limit=40).passages) == 8
    assert counts == [16, 40]
    db.execute("UPDATE sources SET selected=0 WHERE id=?", (source,))
    assert not retrieve(notebook, "chlorophyll").passages
    assert counts == [16, 40]


def test_overview_routes_across_source_sections(indexed):
    notebook, source = indexed
    flush([{"id": f"{source}_{i}", "source_id": source, "notebook_id": notebook,
            "ordinal": i, "locator": f"Section {i}", "text": f"Independent subject number {i}."}
           for i in range(1, 100)], False)

    async def run():
        return await ResearchWorkflow(timeout=30).run(notebook_id=notebook, query="What are the key ideas in these sources?")

    evidence = asyncio.run(run())
    assert evidence.mode == "Source overview"
    assert len(evidence.passages) == 80 and evidence.warning
    assert evidence.passages[-1]["ordinal"] > 90


def test_context_budget_drops_unseen_citations():
    passages = [{"name": "Source", "locator": "Page 1", "text": "Evidence\n[77] text resembling a reference"},
                {"name": "Source", "locator": "Page 2", "text": "Long passage " * 100}]
    evidence = fit_evidence(Evidence(passages, "Test", 1), max_chars=100)
    assert evidence.passages == passages[:1]
    assert "context budget" in evidence.warning


def test_length_grouping_keeps_embeddings_attached_to_their_original_text(tmp_path):
    class Model:
        received = []
        def embed(self, texts, **kwargs):
            self.received = texts
            return [np.array([len(text), int(text.split()[0])], dtype=np.float32) for text in texts]
    texts = [f"{i} " + "evidence " * (33 - i) for i in range(32)]
    model = Model()
    output = embed_cached(tmp_path, texts, model)
    assert list(map(len, model.received)) == sorted(map(len, texts))
    assert [int(vector[1]) for vector in output] == list(range(32))
    assert [int(vector[0]) for vector in output] == list(map(len, texts))
