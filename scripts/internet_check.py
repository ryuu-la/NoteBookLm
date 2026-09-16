import asyncio
import json
from pathlib import Path

from local_notebook.ingestion.discovery import discover
from local_notebook.ingestion.web import fetch
from local_notebook import providers


async def main():
    results = {}
    try:
        name, data, url = await asyncio.to_thread(fetch, "https://www.python.org/about/")
        results["public_url"] = {"status": "passed", "title": name, "bytes": len(data), "url": url}
    except Exception as exc:
        results["public_url"] = {"status": "failed", "error": type(exc).__name__}
    for engine in ["Wikipedia", "Gemini web search"]:
        try:
            items = await discover("retrieval augmented generation", engine)
            results[engine] = {"status": "passed" if items else "empty", "results": len(items)}
        except Exception as exc:
            results[engine] = {"status": "failed", "error": type(exc).__name__}
            if hasattr(exc, "code"):
                results[engine]["http_status"] = exc.code
                key = providers.get_key("Gemini")
                results[engine]["message"] = str(exc.message).replace(key, "[redacted]") if key else str(exc.message)
            elif hasattr(exc, "response"):
                results[engine]["http_status"] = exc.response.status_code
                results[engine]["message"] = exc.response.text[:300]
            elif hasattr(exc, "message"):
                key = providers.get_key("Gemini")
                results[engine]["message"] = str(exc.message).replace(key, "[redacted]") if key else str(exc.message)
    try:
        response = await providers.complete("Reply OK only.", "Connection test", fast=True)
        results["fast_model"] = {"status": "passed", "response_characters": len(response)}
    except Exception as exc:
        results["fast_model"] = {"status": "failed", "error": type(exc).__name__}
    Path("test-results/internet.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


asyncio.run(main())
