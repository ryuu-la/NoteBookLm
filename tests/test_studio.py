import asyncio
import json

import pytest
from pydantic import ValidationError

from local_notebook import providers, storage as db
from local_notebook.exports import artifact_markdown, export_pdf
from local_notebook.retrieval.search import retrieve
from local_notebook.studio import MindNode, Question, generate, validate_map


def test_quiz_rejects_invalid_answer():
    with pytest.raises(ValidationError):
        Question(question="Q", options=["A", "B"], answer=5, explanation="Why", citations=[1])


def test_map_requires_grounded_leaves():
    with pytest.raises(ValueError, match="supporting evidence"):
        validate_map(MindNode(name="Unsupported"), 1)


def test_map_normalizes_string_leaves_without_weakening_citations():
    node = MindNode.model_validate({'name': 'Philosophy', 'children': [
        {'name': 'Week 1', 'children': ['Calculus and Binary System [4]', 'Other topic [1, 2]']} ]})
    validate_map(node, 4)
    leaf = node.children[0].children[0]
    assert leaf.name == 'Calculus and Binary System' and leaf.citations == [4]
    assert node.children[0].children[1].citations == [1, 2]
    with pytest.raises(ValueError, match='invalid source reference'):
        validate_map(MindNode.model_validate('Invalid [99]'), 4)
    with pytest.raises(ValueError, match='supporting evidence'):
        validate_map(MindNode.model_validate('Unsupported'), 4)


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
    with pytest.raises(ValueError, match="Configure your selected provider"):
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


def test_studio_previews_stream_before_artifact_is_saved(indexed, monkeypatch):
    progress = []
    payload = json.dumps({"title": "Biology", "root": {"name": "Photosynthesis", "description": "Plants convert light energy.", "citations": [1]}})

    async def stream(*args, **kwargs):
        assert kwargs['max_output_tokens'] == 8192
        yield payload[:payload.index('description')]
        assert progress and progress[0]['items'] == ['Photosynthesis']
        assert not db.rows('SELECT * FROM artifacts WHERE notebook_id=?', (indexed[0],))
        yield payload[payload.index('description'):]

    monkeypatch.setattr(providers, 'configured', lambda: True)
    monkeypatch.setattr(providers, 'stream', stream)
    identifier = asyncio.run(generate(indexed[0], 'mindmap', retrieve(indexed[0], 'light'), 'Explain photosynthesis', on_progress=progress.append))
    artifact = db.one('SELECT * FROM artifacts WHERE id=?', (identifier,))
    assert progress[-1]['stage'] == 'complete'
    assert progress[-1]['first_token_s'] is not None
    assert 'Plants convert light energy.' in artifact_markdown(artifact)
    assert 'Photosynthesis — Plants convert light energy. [1]' in artifact_markdown(artifact)


def test_invalid_streamed_map_is_not_saved(indexed, monkeypatch):
    async def stream(*args, **kwargs):
        yield '{"title":"Invalid","root":{"name":"No evidence","citations":[99]}}'

    monkeypatch.setattr(providers, 'configured', lambda: True)
    monkeypatch.setattr(providers, 'stream', stream)
    with pytest.raises(ValueError, match='could not finish a valid mind map'):
        asyncio.run(generate(indexed[0], 'mindmap', retrieve(indexed[0], 'light'), 'Map'))
    assert not db.rows('SELECT * FROM artifacts WHERE notebook_id=?', (indexed[0],))


@pytest.mark.parametrize('kind', ['mindmap', 'quiz'])
@pytest.mark.parametrize('failure', ['truncated_json', 'output_limit', 'empty'])
def test_studio_recovers_incomplete_output_before_saving(indexed, monkeypatch, kind, failure):
    valid = ({'title': 'Biology', 'root': {'name': 'Photosynthesis', 'citations': [1]}}
             if kind == 'mindmap' else {'title': 'Biology', 'questions': [{'question': 'What captures light?',
                 'options': ['Chlorophyll', 'Sand'], 'answer': 0, 'explanation': 'Chlorophyll captures light.', 'citations': [1]}]})
    calls, events = [], []
    async def complete(system, prompt, **kwargs):
        calls.append(kwargs)
        assert 'No Markdown' in system
        assert not db.rows('SELECT * FROM artifacts WHERE notebook_id=?', (indexed[0],))
        if len(calls) == 1:
            if failure == 'output_limit':
                raise providers.OutputLimitError('Output limit')
            if failure == 'empty':
                raise providers.EmptyResponseError('No answer')
            return '{"title":"Biology","root":{"name":"Photosyn'
        assert 'COMPLETE valid JSON' in prompt
        return json.dumps(valid)
    monkeypatch.setattr(providers, 'configured', lambda: True)
    monkeypatch.setattr(providers, 'complete', complete)
    identifier = asyncio.run(generate(indexed[0], kind, retrieve(indexed[0], 'light'), 'Study', on_progress=events.append))
    assert len(calls) == 2 and calls[1]['max_output_tokens'] > calls[0]['max_output_tokens']
    assert any(event['stage'] == 'retrying' for event in events)
    assert db.one('SELECT kind FROM artifacts WHERE id=?', (identifier,))['kind'] == kind
    assert len(db.rows('SELECT * FROM artifacts WHERE notebook_id=?', (indexed[0],))) == 1


def test_studio_stops_after_one_recovery_and_hides_parser_error(indexed, monkeypatch):
    calls = []
    async def complete(*args, **kwargs):
        calls.append(1)
        return '{"title":"Unterminated'
    monkeypatch.setattr(providers, 'configured', lambda: True)
    monkeypatch.setattr(providers, 'complete', complete)
    with pytest.raises(ValueError, match='No incomplete result was saved') as error:
        asyncio.run(generate(indexed[0], 'mindmap', retrieve(indexed[0], 'light'), 'Map'))
    assert 'Unterminated' not in str(error.value)
    assert len(calls) == 2
    assert not db.rows('SELECT * FROM artifacts WHERE notebook_id=?', (indexed[0],))


def test_invalid_json_preview_does_not_abort_stream(indexed, monkeypatch):
    calls = []
    async def stream(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            yield r'{"title":"Bad draft","root":{"name":"Bad\q label","citations":[1]}}'
        else:
            yield '{"title":"Biology","root":{"name":"Photosynthesis","citations":[1]}}'
    monkeypatch.setattr(providers, 'configured', lambda: True)
    monkeypatch.setattr(providers, 'stream', stream)
    events = []
    result = asyncio.run(generate(indexed[0], 'mindmap', retrieve(indexed[0], 'light'), 'Map', on_progress=events.append))
    assert len(calls) == 2
    assert db.one('SELECT id FROM artifacts WHERE id=?', (result,))


def test_gemini_connections_are_reused_and_closed(monkeypatch):
    from google import genai
    created, closed = [], []

    class Client:
        def __init__(self, **kwargs):
            self.aio = self
            created.append(self)

        async def aclose(self):
            closed.append(self)

    monkeypatch.setattr(genai, 'Client', Client)

    async def exercise():
        first, second = await asyncio.gather(providers.gemini_client('fixture-one'), providers.gemini_client('fixture-one'))
        assert first is second
        different = await providers.gemini_client('fixture-two')
        assert different is not first
        assert not closed  # key changes must not kill another active request
        await providers.close_clients()

    asyncio.run(exercise())
    assert len(created) == 2 and closed == created
