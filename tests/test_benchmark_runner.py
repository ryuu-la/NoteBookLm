"""Exercise live-evaluation control flow using a fake provider, without API access."""
import asyncio
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_notebook import providers, storage as db
from local_notebook.ingestion import jobs


@pytest.mark.parametrize('refuses', [True, False])
def test_live_benchmark_calls_generator_for_empty_evidence_and_gates_refusals(indexed, tmp_path, monkeypatch, refuses):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / 'benchmarks'))
    # run_path sets these variables; register them with monkeypatch for restoration.
    monkeypatch.setenv('NOTEBOOK_DATA_DIR', str(tmp_path))
    monkeypatch.setenv('NOTEBOOK_MODEL_DIR', str(tmp_path / 'models'))
    runner = runpy.run_path(str(root / 'benchmarks/rag.py'))['run']
    book, source = indexed
    other = jobs.add_file(book, 'archive.txt', b'Archive shelves contain boxes organized by accession number.')
    jobs.ingest(db.one('SELECT * FROM sources WHERE id=?', (other,)))
    locator = db.one('SELECT locator FROM chunks WHERE source_id=?', (source,))['locator']
    monkeypatch.setitem(runner.__globals__, 'seed', lambda *args, **kwargs: (book, 2))
    monkeypatch.setitem(runner.__globals__, 'CASES', [
        {'id': 'answerable', 'question': 'What does photosynthesis do?', 'history': [],
         'relevant': [locator], 'reference': 'Photosynthesis converts light energy into chemical energy.'},
        {'id': 'unknown', 'question': 'What is the orbital period of Neptune?', 'history': [],
         'relevant': [], 'reference': 'The selected sources do not provide this information.'},
    ])
    calls = []

    async def complete(system, prompt, **kwargs):
        negative = 'Neptune' in prompt
        calls.append((bool(kwargs.get('json_mode')), negative))
        if kwargs.get('json_mode'):
            # Even an overgenerous correctness verdict must not bypass the refusal gate.
            return json.dumps({'correct': True, 'completeness': 1,
                               'abstains': refuses if negative else False, 'reason': 'Test judge',
                               'claims': [] if negative else [{
                                   'claim': 'Photosynthesis converts light energy into chemical energy.',
                                   'supported': True, 'citation': 1,
                                   'quote': 'Photosynthesis converts light energy into chemical energy.'}]})
        if negative:
            return 'The sources do not provide this information.' if refuses else 'Neptune takes 165 years.'
        return 'Photosynthesis converts light energy into chemical energy [1].'

    async def close():
        pass

    monkeypatch.setattr(providers, 'configured', lambda: True)
    monkeypatch.setattr(providers, 'complete', complete)
    monkeypatch.setattr(providers, 'close_clients', close)
    target = tmp_path / 'report.json'
    args = SimpleNamespace(answers=True, keyword=True, provider='Local / compatible', model='generator',
                           judge_model='judge', allow_self_judge=False, endpoint='http://localhost:1/v1',
                           request_interval=0, output=str(target))
    if refuses:
        asyncio.run(runner(args))
    else:
        with pytest.raises(SystemExit, match='gates failed'):
            asyncio.run(runner(args))
    report = json.loads(target.read_text(encoding='utf-8'))
    assert calls == [(False, False), (True, False), (False, True), (True, True)]
    assert report['cases'][1]['answer_origin'] == 'model'
    assert report['summary']['abstention_accuracy'] == 1  # Retrieval rejected the question in both cases.
    assert report['summary']['model_abstention_accuracy'] == int(refuses)
    assert report['passed'] is refuses
