import asyncio

import pytest

from local_notebook import chat, storage as db
from local_notebook.evaluation import AnswerJudgment, ClaimJudgment, audit_judgment, require_retrieval_mode, retrieval_metrics
from local_notebook.ingestion import jobs
from local_notebook.retrieval import vectors
from local_notebook.retrieval.search import Evidence, coverage, retrieve
from local_notebook.retrieval.workflow import ResearchWorkflow, contextual_query, is_overview


def run(book, question, history=()):
    async def query():
        return await ResearchWorkflow(timeout=30).run(notebook_id=book, query=question, history=list(history))
    return asyncio.run(query())


def test_explicit_topic_after_overview_searches_full_index(library):
    sid = jobs.add_file(library, 'course.txt', b'Fixture')
    chunks = [{'id': db.uid(), 'source_id': sid, 'notebook_id': library, 'ordinal': i,
               'locator': str(i), 'text': f'Unrelated archive entry {i}.'} for i in range(200)]
    chunks[119]['text'] = 'FastAPI Depends provides dependency injection and request validation.'
    jobs.flush(chunks, False)
    db.execute("UPDATE sources SET status='ready' WHERE id=?", (sid,))
    result = run(library, 'anything more about fast api',
                 [{'role': 'user', 'text': 'What are the key ideas in these sources?'}])
    assert result.diagnostics['route'] == 'targeted'
    assert result.diagnostics['indexed_passages'] == 200
    assert result.passages[0]['id'] == chunks[119]['id']
    assert 'overview' not in result.warning.casefold()


def test_references_inherit_topic_but_named_topics_do_not():
    history = [{'role': 'user', 'text': 'Explain FastAPI dependencies'}]
    assert 'FastAPI' in contextual_query('How does it clean up?', history)
    assert 'FastAPI' in contextual_query('Tell me more', history)
    assert contextual_query('Explain random forests', history) == 'Explain random forests'
    assert not is_overview('Summarize the FastAPI dependency system')
    assert is_overview('What are the key ideas in these sources?')


def test_overview_includes_small_later_source_and_real_ordinals(library):
    for name, ordinals in [('big', [2, 50, 101, 200, 900]), ('small', [33])]:
        sid = jobs.add_file(library, name + '.txt', name.encode())
        jobs.flush([{'id': db.uid(), 'source_id': sid, 'notebook_id': library, 'ordinal': i,
                     'locator': str(i), 'text': f'{name} topic at section {i}'} for i in ordinals], False)
        db.execute("UPDATE sources SET status='ready' WHERE id=?", (sid,))
    result = coverage(library, 4)
    assert len(result.passages) == 4
    assert len({p['source_id'] for p in result.passages}) == 2
    assert result.passages[1]['name'] == 'small.txt'
    assert result.diagnostics['indexed_passages'] == 6


def test_context_skips_oversize_but_preserves_exact_citation_mapping():
    passages = [{'id': str(i), 'name': 'notes', 'locator': str(i), 'text': text}
                for i, text in enumerate(['x' * 1000, 'A supported fact.', 'Another fact.'])]
    evidence = chat.fit_evidence(Evidence(passages, 'test', 0), max_chars=120)
    assert [p['id'] for p in evidence.passages] == ['1', '2']
    prompt = chat.evidence_text(evidence)
    assert '[1] notes' in prompt and 'A supported fact.' in prompt
    assert chat.cited_passages('First fact [1]', evidence)[0]['id'] == '1'


def test_weak_semantic_neighbors_do_not_force_an_answer(indexed, monkeypatch):
    db.save_settings({'semantic': True, 'rerank': True})
    rows = db.rows('SELECT id FROM chunks')
    monkeypatch.setattr(vectors, 'search', lambda *args: [r['id'] for r in rows])
    monkeypatch.setattr(vectors, 'rerank', lambda q, ps: [{**p, 'relevance_score': -11} for p in ps])
    assert not retrieve(indexed[0], 'Neptune orbital period').passages


def test_answer_audit_does_not_confuse_valid_ids_with_support():
    evidence = Evidence([{'text': 'Pydantic validates request fields.'}], 'test', 0)
    judgment = AnswerJudgment(correct=False, completeness=0, abstains=False, reason='Unsupported detail', claims=[
        ClaimJudgment(claim='Pydantic validates fields.', supported=True, citation=1, quote='Pydantic validates request fields.'),
        ClaimJudgment(claim='It guarantees security.', supported=True, citation=1, quote='guarantees security')])
    result = audit_judgment(judgment, 'Fields are validated [1]. Security is guaranteed [1] [99].', evidence)
    assert result['supported_claim_fraction'] == .5
    assert result['invalid_citations'] == [99]
    assert result['citation_validity'] < 1


def test_grouped_citations_resolve_and_invalid_members_are_marked():
    evidence = Evidence([{'id': 'a', 'text': 'first'}, {'id': 'b', 'text': 'second'}], 'test', 0)
    text = chat.validate_citations('Supported [1, 2], invalid [2, 88].', evidence)
    assert text == 'Supported [1] [2], invalid [2] [unverified reference].'
    assert len(chat.cited_passages('Facts [1, 2]', evidence)) == 2


def test_contradictory_judge_verdict_requires_review():
    evidence = Evidence([{'text': 'A transaction rolls back incomplete changes.'}], 'test', 0)
    judgment = AnswerJudgment(correct=False, completeness=1, abstains=False,
                              reason='The answer is supported and complete.', claims=[
        ClaimJudgment(claim='Incomplete changes roll back.', supported=True, citation=1,
                      quote='A transaction rolls back incomplete changes.')])
    assert audit_judgment(judgment, 'Incomplete changes roll back [1].', evidence)['needs_review']


def test_positive_judge_verdict_with_unverifiable_quote_requires_review():
    evidence = Evidence([{'text': 'Pydantic validates fields. Invalid data produces an error.'}], 'test', 0)
    judgment = AnswerJudgment(correct=True, completeness=1, abstains=False, reason='Supported', claims=[
        ClaimJudgment(claim='Pydantic validates fields and errors on invalid data.', supported=True,
                      citation=1, quote='Pydantic validates fields. [...] produces an error.')])
    result = audit_judgment(judgment, 'Pydantic validates fields and errors on invalid data [1].', evidence)
    assert result['correct'] is True  # Preserve the raw judge verdict; do not rewrite it.
    assert result['supported_claim_fraction'] == 0
    assert result['needs_review'] and result['review_reasons']


def test_positive_verdict_with_unsupported_claim_requires_review():
    judgment = AnswerJudgment(correct=True, completeness=1, abstains=False, reason='Wrong verdict', claims=[
        ClaimJudgment(claim='Invented fact', supported=False)])
    assert audit_judgment(judgment, 'Invented fact [1]', Evidence([{'text': 'Other fact'}], 'test', 0))['needs_review']


@pytest.mark.parametrize('mode,warning', [
    ('Keyword search', 'Semantic search is unavailable.'),
    ('Keyword search', ''),
    ('Hybrid retrieval', 'Reranker unavailable.'),
    ('No indexed sources', ''),
])
def test_benchmarks_refuse_silent_or_reported_fallback(mode, warning):
    with pytest.raises(RuntimeError):
        require_retrieval_mode(Evidence([], mode, 1, warning), semantic=True)


def test_benchmark_allows_clean_hybrid_rejection():
    require_retrieval_mode(Evidence([], 'Hybrid retrieval + reranker', 1), semantic=True, rerank=True)


def test_ranking_metrics_count_unique_evidence_and_negatives():
    assert retrieval_metrics(['a', 'a'], ['a', 'b'])['recall_at_8'] == .5
    assert retrieval_metrics([], [])['abstained']
    assert retrieval_metrics(['a'], [])['recall_at_8'] is None


def test_overview_context_budget_preserves_end_and_middle_sections():
    passages = [{'name': 'Book', 'locator': f'Page {i}', 'text': 'Evidence ' * 100, 'ordinal': i}
                for i in range(80)]
    result = chat.fit_evidence(Evidence(passages, 'Source overview', 0), max_chars=5000)
    ordinals = [p['ordinal'] for p in result.passages]
    assert 0 in ordinals and 79 in ordinals
    assert any(30 < n < 50 for n in ordinals)
    assert ordinals == sorted(ordinals)
