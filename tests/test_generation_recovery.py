import asyncio
from types import SimpleNamespace

import pytest

from local_notebook import providers, storage as db
from local_notebook.ui.common import error_text


class BusyError(Exception):
    code = 503


def test_fast_retries_same_model_before_first_token_only(library, monkeypatch):
    db.save_settings({'provider': 'Gemini'})
    calls, statuses = [], []
    async def stream(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise BusyError()
        yield 'A grounded answer [1].'
    monkeypatch.setattr(providers, '_stream', stream)
    monkeypatch.setattr(providers, 'STREAM_RETRY_DELAY', 0)
    async def consume():
        return ''.join([part async for part in providers.stream('system', 'question', fast=True, on_status=statuses.append)])
    assert asyncio.run(consume()) == 'A grounded answer [1].'
    assert len(calls) == 2 and calls[0] == calls[1]
    assert 'same model' in statuses[0]
    assert 'model_override' not in calls[0]


def test_first_token_timeout_retries_same_model(library, monkeypatch):
    db.save_settings({'provider': 'Gemini'})
    closed, calls = [], []
    async def stream(*args, **kwargs):
        calls.append(kwargs)
        try:
            if len(calls) == 1:
                await asyncio.sleep(10)
            yield 'Recovered'
        finally:
            closed.append(True)
    monkeypatch.setattr(providers, '_stream', stream)
    monkeypatch.setattr(providers, 'STREAM_FIRST_TOKEN_TIMEOUT', .01)
    monkeypatch.setattr(providers, 'STREAM_RETRY_DELAY', 0)
    async def consume():
        return ''.join([part async for part in providers.stream('s', 'q', fast=True)])
    assert asyncio.run(consume()) == 'Recovered'
    assert len(closed) == 2
    assert calls[0] == calls[1]


def test_does_not_retry_or_mix_models_after_partial_answer(monkeypatch):
    calls, received = [], []
    async def stream(*args, **kwargs):
        calls.append(True)
        yield 'Partial answer'
        raise BusyError()
    monkeypatch.setattr(providers, '_stream', stream)
    async def consume():
        async for part in providers.stream('s', 'q', fast=True):
            received.append(part)
    with pytest.raises(BusyError):
        asyncio.run(consume())
    assert received == ['Partial answer'] and len(calls) == 1


def test_fast_thinking_does_not_inherit_high(library, monkeypatch):
    db.save_settings({'provider': 'Gemini', 'fast_model': 'gemini-3.5-flash-lite', 'thinking_level': 'high'})
    configs = []
    async def generate(**kwargs):
        configs.append(kwargs['config'])
        async def chunks():
            yield SimpleNamespace(text='Answer')
        return chunks()
    async def client(key):
        return SimpleNamespace(models=SimpleNamespace(generate_content_stream=generate))
    monkeypatch.setattr(providers, 'gemini_client', client)
    monkeypatch.setattr(providers, 'get_key', lambda provider: 'fixture')
    async def consume():
        return [p async for p in providers.stream('s', 'q', fast=True)]
    assert asyncio.run(consume()) == ['Answer']
    assert configs[0].thinking_config.thinking_level.value == 'MINIMAL'
    assert db.settings()['thinking_level'] == 'high'


def test_error_reason_is_safe_and_actionable():
    assert 'busy' in error_text(BusyError('secret diagnostic URL'))
    assert 'secret' not in error_text(BusyError('secret diagnostic URL'))
    assert 'timed out' in error_text(TimeoutError('The model timed out.'))
