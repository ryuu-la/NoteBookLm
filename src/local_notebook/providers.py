import asyncio
import json
import os
import logging
import time
from contextvars import ContextVar
from functools import wraps
from urllib.parse import urlparse
from weakref import WeakKeyDictionary
from uuid import uuid4

import httpx

from . import storage as db
from .config import TEXT_ONLY

STREAM_IDLE_TIMEOUT = 60
STREAM_TOTAL_TIMEOUT = 300
STREAM_FIRST_TOKEN_TIMEOUT = 20
STREAM_RETRY_DELAY = 1
_gemini_sessions = WeakKeyDictionary()
_http_sessions = WeakKeyDictionary()
_run_settings = ContextVar('model_run_settings', default=None)


class OutputLimitError(ValueError):
    """The provider ran out of tokens before completing its output."""


class EmptyResponseError(ValueError):
    """The provider finished without usable answer content."""


def current_settings():
    return _run_settings.get() or db.settings()


def supports_images() -> bool:
    if TEXT_ONLY:
        return False
    settings = current_settings()
    # This hosted deployment rejects image_url, even though the upstream weights support vision.
    return not (settings['provider'] == 'RunInfra'
                and settings['model'] == 'deepseek-ai/DeepSeek-V4.1-Flash')


def model_run(function):
    """Keep one model throughout a run, including its concurrent child tasks."""
    @wraps(function)
    async def wrapped(*args, **kwargs):
        token = _run_settings.set(dict(current_settings()))
        try:
            return await function(*args, **kwargs)
        finally:
            _run_settings.reset(token)
    return wrapped


def compatible_client():
    """Pool connections per event loop; auth stays on each request, never on the client."""
    loop = asyncio.get_running_loop()
    if loop not in _http_sessions:
        _http_sessions[loop] = httpx.AsyncClient(timeout=90, trust_env=False)
    return _http_sessions[loop]


async def gemini_client(key: str):
    """Reuse connections per credential and loop without disrupting active streams."""
    loop = asyncio.get_running_loop()
    session = _gemini_sessions.setdefault(loop, {"lock": asyncio.Lock(), "clients": {}})
    async with session["lock"]:
        if key not in session["clients"]:
            from google import genai
            session["clients"][key] = genai.Client(api_key=key, http_options={"timeout": 90000}).aio
        return session["clients"][key]


async def close_clients():
    session = _gemini_sessions.pop(asyncio.get_running_loop(), None)
    if session:
        await asyncio.gather(*(client.aclose() for client in session["clients"].values()))
    client = _http_sessions.pop(asyncio.get_running_loop(), None)
    if client:
        await client.aclose()


def get_key(provider: str) -> str:
    """Credentials are loaded from the project .env or process environment only."""
    env_name = {"Gemini": "GEMINI_API_KEY", "RunInfra": "RUNINFRA_API_KEY"}.get(provider, "NOTEBOOK_API_KEY")
    return os.environ.get(env_name, "").strip()


def configured() -> bool:
    if os.environ.get("NOTEBOOK_OFFLINE") == "1":
        return False
    settings = current_settings()
    return bool(get_key(settings["provider"])) or settings["provider"] == "Local / compatible"


def validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query:
        raise ValueError("Use an http(s) API base URL without embedded credentials or query parameters.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote API endpoints require HTTPS. HTTP is only allowed for a local server.")
    return endpoint.rstrip("/")


async def stream(system: str, prompt: str, *, fast=False, json_mode=False, max_output_tokens=4096, on_status=None, images=None):
    if current_settings()['provider'] == 'RunInfra':
        fast = False  # A single chosen model for answers, planning and Studio.
        if json_mode:
            # Reasoning can consume the same budget as the final JSON. Small
            # recipe/planner limits otherwise leave no room for usable output.
            max_output_tokens = max(max_output_tokens, 16384)
    started, delivered = time.perf_counter(), False
    try:
        async with asyncio.timeout(STREAM_TOTAL_TIMEOUT):
            for attempt in range(2):
                iterator = _stream(system, prompt, fast=fast, json_mode=json_mode,
                                   max_output_tokens=max_output_tokens, **({'images': images} if images else {}))
                try:
                    while True:
                        timeout = min(STREAM_FIRST_TOKEN_TIMEOUT, STREAM_IDLE_TIMEOUT) if fast and not delivered else STREAM_IDLE_TIMEOUT
                        try:
                            token = await asyncio.wait_for(anext(iterator), timeout=timeout)
                        except StopAsyncIteration:
                            if not delivered:
                                raise EmptyResponseError('The model returned no answer. Try another model.')
                            return
                        if not token:
                            continue
                        if not delivered:
                            logging.getLogger(__name__).info('Generation first_text_s=%.2f attempt=%s', time.perf_counter() - started, attempt + 1)
                        delivered = True
                        yield token
                except Exception as exc:
                    code = getattr(exc, 'code', None)
                    retryable = isinstance(exc, (TimeoutError, httpx.TransportError)) or code in {500, 502, 503, 504}
                    if delivered or attempt or not retryable:
                        raise
                    message = 'Model connection interrupted. Retrying the same model once…'
                    logging.getLogger(__name__).warning('Generation retry error=%s code=%s', type(exc).__name__, code)
                    if on_status:
                        on_status(message)
                finally:
                    await iterator.aclose()
                await asyncio.sleep(STREAM_RETRY_DELAY)
    except TimeoutError as exc:
        message = ('The model stopped responding. Your partial answer is preserved.' if delivered else
                   'The model did not send any answer before the timeout. Try another model or retry this question.')
        raise TimeoutError(message) from exc


async def _stream(system: str, prompt: str, *, fast=False, json_mode=False, max_output_tokens=4096, images=None):
    if images and not supports_images():
        raise ValueError('This answer model accepts text only. Select a vision-capable model for images.')
    settings = current_settings()
    model = settings["fast_model"] if fast else settings["model"]
    key = get_key(settings["provider"])
    if settings["provider"] == "Gemini":
        if not key:
            raise ValueError("Set GEMINI_API_KEY in the project .env and restart the server to generate an answer.")
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=max_output_tokens,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json" if json_mode else "text/plain")
        if model.startswith("gemini-3") and "flash" in model:
            config.thinking_config = types.ThinkingConfig(thinking_level='minimal' if fast else settings["thinking_level"])
        client = await gemini_client(key)
        contents = prompt
        if images:
            contents = [types.Part.from_text(text=prompt)]
            for image in images:
                contents.extend([types.Part.from_text(text=f"Source evidence [{image['number']}]:"),
                                 types.Part.from_bytes(data=image['data'], mime_type=image['mime_type'])])
        response = await client.models.generate_content_stream(model=model, contents=contents, config=config)
        try:
            async for part in response:
                if part.text:
                    yield part.text
                if json_mode and any(str(c.finish_reason).endswith('MAX_TOKENS') for c in (part.candidates or [])):
                    raise OutputLimitError('The model reached its output limit before completing the result.')
        finally:
            await response.aclose()
    else:
        if settings['provider'] == 'RunInfra' and not key:
            raise ValueError('Set RUNINFRA_API_KEY in the project .env and restart the server.')
        endpoint = validate_endpoint(settings["endpoint"])
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        if settings['provider'] == 'RunInfra':
            headers['X-Client-Request-Id'] = str(uuid4())
        payload = {"model": model, "messages": [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}], "stream": True, "temperature": 0.2,
                   "max_tokens": max_output_tokens}
        if images:
            import base64
            content = [{"type": "text", "text": prompt}]
            for image in images:
                encoded = base64.b64encode(image['data']).decode('ascii')
                content.extend([{"type": "text", "text": f"Source evidence [{image['number']}]:"},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:{image['mime_type']};base64,{encoded}"}}])
            payload['messages'][1]['content'] = content
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        client = compatible_client()
        async with client.stream("POST", endpoint + "/chat/completions", json=payload,
                                 headers=headers) as response:
            if response.status_code >= 400:
                raise ValueError(f"Provider returned HTTP {response.status_code}. Check the model, key, and endpoint.")
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                item = json.loads(data)
                choices = item.get("choices", [])
                if choices:
                    token = choices[0].get("delta", {}).get("content")
                    if token:
                        yield token
                    reason = choices[0].get('finish_reason')
                    if reason:
                        logging.getLogger(__name__).info('Generation finished model=%s reason=%s', model, reason)
                    if json_mode and reason == 'length':
                        raise OutputLimitError('The model reached its output limit before completing the result.')


async def complete(system: str, prompt: str, *, on_chunk=None, **kwargs) -> str:
    parts = []
    async for part in stream(system, prompt, **kwargs):
        parts.append(part)
        if on_chunk is not None:
            on_chunk(part)
    result = "".join(parts)
    if not result.strip():
        raise EmptyResponseError("The model returned no content. Try another model or simplify the request.")
    return result
