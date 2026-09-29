"""Authored regression judgments: chat routing, full-index lookup, scope and rejection.

Separate from the older study-notes ranking benchmark. Not an external/held-out test set.
"""

TOPICS = [
    ('fastapi', 'FastAPI', 'FastAPI validates request bodies using Pydantic models and generates OpenAPI documentation. Async path operations can await nonblocking I/O. Blocking I/O must not run directly on the event loop.'),
    ('flask', 'Flask', 'Flask is a Python web framework with a small core. Extensions supply features such as database integration. A Flask application registers routes with decorators.'),
    ('dependencies', 'FastAPI dependencies', 'FastAPI Depends injects reusable dependencies into path operations. A dependency can validate an authentication token or provide a database session. Dependencies with yield can clean up resources after use.'),
    ('validation', 'Input validation', 'Pydantic validates typed request fields in FastAPI. Invalid request data produces a validation error response. Type annotations describe the expected request shape.'),
    ('async', 'Asynchronous execution', 'An async FastAPI endpoint can await I/O without blocking the event loop. CPU-heavy tasks still occupy a CPU and should be moved to a worker when necessary. Async does not automatically make CPU-heavy work faster.'),
    ('transactions', 'Transactions', 'Database transaction atomicity means all changes succeed together or roll back. A rollback discards incomplete changes. Committed data is preserved under the durability guarantees.'),
    ('trees', 'Decision trees', 'Decision trees recursively split observations by feature tests. Maximum depth and minimum leaf size limit complexity. Pruning can reduce overfitting.'),
    ('forest', 'Random forests', 'A random forest combines decision trees using averaging or voting. Bootstrap samples and random feature subsets diversify trees. Aggregation often reduces variance relative to a single tree.'),
]

OVERVIEW_HISTORY = [{'role': 'user', 'text': 'What are the key ideas in these sources?'},
                    {'role': 'assistant', 'text': 'The sources cover web APIs, databases, and learning methods.'}]

CASES = [
    {'id': 'reported-fast-api-followup', 'question': 'anything more about fast api', 'history': OVERVIEW_HISTORY,
     'relevant': ['fastapi', 'dependencies', 'validation', 'async'], 'category': 'explicit follow-up',
     'reference': 'FastAPI uses Pydantic validation, generates OpenAPI documentation, and supports async I/O and dependency injection.'},
    {'id': 'topic-after-overview', 'question': 'Explain database transactions', 'history': OVERVIEW_HISTORY,
     'relevant': ['transactions'], 'category': 'explicit follow-up', 'reference': 'Transaction atomicity means all changes succeed or roll back.'},
    {'id': 'named-overview', 'question': 'Summarize the FastAPI dependency system', 'history': [],
     'relevant': ['dependencies'], 'category': 'topic summary', 'reference': 'Depends injects reusable dependencies; yield dependencies can release resources.'},
    {'id': 'compound-name', 'question': 'How does fast api validate requests?', 'history': [],
     'relevant': ['validation'], 'category': 'compound name', 'reference': 'FastAPI uses Pydantic to validate request fields.'},
    {'id': 'paraphrase', 'question': 'How can incomplete database changes be discarded together?', 'history': [],
     'relevant': ['transactions'], 'category': 'paraphrase', 'reference': 'A transaction rollback discards incomplete changes as a unit.'},
    {'id': 'reference-followup', 'question': 'How does it handle cleanup?',
     'history': [{'role': 'user', 'text': 'Explain FastAPI dependencies'}], 'relevant': ['dependencies'],
     'category': 'referential follow-up', 'reference': 'Dependencies with yield can clean up resources.'},
    {'id': 'generic-followup', 'question': 'Tell me more',
     'history': [{'role': 'user', 'text': 'Explain database transactions'}], 'relevant': ['transactions'],
     'category': 'referential follow-up', 'reference': 'Transactions ensure atomic changes and allow rollback.'},
    {'id': 'new-topic', 'question': 'Explain decision tree pruning',
     'history': [{'role': 'user', 'text': 'Explain FastAPI dependencies'}], 'relevant': ['trees'],
     'category': 'topic switch', 'reference': 'Pruning reduces tree complexity and can reduce overfitting.'},
    {'id': 'comparison', 'question': 'Compare decision trees and random forests', 'history': [],
     'relevant': ['trees', 'forest'], 'category': 'multi-source comparison',
     'reference': 'A tree uses feature splits; a forest aggregates varied trees to reduce variance.'},
    {'id': 'async-limits', 'question': 'Does async make CPU-heavy FastAPI work faster?', 'history': [],
     'relevant': ['async'], 'category': 'limitation', 'reference': 'No. Async helps nonblocking I/O; CPU-heavy work may need a worker.'},
    {'id': 'unknown', 'question': 'What is the orbital period of Neptune?', 'history': [],
     'relevant': [], 'category': 'unanswerable', 'reference': 'The selected sources do not provide this information.'},
    {'id': 'unknown-after-overview', 'question': 'anything about medieval pottery glazes', 'history': OVERVIEW_HISTORY,
     'relevant': [], 'category': 'unanswerable', 'reference': 'The selected sources do not provide this information.'},
]


def seed(db, jobs, *, semantic):
    """Insert 8 topic passages and 240 repetitive archive distractors, bypassing parsing.

    This fixture checks regressions and scope, not diverse long-document accuracy.
    """
    book = db.create_notebook('RAG evaluation')
    sources = [jobs.add_file(book, f'Authored evaluation {i}.txt', f'Fixture source {i}'.encode()) for i in range(2)]
    chunks = []
    for i in range(240):
        sid = sources[i % 2]
        chunks.append({'id': db.uid(), 'source_id': sid, 'notebook_id': book, 'ordinal': i,
                       'locator': f'distractor-{i}',
                       'text': f'Archive entry {i}. This section catalogs shelves, storage boxes, and document dates. The collection is organized by accession number.'})
    for i, (identifier, title, text) in enumerate(TOPICS):
        # Non-contiguous ordinals are intentional; coverage must use actual IDs.
        sid = sources[i % 2]
        chunks.append({'id': db.uid(), 'source_id': sid, 'notebook_id': book, 'ordinal': 19 + i * 24,
                       'locator': identifier, 'text': title + '\n' + text})
    jobs.flush(chunks, semantic)
    for sid in sources:
        db.execute("UPDATE sources SET status='ready', chunks=? WHERE id=?",
                   (sum(c['source_id'] == sid for c in chunks), sid))
    # Strong matches outside the notebook and deselected sources must never leak.
    other = db.create_notebook('Private evaluation scope')
    forbidden = jobs.add_file(other, 'Forbidden.txt', b'outside fixture')
    disabled = jobs.add_file(book, 'Disabled.txt', b'disabled fixture')
    private = [{'id': db.uid(), 'source_id': sid, 'notebook_id': bid, 'ordinal': 0,
                'locator': 'forbidden', 'text': TOPICS[0][2] + ' PRIVATE CANARY'}
               for sid, bid in [(forbidden, other), (disabled, book)]]
    jobs.flush(private, semantic)
    db.execute("UPDATE sources SET status='ready',selected=0 WHERE id=?", (disabled,))
    db.execute("UPDATE sources SET status='ready' WHERE id=?", (forbidden,))
    return book, len(chunks)
