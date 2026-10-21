"""Reloads retain execution, persisted history, and the first session's identity."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.api.routes import chat_orchestrator
from src.models.db import ChatMessageModel, ChatSessionModel, SemanticDatabaseModel, UserModel
from src.models.schemas import ChatRequest


@pytest.mark.asyncio
async def test_reload_during_first_message_and_replay_after_completion(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Chat", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.commit()
    user = await async_session.get(UserModel, 1)
    started, finish = asyncio.Event(), asyncio.Event()
    body = ChatRequest(message="Hello", client_message_id="reload-first-message")

    async def classify(state):
        started.set()
        await finish.wait()
        return {"intent": "out_of_scope", "chat_response": "Recovered answer"}

    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.agents.nodes.orchestrator_node.orchestrator_node", side_effect=classify) as agent,
    ):
        first = asyncio.create_task(chat_orchestrator(str(database.id), body, None, user, async_session))
        await asyncio.wait_for(started.wait(), timeout=3)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        resumed = asyncio.create_task(chat_orchestrator(str(database.id), body, None, user, async_session))
        await asyncio.sleep(0)
        finish.set()
        response = await asyncio.wait_for(resumed, timeout=3)
        replay = await chat_orchestrator(str(database.id), body, None, user, async_session)
        assert response.chat_response == replay.chat_response == "Recovered answer"
        assert response.session_id == replay.session_id
        assert response.assistant_message_id == replay.assistant_message_id
        assert agent.call_count == 1

    async_session.expire_all()
    assert len((await async_session.scalars(select(ChatSessionModel))).all()) == 1
    assert len((await async_session.scalars(select(ChatMessageModel))).all()) == 2
