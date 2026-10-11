import asyncio
import json
from uuid import UUID

import httpx
import pytest

from local_notebook import providers, storage as db


def test_runinfra_settings_and_credentials(library, monkeypatch):
    db.save_settings({'provider': 'RunInfra', 'model': 'local-model', 'endpoint': 'http://localhost:11434/v1'})
    monkeypatch.setenv('RUNINFRA_API_KEY', 'fixture-runinfra')
    monkeypatch.setenv('NOTEBOOK_API_KEY', 'fixture-other')
    monkeypatch.delenv('NOTEBOOK_OFFLINE', raising=False)
    settings = db.settings()
    assert settings['model'] == settings['fast_model'] == 'glm-5-3-flash'
    assert settings['endpoint'] == 'https://api.runinfra.ai/v1'
    assert providers.get_key('RunInfra') == 'fixture-runinfra'
    assert providers.configured()
    db.save_settings({'provider': 'Local / compatible'})
    assert db.settings()['model'] == 'local-model'
    assert db.settings()['endpoint'] == 'http://localhost:11434/v1'


@pytest.mark.parametrize('model', ['glm-5-3-flash', 'Qwen/Qwen3.8-27B', 'deepseek-ai/DeepSeek-V4.1-Flash'])
def test_runinfra_stream_and_json_request(library, monkeypatch, model):
    db.save_settings({'provider': 'RunInfra', 'runinfra_model': model})
    monkeypatch.setenv('RUNINFRA_API_KEY', 'fixture-key')
    seen = []
    def handler(request):
        seen.append(request)
        body = 'data: ' + json.dumps({'choices': [{'delta': {'content': '{"ok":true}'}}]}) + '\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body, headers={'content-type': 'text/event-stream'})
    client_type = httpx.AsyncClient
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    async def check():
        for fast in (True, False):
            assert await providers.complete('JSON only', 'Hello', fast=fast, json_mode=True, max_output_tokens=2048) == '{"ok":true}'
    asyncio.run(check())
    for request in seen:
        assert str(request.url) == 'https://api.runinfra.ai/v1/chat/completions'
        assert request.headers['authorization'] == 'Bearer fixture-key'
        UUID(request.headers['x-client-request-id'])
        payload = json.loads(request.content)
        assert payload['model'] == model
        assert payload['stream'] and payload['max_tokens'] == 16384
        assert payload['response_format'] == {'type': 'json_object'}
    assert seen[0].headers['x-client-request-id'] != seen[1].headers['x-client-request-id']


def test_runinfra_missing_key_is_actionable(library, monkeypatch):
    db.save_settings({'provider': 'RunInfra'})
    monkeypatch.delenv('RUNINFRA_API_KEY', raising=False)
    monkeypatch.setenv('NOTEBOOK_API_KEY', 'wrong-provider')
    assert not providers.configured()
    with pytest.raises(ValueError, match='RUNINFRA_API_KEY'):
        asyncio.run(providers.complete('s', 'q'))


def test_text_only_deployment_uses_real_pdf_text_instead_of_rejected_images(library):
    from local_notebook import chat
    from local_notebook.ingestion import jobs
    from local_notebook.retrieval.search import Evidence
    db.save_settings({'provider': 'RunInfra', 'runinfra_model': 'deepseek-ai/DeepSeek-V4.1-Flash'})
    source = jobs.add_file(library, 'fixture.txt', b'Fixture')
    text = {'id': 'page-text', 'source_id': source, 'notebook_id': library,
            'ordinal': 0, 'locator': 'Page 1', 'text': 'A neural network learns from examples.'}
    visual = {**text, 'id': 'page-image', 'ordinal': 1, 'text': '', 'image': 'unused-image-reference'}
    jobs.flush([text, visual], False)
    db.execute("UPDATE sources SET status='ready' WHERE id=?", (source,))
    evidence = chat.fit_evidence(Evidence([{**visual, 'name': 'fixture'}], 'Hybrid retrieval', 0), images_supported=providers.supports_images())
    assert [p['id'] for p in evidence.passages] == ['page-text']
    assert all(not p.get('image') for p in evidence.passages)
    assert 'learns from examples' in chat.evidence_text(evidence)
    assert 'cannot inspect images' in evidence.warning
    db.execute('UPDATE sources SET selected=0 WHERE id=?', (source,))
    assert not chat.fit_evidence(Evidence([visual], 'Hybrid retrieval', 0), images_supported=False).passages


def test_text_only_deployment_never_sends_an_invalid_image_payload(library):
    db.save_settings({'provider': 'RunInfra', 'runinfra_model': 'deepseek-ai/DeepSeek-V4.1-Flash'})
    with pytest.raises(ValueError, match='accepts text only'):
        asyncio.run(providers.complete('s', 'q', images=[{'data': b'fixture'}]))


@pytest.mark.parametrize('content', ['', '{"title":"Cut off'])
def test_runinfra_detects_output_limit_even_without_answer_tokens(library, monkeypatch, content):
    db.save_settings({'provider': 'RunInfra'})
    monkeypatch.setenv('RUNINFRA_API_KEY', 'fixture-key')
    def handler(request):
        body = 'data: ' + json.dumps({'choices': [{'delta': {'content': content}, 'finish_reason': 'length'}]}) + '\n\ndata: [DONE]\n\n'
        return httpx.Response(200, text=body)
    client_type = httpx.AsyncClient
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))
    async def check():
        try:
            with pytest.raises(providers.OutputLimitError):
                await providers.complete('s', 'q', json_mode=True)
        finally:
            await providers.close_clients()
    asyncio.run(check())


def test_background_run_keeps_model_when_next_run_switches(library, monkeypatch):
    db.save_settings({'provider': 'RunInfra', 'runinfra_model': 'glm-5-3-flash'})
    monkeypatch.setenv('RUNINFRA_API_KEY', 'fixture-key')
    models = []

    def handler(request):
        models.append(json.loads(request.content)['model'])
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')

    client_type = httpx.AsyncClient
    monkeypatch.setattr(providers.httpx, 'AsyncClient', lambda **kw: client_type(transport=httpx.MockTransport(handler), **kw))

    async def check():
        started, resume = asyncio.Event(), asyncio.Event()

        @providers.model_run
        async def background():
            started.set()
            await resume.wait()
            # Child tasks and later stages must keep the original selection.
            await asyncio.gather(providers.complete('s', 'q', fast=True), providers.complete('s', 'q'))

        task = asyncio.create_task(background())
        await started.wait()
        db.save_settings({'runinfra_model': 'Qwen/Qwen3.8-27B'})
        await providers.complete('s', 'new run')
        resume.set()
        await task
        assert providers.current_settings()['model'] == 'Qwen/Qwen3.8-27B'
        await providers.close_clients()

    asyncio.run(check())
    assert models == ['Qwen/Qwen3.8-27B', 'glm-5-3-flash', 'glm-5-3-flash']
