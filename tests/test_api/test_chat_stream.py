"""Streaming authorization, trace persistence, replay, and safe failure replies."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from src.api import routes
from src.api.auth import create_access_token
from src.models.db import ChatMessageModel, SemanticDatabaseModel, UserModel
from src.models.schemas import ChatResponse
from src.services.chat_execution import execution_step
from src.services.chat_service import create_chat_session, save_chat_message


@pytest.fixture
async def chat_database(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Trace DB", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.commit()
    return database.id


@pytest.fixture
def headers():
    return {
        "Authorization": f"Bearer {create_access_token(UserModel(id=1, email='test@company.com', username='tester'))}"
    }


async def _fake_chat(db_id, body, org_id, user, db):
    session = await routes._resolve_chat_session(db, body.session_id, user.id, int(db_id))
    replay = await routes._replay_chat_response(db, session, user.id, body.client_message_id)
    if replay:
        return replay
    user_message = await save_chat_message(
        db, session.id, "user", body.message, client_message_id=body.client_message_id
    )
    with execution_step("context"):
        if body.message == "fail":
            raise ValueError("secret-connection-string")
    assistant = await save_chat_message(
        db,
        session.id,
        "assistant",
        "Answer",
        intent="chitchat",
        metadata_json={"status": "completed"},
        client_message_id=f"{body.client_message_id}:assistant",
    )
    return ChatResponse(
        intent="chitchat",
        chat_response="Answer",
        session_id=session.id,
        user_message_id=user_message.id,
        assistant_message_id=assistant.id,
    )


@pytest.mark.asyncio
async def test_stream_result_history_and_replay_share_trace(client, async_session, chat_database, headers):
    session = await create_chat_session(async_session, 1, chat_database)
    body = {"message": "hello", "session_id": session.id, "client_message_id": "trace-client"}
    with patch("src.api.routes._execute_chat_request_inner", side_effect=_fake_chat):
        response = await client.post(f"/api/v1/semantic/{chat_database}/chat/stream", json=body, headers=headers)
        replay = await client.post(f"/api/v1/semantic/{chat_database}/chat", json=body, headers=headers)
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    assert "event: snapshot" in response.text and "event: result" in response.text
    trace = replay.json()["execution_trace"]
    assert trace["status"] == "completed" and trace["run_id"] in response.text
    history = await client.get(f"/api/v1/semantic/{chat_database}/chat/sessions/{session.id}", headers=headers)
    assert history.json()["messages"][-1]["metadata_json"]["execution_trace"] == trace
    assert len(history.json()["messages"]) == 2


@pytest.mark.asyncio
async def test_stream_checks_database_org_session_and_client_id(client, async_session, chat_database, headers):
    with patch("src.api.routes._start_chat_request") as start:
        for path, body, extra in [
            (chat_database, {"message": "hello"}, {}),
            (99999, {"message": "hello", "client_message_id": "client"}, {}),
            (chat_database, {"message": "hello", "client_message_id": "client"}, {"X-Organization-ID": "999"}),
            (
                chat_database,
                {
                    "message": "hello",
                    "client_message_id": "client",
                    "session_id": "00000000-0000-0000-0000-000000000000",
                },
                {},
            ),
        ]:
            response = await client.post(
                f"/api/v1/semantic/{path}/chat/stream", json=body, headers={**headers, **extra}
            )
            assert response.status_code in {404, 422}
        start.assert_not_called()


@pytest.mark.asyncio
async def test_stream_failure_is_persisted_and_does_not_expose_exception(client, async_session, chat_database, headers):
    session = await create_chat_session(async_session, 1, chat_database)
    body = {"message": "fail", "session_id": session.id, "client_message_id": "failed-client"}
    with patch("src.api.routes._execute_chat_request_inner", side_effect=_fake_chat):
        response = await client.post(f"/api/v1/semantic/{chat_database}/chat/stream", json=body, headers=headers)
        replay = await client.post(f"/api/v1/semantic/{chat_database}/chat", json=body, headers=headers)
    assert "event: error" in response.text and "secret-connection-string" not in response.text
    assert replay.json()["execution_trace"]["status"] == "error"
    messages = list(
        (await async_session.scalars(select(ChatMessageModel).where(ChatMessageModel.session_id == session.id))).all()
    )
    assert len(messages) == 2
    assert messages[-1].metadata_json["status"] == "error"


@pytest.mark.asyncio
async def test_old_replay_does_not_invent_trace(client, async_session, chat_database, headers):
    session = await create_chat_session(async_session, 1, chat_database)
    await save_chat_message(async_session, session.id, "user", "old", client_message_id="old-client")
    assistant = await save_chat_message(
        async_session, session.id, "assistant", "Old answer", client_message_id="old-client:assistant"
    )
    body = {"message": "old", "session_id": session.id, "client_message_id": "old-client"}
    with patch("src.api.routes._execute_chat_request_inner", side_effect=_fake_chat):
        response = await client.post(f"/api/v1/semantic/{chat_database}/chat", json=body, headers=headers)
    assert response.json()["execution_trace"] is None
    await async_session.refresh(assistant)
    assert assistant.metadata_json is None


@pytest.mark.asyncio
async def test_json_failure_without_client_id_still_saves_safe_history(client, async_session, chat_database, headers):
    session = await create_chat_session(async_session, 1, chat_database)
    body = {"message": "fail", "session_id": session.id}
    with patch("src.api.routes._execute_chat_request_inner", side_effect=_fake_chat), pytest.raises(ValueError):
        await client.post(f"/api/v1/semantic/{chat_database}/chat", json=body, headers=headers)
    messages = list(
        await async_session.scalars(select(ChatMessageModel).where(ChatMessageModel.session_id == session.id))
    )
    assert len(messages) == 2
    assert messages[-1].metadata_json["execution_trace"]["status"] == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize("reuse", [True, False])
async def test_query_action_failures_keep_safe_history(client, async_session, chat_database, headers, reuse):
    session = await create_chat_session(async_session, 1, chat_database)
    body = {"message": "Calculate", "session_id": session.id, "client_message_id": "query-failure"}
    if reuse:
        body["reuse_metric_id"] = 1
    else:
        previous = await save_chat_message(
            async_session,
            session.id,
            "assistant",
            "Choose",
            metadata_json={
                "clarification": {"options": [{"id": "option", "spec": {"metric_ids": [1]}}]},
            },
        )
        body["clarification_selection"] = {"assistant_message_id": previous.id, "option_id": "option"}
    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.api.routes.build_parser_catalog", new=AsyncMock(return_value={"metrics": [{"id": 1}]})),
        patch("src.api.routes._query_target", new=AsyncMock(return_value=(None, None))),
        patch("src.api.routes.execute_natural_language_query", new=AsyncMock(side_effect=RuntimeError("secret SQL"))),
    ):
        response = await client.post(f"/api/v1/semantic/{chat_database}/chat/stream", json=body, headers=headers)
    assert "event: error" in response.text and "secret SQL" not in response.text
    messages = list(
        await async_session.scalars(
            select(ChatMessageModel).where(
                ChatMessageModel.session_id == session.id,
                ChatMessageModel.client_message_id == "query-failure:assistant",
            )
        )
    )
    assert len(messages) == 1
    assert messages[0].metadata_json["execution_trace"]["status"] == "error"
