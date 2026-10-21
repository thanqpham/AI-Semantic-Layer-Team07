"""Attach public execution traces to existing chat message metadata."""

import logging
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import ChatMessageModel
from src.models.schemas import ChatRequest, ChatResponse
from src.services.chat_execution import AGENTS, SAFE_ERROR, ChatExecution, current_execution, execution_context
from src.services.chat_service import save_chat_message

logger = logging.getLogger(__name__)


async def execute_with_trace(
    operation: Callable[[], Awaitable[ChatResponse]],
    db: AsyncSession,
    body: ChatRequest,
) -> ChatResponse:
    """Persist successful and failed executions, preserving historical replay traces."""
    execution = current_execution() or ChatExecution()
    with execution_context(execution):
        try:
            response = await operation()
        except Exception:
            execution.finish("error")
            try:
                await _persist_failure(db, body, execution)
            except Exception:
                logger.exception("Failed to persist the chat failure trace")
            raise
        if execution.replayed or response.execution_trace is not None:
            if response.execution_trace is not None:
                execution.trace = response.execution_trace
            return response
        return await _attach_trace(db, response, execution)


async def _attach_trace(db: AsyncSession, response: ChatResponse, execution: ChatExecution) -> ChatResponse:
    status = _response_status(response, execution)
    trace = execution.finish(status, response.intent)
    message = await db.get(ChatMessageModel, response.assistant_message_id)
    if message is not None:
        message.metadata_json = {
            **(message.metadata_json or {}),
            "execution_trace": trace,
            "status": "error" if status == "error" else "completed",
        }
        await db.commit()
    response.execution_trace = trace
    return response


def _response_status(response: ChatResponse, execution: ChatExecution) -> str:
    if any(
        event.get("status") == "failed"
        and (
            event.get("action") == event.get("node")
            and event.get("node") in AGENTS
            or event.get("action") in {"sql_compile", "sql_execute"}
        )
        for event in execution.trace["events"]
    ):
        return "error"
    if response.clarification is not None:
        return "needs_clarification"
    return "completed"


async def _persist_failure(
    db: AsyncSession,
    body: ChatRequest,
    execution: ChatExecution,
) -> None:
    """Save a safe failed reply only if this authorized request already saved a user message."""
    await db.rollback()
    if not execution.user_message_id:
        return
    message = await db.get(ChatMessageModel, execution.user_message_id)
    if message is not None:
        await save_chat_message(
            db,
            message.session_id,
            "assistant",
            SAFE_ERROR,
            intent="chitchat",
            metadata_json={
                "schema_version": 2,
                "status": "error",
                "error": SAFE_ERROR,
                "execution_trace": execution.snapshot(),
            },
            client_message_id=f"{body.client_message_id}:assistant" if body.client_message_id else None,
        )
