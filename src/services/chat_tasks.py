"""Keep chat execution alive across browser disconnects and coalesce retries."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from src.services.chat_execution import ChatExecution, execution_context

T = TypeVar("T")
# shortcut: tasks live in one worker; use a shared job queue before enabling multiple workers.
_tasks: dict[tuple[int, int | None, str, str], asyncio.Task] = {}
_executions: dict[tuple[int, int | None, str, str], ChatExecution] = {}


async def run_chat_task(key: tuple[int, int | None, str, str], operation: Callable[[], Awaitable[T]]) -> T:
    """Await a shared task without letting a disconnected request cancel it."""
    task, _ = start_chat_task(key, operation)
    return await asyncio.shield(task)


def start_chat_task(
    key: tuple[int, int | None, str, str], operation: Callable[[], Awaitable[T]]
) -> tuple[asyncio.Task[T], ChatExecution]:
    """Get the same task and trace for JSON calls and streaming reconnects."""
    if key not in _tasks:
        execution = ChatExecution()

        async def execute() -> T:
            with execution_context(execution):
                return await operation()

        _executions[key] = execution
        _tasks[key] = asyncio.create_task(execute())
        _tasks[key].add_done_callback(lambda done: _finish_task(key, done))
    return _tasks[key], _executions[key]


def _finish_task(key: tuple[int, int | None, str, str], task: asyncio.Task) -> None:
    _executions[key].changed.set()
    _tasks.pop(key, None)
    _executions.pop(key, None)
    if not task.cancelled():
        task.exception()  # Retrieve failures even when the browser has disconnected.
