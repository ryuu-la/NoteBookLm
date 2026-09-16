"""Measure provider first-token latency using original sample text; print no credentials."""
import asyncio
import json
import time

from local_notebook import providers, storage as db


async def main():
    results = []
    for repeat in range(2):
        for fast in (False, True):
            started, first, size = time.perf_counter(), None, 0
            try:
                async for token in providers.stream(
                    "Answer briefly using only the evidence. Cite [1].",
                    "[1] Retrieval practice means recalling an idea without looking at notes. Feedback corrects mistakes.\n"
                    "Question: What is retrieval practice?", fast=fast):
                    if first is None:
                        first = time.perf_counter() - started
                    size += len(token)
            except Exception as exc:
                print(json.dumps({"fast": fast, "provider_error_code": getattr(exc, "code", None),
                                  "error_type": type(exc).__name__}), flush=True)
                continue
            row = {"model": db.settings()["fast_model" if fast else "model"], "repeat": repeat + 1,
                   "first_token_s": round(first, 2) if first else None,
                   "total_s": round(time.perf_counter() - started, 2), "characters": size}
            results.append(row)
            print(json.dumps(row), flush=True)
    return results


if __name__ == "__main__":
    asyncio.run(main())
