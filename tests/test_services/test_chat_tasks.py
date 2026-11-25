"""Regression coverage for browser reloads during chat execution."""

import asyncio

import pytest

from src.services.chat_tasks import cancel_chat_task, run_chat_task, start_chat_task


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


@pytest.mark.asyncio
async def test_cancel_chat_task_stops_shared_execution_and_reports_finished():
    started = asyncio.Event()

    async def agent():
        started.set()
        await asyncio.sleep(30)

    key = (1, 2, "101", "cancel-me")
    task, _ = start_chat_task(key, agent)
    await started.wait()
    assert cancel_chat_task(key) is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancel_chat_task(key) is False
