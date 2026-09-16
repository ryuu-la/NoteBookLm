import asyncio
import json

import pytest
from pydantic import ValidationError

from local_notebook import providers, storage as db
from local_notebook.exports import export_pdf
from local_notebook.retrieval.search import retrieve
from local_notebook.studio import MindNode, Question, generate, validate_map


def test_quiz_rejects_invalid_answer():
    with pytest.raises(ValidationError):
        Question(question="Q", options=["A", "B"], answer=5, explanation="Why", citations=[1])


def test_map_requires_grounded_leaves():
    with pytest.raises(ValueError, match="supporting evidence"):
        validate_map(MindNode(name="Unsupported"), 1)


def test_generation_saves_validated_quiz(indexed, monkeypatch):
    async def complete(*args, **kwargs):
        return json.dumps({"title": "Biology quiz", "questions": [{"question": "What captures light?",
             "options": ["Chlorophyll", "Sand"], "answer": 0, "explanation": "The source says chlorophyll captures sunlight.", "citations": [1]}]})
    monkeypatch.setattr(providers, "configured", lambda: True)
    monkeypatch.setattr(providers, "complete", complete)
    identifier = asyncio.run(generate(indexed[0], "quiz", retrieve(indexed[0], "chlorophyll"), "One question"))
    artifact = db.one("SELECT * FROM artifacts WHERE id=?", (identifier,))
    assert artifact["kind"] == "quiz" and len(json.loads(artifact["citations"])) == 1


def test_generation_refuses_missing_provider(indexed, monkeypatch):
    monkeypatch.setattr(providers, "configured", lambda: False)
    with pytest.raises(ValueError, match="Connect Gemini"):
        asyncio.run(generate(indexed[0], "quiz", retrieve(indexed[0], "light"), "Quiz"))


def test_pdf_is_readable_and_has_multiple_pages(tmp_path):
    from pypdf import PdfReader
    path = tmp_path / "notes.pdf"
    path.write_bytes(export_pdf("Notes – learning", "# Key ideas\n\n" + "Spaced practice with feedback improves understanding.\n" * 100))
    reader = PdfReader(path)
    assert len(reader.pages) > 1
    assert "Spaced practice" in reader.pages[0].extract_text()


def test_endpoint_disallows_credentials_and_insecure_remote():
    with pytest.raises(ValueError):
        providers.validate_endpoint("http://example.com/v1")
    with pytest.raises(ValueError):
        providers.validate_endpoint("https://secret@example.com/v1")
    assert providers.validate_endpoint("http://localhost:11434/v1/") == "http://localhost:11434/v1"
