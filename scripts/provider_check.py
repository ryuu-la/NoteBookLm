import asyncio
import json
from pathlib import Path

from local_notebook import providers, storage as db


async def check():
    settings = db.settings()
    result = {"provider": settings["provider"], "model": settings["model"]}
    if not providers.configured():
        result["status"] = "No configured provider; live inference not tested"
    else:
        try:
            response = await providers.complete("Reply with OK only.", "Connection test for the local notebook app.")
            result.update(status="connected", response_characters=len(response))
        except Exception as exc:
            result.update(status="failed", error_type=type(exc).__name__)
            if hasattr(exc, "code"):
                result["http_status"] = exc.code
            if hasattr(exc, "message"):
                message = str(exc.message)
                key = providers.get_key(settings["provider"])
                result["message"] = message.replace(key, "[redacted]") if key else message
    Path("test-results/provider.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


asyncio.run(check())
