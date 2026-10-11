import asyncio

import pytest

from local_notebook import agent, chat, providers, research, storage as db
from local_notebook.ingestion import jobs
from local_notebook.retrieval.workflow import is_overview, source_evidence


@pytest.mark.parametrize('question', [
    'can u create a proper learning guide here', 'Create a study plan from these sources',
    'Make a mind map and graph for learning, expand it into weeks',
])
def test_study_requests_stay_on_sources(indexed, question):
    assert is_overview(question)
    history = [{'role': 'assistant', 'text': 'Old web topic', 'citations': '[{"kind":"web"}]'}]
    for mode in ('auto', 'web', 'sources'):
        assert not research.use_web(question, mode, history, has_sources=True)
    evidence = asyncio.run(source_evidence(indexed[0], question, history))
    assert evidence.passages and evidence.diagnostics['route'] == 'overview'
    assert not research.wants_comparison(question)


def test_named_topic_does_not_turn_into_unrelated_overview():
    assert not is_overview('Create a learning guide about quantum mechanics')
    assert research.use_web('Search online for FastAPI releases', 'web', has_sources=True)
    assert not research.use_web('Search online for FastAPI releases', 'sources', has_sources=True)
    assert not research.wants_comparison('Analyze my text')
    assert research.wants_comparison('Compare the web results with my text')


def test_quick_search_reads_parallel_without_planner(library, monkeypatch):
    active, peak = 0, 0
    async def forbidden(*args, **kwargs):
        raise AssertionError('Quick research must never call the LLM planner')
    async def discover(*args):
        return [{'url': f'https://site{i}.example/article'} for i in range(7)]
    async def read(url):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.01)
        active -= 1
        return {'url': url, 'title': 'FastAPI', 'text': 'FastAPI supports dependency injection. ' * 8}
    monkeypatch.setattr(research, 'decide', forbidden)
    monkeypatch.setattr(providers, 'complete', forbidden)
    monkeypatch.setattr(research.discovery, 'discover', discover)
    monkeypatch.setattr(research, 'read_page', read)
    result = asyncio.run(research.research(library, 'Search FastAPI', [], depth='quick'))
    assert peak == 4 and len(result.passages) == 4
    assert result.diagnostics['planner_calls'] == 0
    assert result.warning == ''
    assert all(p['kind'] == 'web' for p in result.passages)


def test_quick_read_failure_keeps_good_pages(library, monkeypatch):
    async def read(url):
        if 'slow' in url:
            await asyncio.sleep(10)
        return {'url': url, 'title': 'Good', 'text': 'Supported facts. ' * 20}
    monkeypatch.setattr(research, 'QUICK_READ_TIMEOUT', .02)
    monkeypatch.setattr(research, 'read_page', read)
    evidence = asyncio.run(research.research(library, 'Read https://good.example https://slow.example', [], depth='quick'))
    assert len(evidence.passages) == 1 and evidence.diagnostics['errors']


def test_quick_compare_reads_documents_once(indexed, monkeypatch):
    calls = []
    async def retrieve(*args):
        calls.append(True)
        return await source_evidence(*args)
    async def read(url):
        return {'url': url, 'title': 'Biology', 'text': 'Photosynthesis converts light energy. ' * 10}
    monkeypatch.setattr(research, 'source_evidence', retrieve)
    monkeypatch.setattr(research, 'read_page', read)
    result = asyncio.run(research.research(indexed[0], 'Compare my text with https://biology.example', [], depth='quick'))
    assert len(calls) == 1
    assert {p['kind'] for p in result.passages} == {'document', 'web'}


def test_tools_execute_parallel_without_planning(indexed, monkeypatch):
    entered = []
    both = asyncio.Event()
    async def mark(tool):
        entered.append(tool)
        if len(entered) == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 1)
    async def mindmap(*args, **kwargs):
        await mark('mindmap')
        return {'title': 'Map', 'root': {'name': 'Topic'}, 'citations': []}
    async def data(*args):
        await mark('data')
        return {'title': 'Table', 'columns': ['Name', 'Value'], 'rows': [['A', 2]],
                'statistics': {}, 'coverage': 'Fixture', 'citations': []}
    async def forbidden(*args, **kwargs):
        raise AssertionError('No model call before explicit tools')
    monkeypatch.setattr(agent, 'generate', mindmap)
    monkeypatch.setattr(agent, 'prepare_data', data)
    monkeypatch.setattr(agent.providers, 'complete', forbidden)
    result = asyncio.run(agent.run(indexed[0], 'Create a mind map and chart from my sources'))
    assert set(entered) == {'mindmap', 'data'}
    assert len(result.outputs) == 2 and result.evidence.diagnostics['planner_calls'] == 0


def test_unselected_source_is_excluded_from_learning_guide(indexed):
    sid = jobs.add_file(indexed[0], 'private.txt', b'Unselected secret content')
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (sid,)))
    db.execute('UPDATE sources SET selected=0 WHERE id=?', (sid,))
    result = asyncio.run(source_evidence(indexed[0], 'can u create a proper learning guide here'))
    assert result.passages and all(p['source_id'] != sid for p in result.passages)


def test_prompt_does_not_request_unsolicited_comparison():
    assert 'Only when explicitly asked' in chat.SYSTEM
    assert 'Do not add unsolicited comparisons' in chat.SYSTEM


def test_compatible_connections_reused(monkeypatch):
    created, closed = [], []
    class Client:
        def __init__(self, **kwargs):
            created.append(self)
        async def aclose(self):
            closed.append(self)
    monkeypatch.setattr(providers.httpx, 'AsyncClient', Client)
    async def run():
        assert providers.compatible_client() is providers.compatible_client()
        await providers.close_clients()
    asyncio.run(run())
    assert len(created) == len(closed) == 1
