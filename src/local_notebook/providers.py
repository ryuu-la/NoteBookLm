import json
import os
from urllib.parse import urlparse

import httpx

from . import storage as db

_keys: dict[str, str] = {}


def set_key(provider: str, value: str, remember=False) -> None:
    import keyring
    _keys[provider] = value.strip()
    if remember:
        keyring.set_password("local-notebook", provider, value.strip())
    else:
        try:
            keyring.delete_password("local-notebook", provider)
        except keyring.errors.PasswordDeleteError:
            pass


def get_key(provider: str) -> str:
    if provider in _keys:
        return _keys[provider]
    env_name = "GEMINI_API_KEY" if provider == "Gemini" else "NOTEBOOK_API_KEY"
    if os.environ.get(env_name):
        return os.environ[env_name]
    try:
        import keyring
        return keyring.get_password("local-notebook", provider) or ""
    except Exception:
        return ""


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


async def stream(system: str, prompt: str, *, fast=False, json_mode=False):
    settings = db.settings()
    model = settings["fast_model"] if fast else settings["model"]
    key = get_key(settings["provider"])
    if settings["provider"] == "Gemini":
        if not key:
            raise ValueError("Add your Gemini API key in Settings to generate an answer.")
        from google import genai
        from google.genai import types
        config = types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=4096,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            response_mime_type="application/json" if json_mode else "text/plain")
        if model.startswith("gemini-3") and "flash" in model:
            config.thinking_config = types.ThinkingConfig(thinking_level=settings["thinking_level"])
        async with genai.Client(api_key=key, http_options={"timeout": 90000}).aio as client:
            response = await client.models.generate_content_stream(model=model, contents=prompt, config=config)
            async for part in response:
                if part.text:
                    yield part.text
    else:
        endpoint = validate_endpoint(settings["endpoint"])
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        payload = {"model": model, "messages": [{"role": "system", "content": system},
                    {"role": "user", "content": prompt}], "stream": True, "temperature": 0.2,
                   "max_tokens": 8192}
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


async def complete(system: str, prompt: str, **kwargs) -> str:
    parts = []
    async for part in stream(system, prompt, **kwargs):
        parts.append(part)
    result = "".join(parts)
    if not result.strip():
        raise ValueError("The model returned no content. Try another model or simplify the request.")
    return result
