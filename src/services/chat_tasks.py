"""Keep chat execution alive across browser disconnects and coalesce retries."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")
# shortcut: tasks live in one worker; use a shared job queue before enabling multiple workers.
_tasks: dict[tuple[int, int | None, str, str], asyncio.Task] = {}


async def run_chat_task(key: tuple[int, int | None, str, str], operation: Callable[[], Awaitable[T]]) -> T:
    """Await a shared task without letting a disconnected request cancel it."""
    task = _tasks.get(key)
    if task is None:
        task = asyncio.create_task(operation())
        _tasks[key] = task
        task.add_done_callback(lambda done: _finish_task(key, done))
    return await asyncio.shield(task)


def _finish_task(key: tuple[int, int | None, str, str], task: asyncio.Task) -> None:
    _tasks.pop(key, None)
    if not task.cancelled():
        task.exception()  # Retrieve failures even when the browser has disconnected.
