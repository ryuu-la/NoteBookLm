import asyncio
import json

import pytest

from local_notebook import chat, research, storage as db
from local_notebook.ingestion import jobs, web_reader
from local_notebook.retrieval.search import Evidence


@pytest.mark.parametrize('question,expected', [
    ('Search online for more physics sources', True),
    ('Find articles about resonance', True),
    ('Read https://example.org/article', True),
    ('Explain the uploaded physics chapter', False),
    ('Do not search online, use my sources', False),
])
def test_request_routing(question, expected):
    assert research.wants_web(question) is expected


def test_mode_and_followup_routing():
    history = [{'role': 'assistant', 'text': 'Resonance', 'citations': json.dumps([{'kind': 'web'}])}]
    assert research.use_web('Explain resonance', 'web')
    assert not research.use_web('Search online', 'sources')
    assert research.use_web('Tell me more about that', history=history)
    assert not research.use_web('Explain only my sources', history=history)
    assert not research.use_web('Explain photosynthesis', history=history)


def page(url, links=()):
    return {'url': url, 'title': 'Resonance physics', 'text':
            'Resonance particles decay rapidly. Their lifetimes relate to resonance widths. ' * 12,
            'links': list(links)}


def test_agent_search_read_follow_refine_without_index(library, monkeypatch):
    actions = iter([
        {'action': 'search', 'query': 'particle physics resonances'},
        {'action': 'read', 'ids': [1]},
        {'action': 'read', 'ids': [2]},
        {'action': 'search', 'query': 'resonance width lifetime relation'},
        {'action': 'read', 'ids': [3]},
        {'action': 'answer', 'coverage': ''},
    ])
    states, reads, queries = [], [], []

    async def decide(state):
        states.append(state)
        return next(actions)

    async def search(query, progress):
        queries.append(query)
        return [{'url': 'https://physics.example/' + str(len(queries)), 'title': 'Physics'}], []

    async def read(url):
        reads.append(url)
        return page(url, [{'url': 'https://physics.example/details', 'title': 'Lifetime details'}])

    monkeypatch.setattr(research, 'decide', decide)
    monkeypatch.setattr(research, 'search_web', search)
    monkeypatch.setattr(research, 'read_page', read)
    result = asyncio.run(research.research(library, 'Search online about these particles',
                         [{'role': 'assistant', 'text': 'Short-lived resonance particles'}]))
    assert len(reads) == 3
    assert reads[1].endswith('/details')
    assert len(queries) == 2
    assert len(result.passages) == 3
    assert result.diagnostics['indexed_passages'] == 0
    assert not db.sources(library)
    assert not db.rows('SELECT * FROM chunks')
    assert states[-1]['read_pages']
    citations = chat.cited_passages('Measured widths [1] [2].', result)
    assert len(citations) == 2
    assert all('text' not in item and item['kind'] == 'web' for item in citations)
    assert chat.citation_target(citations[0]).startswith('https://physics.example/')


def test_search_falls_back_without_using_snippets(monkeypatch):
    engines = []

    async def discover(query, engine):
        engines.append(engine)
        if engine == 'DuckDuckGo':
            raise ValueError('Unavailable')
        return [{'url': 'https://physics.example', 'description': 'unverified snippet'}]

    monkeypatch.setattr(research.discovery, 'discover', discover)
    found, errors = asyncio.run(research.search_web('physics', lambda text: None))
    assert found and errors
    assert engines == ['DuckDuckGo', 'Multi-engine']


def test_failed_reads_do_not_become_evidence(library, monkeypatch):
    async def decide(state):
        return {'action': 'read', 'ids': [1]} if state['candidates'] else {'action': 'answer'}

    async def fail(url):
        raise ValueError('Unreadable')

    monkeypatch.setattr(research, 'decide', decide)
    monkeypatch.setattr(research, 'read_page', fail)
    monkeypatch.setattr(research, 'MAX_SEARCHES', 0)
    with pytest.raises(ValueError, match='could not read relevant pages'):
        asyncio.run(research.research(library, 'Read https://physics.example', []))
    assert not db.sources(library)


def test_cancellation_interrupts_reading(library, monkeypatch):
    async def decide(state):
        return {'action': 'read', 'ids': [1]}

    entered = asyncio.Event()
    stopped = []

    async def read(url):
        entered.set()
        try:
            await asyncio.sleep(100)
        finally:
            stopped.append(True)

    async def run():
        task = asyncio.create_task(research.research(library, 'Read https://physics.example', []))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    monkeypatch.setattr(research, 'decide', decide)
    monkeypatch.setattr(research, 'read_page', read)
    asyncio.run(run())
    assert stopped and not db.sources(library)


def test_repeated_search_and_page_budget(library, monkeypatch):
    decisions = []

    async def decide(state):
        decisions.append(state)
        return {'action': 'search', 'query': 'same query'}

    searches = []

    async def search(query, progress):
        searches.append(query)
        return [], []

    monkeypatch.setattr(research, 'decide', decide)
    monkeypatch.setattr(research, 'search_web', search)
    with pytest.raises(ValueError):
        asyncio.run(research.research(library, 'Search online', []))
    assert len(searches) == 1
    assert len(decisions) == research.MAX_STEPS


def test_citation_urls_and_page_extraction():
    citation = {'kind': 'web', 'url': 'https://example.org/Resonance_(physics)', 'id': 'web1'}
    assert chat.citation_target(citation).endswith('Resonance_%28physics%29')
    assert chat.citation_target({**citation, 'url': 'javascript:alert(1)'}) == '#'
    assert chat.citation_target({'id': 'local1'}) == '/evidence/local1'
    data = b'<html><title>Physics</title><nav>Ignore me</nav><main><p>' + b'Resonance physics. ' * 20
    data += b'</p><a href="/details">Read details</a><a href="javascript:alert(1)">Bad</a></main></html>'
    result = web_reader.extract(data, 'https://physics.example/start', 'text/html')
    assert 'Ignore me' not in result['text']
    assert result['links'] == [{'url': 'https://physics.example/details', 'title': 'Read details',
                               'description': 'Linked from Physics'}]


def test_reader_rejects_private_urls():
    with pytest.raises(ValueError, match='public'):
        asyncio.run(web_reader.read_page('http://127.0.0.1/secret'))


def test_agent_combines_selected_documents_and_web(library, monkeypatch):
    selected = jobs.add_file(library, 'Philosophy.txt', b'Eastern philosophy emphasizes ethical cultivation and meditation. Western philosophy emphasizes logical argument. ' * 5)
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (selected,)))
    excluded = jobs.add_file(library, 'Unselected.txt', b'Eastern philosophy secret unrelated document. ' * 5)
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (excluded,)))
    db.execute('UPDATE sources SET selected=0 WHERE id=?', (excluded,))
    before = db.sources(library)
    states = []

    async def decide(state):
        states.append(state)
        if not state['searches']:
            return {'action': 'search', 'query': 'Eastern philosophy ethics'}
        if not state['read_pages']:
            return {'action': 'read', 'ids': [1]}
        return {'action': 'answer'}

    async def search(query, progress):
        return [{'url': 'https://philosophy.example/ethics', 'title': 'Eastern ethics'}], []

    async def read(url):
        return {'url': url, 'title': 'Eastern ethics', 'text': 'Eastern ethics emphasizes self cultivation and compassion. ' * 10, 'links': []}

    monkeypatch.setattr(research, 'decide', decide)
    monkeypatch.setattr(research, 'search_web', search)
    monkeypatch.setattr(research, 'read_page', read)
    result = asyncio.run(research.research(library, 'Search Eastern philosophy and compare with our text', []))
    assert states[0]['document_evidence']
    assert {p['kind'] for p in result.passages} == {'document', 'web'}
    assert all(p['source_id'] != excluded for p in result.passages)
    assert db.sources(library) == before
    assert len(db.sources(library)) == 2
    assert 'NOTEBOOK DOCUMENT' in chat.evidence_text(result) and 'WEBSITE' in chat.evidence_text(result)
    web_number = next(i for i, p in enumerate(result.passages, 1) if p['kind'] == 'web')
    assert chat.missing_comparison_citations(f'Web only [{web_number}]', result)
    assert not chat.missing_comparison_citations(f'Document [1], website [{web_number}].', result)


def test_context_budget_preserves_both_evidence_types():
    docs = [{'id': str(i), 'name': 'Doc', 'locator': 'Page 1', 'kind': 'document', 'text': 'd' * 25000} for i in range(12)]
    web = [{'id': 'web' + str(i), 'name': 'Site', 'locator': 'URL', 'kind': 'web', 'text': 'w' * 25000} for i in range(8)]
    result = research.combine_evidence(docs, web)
    assert {p['kind'] for p in result} == {'document', 'web'}
    assert sum(len(p['text']) for p in result) < 30000


def test_document_tool_can_refine_an_empty_search(library, monkeypatch):
    sid = jobs.add_file(library, 'Philosophy.txt', b'Fixture')
    db.execute("UPDATE sources SET status='ready' WHERE id=?", (sid,))
    queries = []

    async def retrieve(book, query):
        queries.append(query)
        passages = [] if len(queries) == 1 else [{'id': 'fixture', 'name': 'Philosophy', 'locator': 'Page 1',
                                                 'text': 'Eastern philosophy concerns ethics.', 'source_id': sid}]
        return Evidence(passages, 'Documents', 0)

    async def decide(state):
        if not state['document_evidence']:
            return {'action': 'retrieve', 'query': 'Eastern philosophy ethics'}
        return {'action': 'answer'}

    monkeypatch.setattr(research, 'retrieve_documents', retrieve)
    monkeypatch.setattr(research, 'decide', decide)
    result = asyncio.run(research.research(library, 'Explain our text on easter philosphy', []))
    assert len(queries) == 2
    assert result.passages[0]['kind'] == 'document'
