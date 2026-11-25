"""Stopping a running chat leaves a replayable terminal state."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.api.routes import cancel_chat_run, chat_orchestrator
from src.models.db import SemanticDatabaseModel, UserModel
from src.models.schemas import ChatCancelRequest, ChatRequest


@pytest.mark.asyncio
async def test_cancel_persists_stopped_marker_and_replays_it(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Chat", db_type="sqlite", conn_url_enc="e")
    async_session.add(database)
    await async_session.commit()
    user = await async_session.get(UserModel, 1)
    started = asyncio.Event()
    body = ChatRequest(message="Hello", client_message_id="cancel-run-1")

    async def classify(state):
        started.set()
        await asyncio.Event().wait()  # Block until cancellation lands.
        return {"intent": "out_of_scope", "chat_response": "late answer"}

    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.agents.nodes.chat.orchestrator_node.orchestrator_node", side_effect=classify),
    ):
        run = asyncio.create_task(chat_orchestrator(str(database.id), body, None, user, async_session))
        await asyncio.wait_for(started.wait(), timeout=3)
        result = await cancel_chat_run(
            str(database.id), ChatCancelRequest(client_message_id="cancel-run-1"), None, user, async_session
        )
        assert result.cancelled is True
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(run, timeout=3)

    replay = await asyncio.wait_for(
        chat_orchestrator(str(database.id), body, None, user, async_session), timeout=3
    )
    assert replay.chat_response == "Interrupted"
    assert replay.execution_trace is not None
    assert replay.execution_trace["status"] == "cancelled"

    idle = await cancel_chat_run(
        str(database.id), ChatCancelRequest(client_message_id="nothing-running"), None, user, async_session
    )
    assert idle.cancelled is False
