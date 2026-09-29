import asyncio

import pytest

from local_notebook import chat, providers, storage as db
from local_notebook.retrieval.search import Evidence


def test_edit_commits_one_branch_and_preserves_other_notebooks(library):
    first = db.add_message(library, "user", "Original question")
    db.add_message(library, "assistant", "Old answer")
    db.add_message(library, "user", "Later question")
    other = db.create_notebook("Other notebook")
    db.add_message(other, "user", "Leave this alone")
    db.replace_turn(library, first, "Edited question", "New answer", [{"number": 1}])
    history = db.messages(library)
    assert [(row["role"], row["text"]) for row in history] == [
        ("user", "Edited question"), ("assistant", "New answer")]
    assert history[0]["id"] == first
    assert db.messages(other)[0]["text"] == "Leave this alone"


def test_invalid_retry_does_not_delete_any_history(library):
    db.add_message(library, "user", "Keep question")
    assistant = db.add_message(library, "assistant", "Keep answer")
    before = db.messages(library)
    with pytest.raises(ValueError):
        db.replace_turn(library, assistant, "Wrong target", "New answer")
    assert db.messages(library) == before


def test_retry_prompt_excludes_future_and_replaced_answer(library):
    db.add_message(library, "user", "Original question")
    db.add_message(library, "assistant", "Outdated answer")
    db.add_message(library, "user", "Future question")
    prompt = chat.prompt(library, "Edited question", Evidence([], "test", 0),
                         history=[{"role": "user", "text": "Edited question"}])
    assert "Edited question" in prompt
    assert "Outdated answer" not in prompt and "Future question" not in prompt


def test_stream_timeout_keeps_delivered_tokens_and_closes_provider(monkeypatch):
    closed, received = [], []

    async def stalled(*args, **kwargs):
        try:
            yield "Visible partial answer"
            await asyncio.sleep(10)
        finally:
            closed.append(True)

    monkeypatch.setattr(providers, "_stream", stalled)
    monkeypatch.setattr(providers, "STREAM_IDLE_TIMEOUT", .03)

    async def consume():
        async for token in providers.stream("system", "question"):
            received.append(token)

    with pytest.raises(TimeoutError, match="stopped responding"):
        asyncio.run(consume())
    assert received == ["Visible partial answer"] and closed == [True]
