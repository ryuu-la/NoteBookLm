from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from .. import providers, storage as db


async def discover(query: str, engine: str) -> list[dict]:
    if not query.strip():
        raise ValueError("Enter a topic to search.")
    if engine == "Wikipedia":
        async with httpx.AsyncClient(timeout=25, trust_env=False) as client:
            response = await client.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 6},
                headers={"User-Agent": "FolioLocalNotebook/0.1 (local study application)"})
            if response.status_code >= 400:
                raise ValueError("Wikipedia search is unavailable from this connection. Use Browser search or import a public URL.")
            return [{"title": item["title"], "url": "https://en.wikipedia.org/wiki/" + quote(item["title"].replace(" ", "_")),
                     "description": BeautifulSoup(item["snippet"], "html.parser").get_text()}
                    for item in response.json()["query"]["search"]]
    key = providers.get_key("Gemini")
    if not key:
        raise ValueError("Gemini web search needs a Gemini API key. Choose Wikipedia for key-free discovery.")
    from google import genai
    from google.genai import types
    try:
        async with genai.Client(api_key=key).aio as client:
            result = await client.models.generate_content(
                model=db.settings()["fast_model"], contents=f"Find reliable public sources to study: {query}",
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
    except Exception as exc:
        if getattr(exc, "code", None) == 429:
            raise ValueError("Gemini web search quota is unavailable. Use Browser search or add a website URL directly.") from exc
        raise
    sources, seen = [], set()
    for candidate in result.candidates or []:
        metadata = candidate.grounding_metadata
        for chunk in (metadata.grounding_chunks or []) if metadata else []:
            if chunk.web and chunk.web.uri not in seen:
                seen.add(chunk.web.uri)
                sources.append({"title": chunk.web.title or "Web source", "url": chunk.web.uri,
                                "description": "Source discovered with Google Search grounding"})
    return sources[:8]
