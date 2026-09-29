import asyncio
import json
import os
import logging
import time
from urllib.parse import urlparse
from weakref import WeakKeyDictionary

import httpx

from . import storage as db

STREAM_IDLE_TIMEOUT = 60
STREAM_TOTAL_TIMEOUT = 300
STREAM_FIRST_TOKEN_TIMEOUT = 20
STREAM_RETRY_DELAY = 1
_gemini_sessions = WeakKeyDictionary()


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


def get_key(provider: str) -> str:
    """Credentials are loaded from the project .env or process environment only."""
    env_name = "GEMINI_API_KEY" if provider == "Gemini" else "NOTEBOOK_API_KEY"
    return os.environ.get(env_name, "").strip()


def configured() -> bool:
    if os.environ.get("NOTEBOOK_OFFLINE") == "1":
        return False
    settings = db.settings()
    return bool(get_key(settings["provider"])) or settings["provider"] == "Local / compatible"


def validate_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.query:
        raise ValueError("Use an http(s) API base URL without embedded credentials or query parameters.")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Remote API endpoints require HTTPS. HTTP is only allowed for a local server.")
    return endpoint.rstrip("/")


async def stream(system: str, prompt: str, *, fast=False, json_mode=False, max_output_tokens=4096, on_status=None):
    started, delivered = time.perf_counter(), False
    try:
        async with asyncio.timeout(STREAM_TOTAL_TIMEOUT):
            for attempt in range(2):
                iterator = _stream(system, prompt, fast=fast, json_mode=json_mode,
                                   max_output_tokens=max_output_tokens)
                try:
                    while True:
                        timeout = min(STREAM_FIRST_TOKEN_TIMEOUT, STREAM_IDLE_TIMEOUT) if fast and not delivered else STREAM_IDLE_TIMEOUT
                        try:
                            token = await asyncio.wait_for(anext(iterator), timeout=timeout)
                        except StopAsyncIteration:
                            if not delivered:
                                raise ValueError('The model returned no answer. Try another model.')
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


async def _stream(system: str, prompt: str, *, fast=False, json_mode=False, max_output_tokens=4096):
    settings = db.settings()
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
        response = await client.models.generate_content_stream(model=model, contents=prompt, config=config)
        try:
            async for part in response:
                if part.text:
                    yield part.text
        finally:
            await response.aclose()
    else:
        endpoint = validate_endpoint(settings["endpoint"])
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {"model": model, "messages": [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}], "stream": True, "temperature": 0.2,
                   "max_tokens": max_output_tokens}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
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


async def complete(system: str, prompt: str, *, on_chunk=None, **kwargs) -> str:
    parts = []
    async for part in stream(system, prompt, **kwargs):
        parts.append(part)
        if on_chunk is not None:
            on_chunk(part)
    result = "".join(parts)
    if not result.strip():
        raise ValueError("The model returned no content. Try another model or simplify the request.")
    return result
