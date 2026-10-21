"""Regression coverage for browser reloads during chat execution."""

import asyncio

import pytest

from src.services.chat_tasks import run_chat_task


@pytest.mark.asyncio
async def test_disconnect_and_retry_keep_one_agent_execution():
    started, finish = asyncio.Event(), asyncio.Event()
    calls = 0

    async def agent():
        nonlocal calls
        calls += 1
        started.set()
        await finish.wait()
        return "persisted answer"

    key = (1, 2, "101", "client-message")
    original = asyncio.create_task(run_chat_task(key, agent))
    await started.wait()
    original.cancel()
    with pytest.raises(asyncio.CancelledError):
        await original
    resumed = asyncio.create_task(run_chat_task(key, agent))
    await asyncio.sleep(0)
    finish.set()
    assert await resumed == "persisted answer"
    assert calls == 1
