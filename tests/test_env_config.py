import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from local_notebook import config, providers, storage as db


def test_env_file_overrides_inherited_credentials_including_blank_key(tmp_path, monkeypatch):
    env = tmp_path / '.env'
    env.write_text('GEMINI_API_KEY=fixture-file-key\nGEMINI_MAIN_MODEL=gemini-3.8-flash\n', encoding='utf-8')
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-inherited-key')
    monkeypatch.delenv('GEMINI_MAIN_MODEL', raising=False)
    config.load_environment(env)
    assert providers.get_key('Gemini') == 'fixture-file-key'
    assert config.gemini_models()['model'] == 'gemini-3.8-flash'
    env.write_text('GEMINI_API_KEY=\n', encoding='utf-8')
    config.load_environment(env)
    assert providers.get_key('Gemini') == ''


def test_credentials_never_fall_back_to_legacy_store(monkeypatch):
    def forbidden(*args):
        raise AssertionError('Legacy credential store must not be accessed')
    monkeypatch.setitem(sys.modules, 'keyring', SimpleNamespace(get_password=forbidden))
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    assert providers.get_key('Gemini') == ''


def test_env_models_override_stale_database_and_drop_legacy_settings(library, monkeypatch):
    monkeypatch.setenv('GEMINI_FAST_MODEL', 'gemini-3.5-flash-lite')
    monkeypatch.setenv('GEMINI_MAIN_MODEL', 'gemini-3.8-flash')
    for key, value in {'model': 'obsolete-model', 'fast_model': 'obsolete-model',
                       'fallback_model': 'obsolete-backup', 'api_key': 'obsolete-secret'}.items():
        db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
    settings = db.settings()
    assert settings['model'] == 'gemini-3.8-flash'
    assert settings['fast_model'] == 'gemini-3.5-flash-lite'
    assert 'api_key' not in settings and 'fallback_model' not in settings
    db.initialize()
    assert not db.rows("SELECT * FROM settings WHERE key IN ('api_key','fallback_model')")
    db.save_settings({'api_key': 'fixture-secret', 'fallback_model': 'obsolete-backup'})
    assert not db.rows("SELECT * FROM settings WHERE key IN ('api_key','fallback_model')")


def test_gemini_rejects_models_outside_configured_pair(monkeypatch):
    monkeypatch.setenv('GEMINI_FAST_MODEL', 'obsolete-model')
    with pytest.raises(ValueError, match='GEMINI_FAST_MODEL'):
        config.gemini_models()


def test_unavailable_model_is_not_retried_or_replaced(monkeypatch):
    class MissingModel(Exception):
        code = 404
    calls = []
    async def stream(*args, **kwargs):
        calls.append(kwargs)
        raise MissingModel()
        yield  # pragma: no cover
    monkeypatch.setattr(providers, '_stream', stream)
    async def consume():
        return [part async for part in providers.stream('s', 'q', fast=True)]
    with pytest.raises(MissingModel):
        asyncio.run(consume())
    assert len(calls) == 1
