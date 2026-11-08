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
async def test_stream_known_compile_error_is_safe_and_replayed(client, async_session, chat_database, headers):
    from src.services.semantic_compile_error import SemanticCompileError

    async def fail_compile(*args, **kwargs):
        with execution_step("sql_compile"):
            raise SemanticCompileError("UNSAFE_FANOUT", "secret SQL")

    session = await create_chat_session(async_session, 1, chat_database)
    body = {"message": "Xem metric", "session_id": session.id, "client_message_id": "known-failure"}
    catalog = {
        "_relationship_fingerprint": "graph-v1",
        "metrics": [{"id": 1, "base_entity": "orders", "dimension_ids": [], "filter_column_ids": []}],
    }
    state = {"intent": "semantic_query", "interpretation": {"status": "resolved", "spec": {"metric_ids": [1]}}}
    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.api.routes.build_parser_catalog", new=AsyncMock(return_value=catalog)),
        patch("src.api.routes._query_target", new=AsyncMock(return_value=(None, None))),
        patch("src.api.routes.execute_natural_language_query", new=AsyncMock(side_effect=fail_compile)),
        patch(
            "src.agents.nodes.chat.orchestrator_node.orchestrator_node",
            new=AsyncMock(return_value={"intent": "semantic_query"}),
        ),
        patch("src.agents.graphs.chat_graph.chat_agent") as agent,
    ):
        agent.ainvoke = AsyncMock(return_value=state)
        response = await client.post(f"/api/v1/semantic/{chat_database}/chat/stream", json=body, headers=headers)
        replay = await client.post(f"/api/v1/semantic/{chat_database}/chat", json=body, headers=headers)
    assert "event: result" in response.text and "secret SQL" not in response.text
    assert "quan hệ" in replay.json()["chat_response"].lower()
    assert replay.json()["execution_trace"]["status"] == "error"
    assert any(event.get("error_code") == "UNSAFE_FANOUT" for event in replay.json()["execution_trace"]["events"])


@pytest.mark.asyncio
async def test_clarification_snapshot_blocks_changed_mapping_without_exposing_digest(
    client, async_session, chat_database, headers
):
    session = await create_chat_session(async_session, 1, chat_database)
    catalog = {
        "_relationship_fingerprint": "graph-v1",
        "metrics": [{"id": 1, "base_entity": "orders", "dimension_ids": [], "filter_column_ids": [11]}],
        "filter_columns": [
            {
                "column_id": 11,
                "data_type": "TEXT",
                "review_status": "approved",
                "allowed_values": ["North"],
                "_approved_mappings": [{"db_value": "North", "business_value": "Miền Bắc", "status": "approved"}],
            }
        ],
    }
    clarification = {
        "prompt": "Chọn",
        "options": [
            {
                "id": "opt",
                "label": "Miền Bắc",
                "spec": {"metric_ids": [1], "filters": [{"column_id": 11, "operator": "eq", "value": "Miền Bắc"}]},
            }
        ],
    }
    state = {
        "intent": "semantic_query",
        "interpretation": {"status": "needs_clarification", "clarification": clarification},
        "clarification": clarification,
    }
    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.api.routes.build_parser_catalog", new=AsyncMock(return_value=catalog)),
        patch("src.api.routes._query_target", new=AsyncMock(return_value=(None, None))),
        patch("src.api.routes.execute_natural_language_query", new=AsyncMock()) as execute,
        patch(
            "src.agents.nodes.chat.orchestrator_node.orchestrator_node",
            new=AsyncMock(return_value={"intent": "semantic_query"}),
        ),
        patch("src.agents.graphs.chat_graph.chat_agent") as agent,
    ):
        agent.ainvoke = AsyncMock(return_value=state)
        initial = await client.post(
            f"/api/v1/semantic/{chat_database}/chat",
            headers=headers,
            json={"message": "Xem miền Bắc", "session_id": session.id},
        )
        assert initial.status_code == 200
        assistant_id = initial.json()["assistant_message_id"]
        saved = await async_session.get(ChatMessageModel, assistant_id)
        assert saved.metadata_json["semantic_option_digests"].get("opt")
        history = await client.get(f"/api/v1/semantic/{chat_database}/chat/sessions/{session.id}", headers=headers)
        assert "semantic_option_digests" not in str(history.json())
        catalog["filter_columns"][0]["allowed_values"] = ["South"]
        catalog["filter_columns"][0]["_approved_mappings"][0]["db_value"] = "South"
        selected = await client.post(
            f"/api/v1/semantic/{chat_database}/chat",
            headers=headers,
            json={
                "message": "Miền Bắc",
                "session_id": session.id,
                "clarification_selection": {"assistant_message_id": assistant_id, "option_id": "opt"},
            },
        )
    assert selected.status_code == 200
    assert selected.json()["semantic_query_result"] is None
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["pairs", "direction", "status"])
async def test_real_catalog_relationship_change_invalidates_old_option(
    client, async_session, chat_database, headers, change
):
    from src.api.routes import _option_spec_digest
    from src.models.db import CanonicalRelationshipModel
    from src.models.schemas import SemanticQuerySpec
    from src.services.natural_language_query import build_parser_catalog
    from tests.test_services.test_compiler_relationship_cases import _add_table, _make_sum_metric

    orders, oc = await _add_table(
        async_session,
        chat_database,
        "orders",
        [
            ("id", "INTEGER", True),
            ("amount", "NUMERIC", False),
            ("customer_id", "INTEGER", False),
            ("other_customer_id", "INTEGER", False),
        ],
    )
    customers, cc = await _add_table(async_session, chat_database, "customers", [("id", "INTEGER", True)])
    relation = CanonicalRelationshipModel(
        connection_id=chat_database,
        from_entity_id=orders.id,
        to_entity_id=customers.id,
        relationship_type="many_to_one",
        relationship_key="orders_customer",
        join_condition="metadata only",
        column_pairs=[{"from_column_id": oc["customer_id"].id, "to_column_id": cc["id"].id}],
        review_status="approved",
        validation_status="valid",
    )
    metric = _make_sum_metric(chat_database, "Revenue", "orders", orders.id, oc["amount"].id, oc["id"].id)
    async_session.add_all([relation, metric])
    await async_session.commit()
    session = await create_chat_session(async_session, 1, chat_database)
    before = await build_parser_catalog(async_session, chat_database)
    spec = SemanticQuerySpec(metric_ids=[metric.id])
    previous = await save_chat_message(
        async_session,
        session.id,
        "assistant",
        "Choose",
        metadata_json={
            "semantic_option_digests": {"opt": _option_spec_digest(session.id, "opt", spec, before)},
            "clarification": {"options": [{"id": "opt", "spec": spec.model_dump(mode="json")}]},
        },
    )
    if change == "pairs":
        relation.column_pairs = [{"from_column_id": oc["other_customer_id"].id, "to_column_id": cc["id"].id}]
    elif change == "direction":
        relation.from_entity_id, relation.to_entity_id = customers.id, orders.id
        relation.relationship_type = "one_to_many"
        relation.column_pairs = [{"from_column_id": cc["id"].id, "to_column_id": oc["customer_id"].id}]
    else:
        relation.review_status = "disabled"
    await async_session.commit()
    after = await build_parser_catalog(async_session, chat_database)
    assert before["_relationship_fingerprint"] != after["_relationship_fingerprint"]
    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.api.routes._query_target", new=AsyncMock(return_value=(None, None))),
        patch("src.api.routes.execute_natural_language_query", new=AsyncMock()) as execute,
    ):
        response = await client.post(
            f"/api/v1/semantic/{chat_database}/chat",
            headers=headers,
            json={
                "message": "Xem",
                "session_id": session.id,
                "clarification_selection": {"assistant_message_id": previous.id, "option_id": "opt"},
            },
        )
    assert response.status_code == 200
    assert response.json()["semantic_query_result"] is None
    execute.assert_not_awaited()


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
    from src.api.routes import _option_spec_digest
    from src.models.schemas import SemanticQuerySpec

    session = await create_chat_session(async_session, 1, chat_database)
    body = {"message": "Calculate", "session_id": session.id, "client_message_id": "query-failure"}
    catalog = {"_relationship_fingerprint": "graph-v1", "_mapping_fingerprint": "mapping-v1", "metrics": [{"id": 1}]}
    if reuse:
        body["reuse_metric_id"] = 1
    else:
        previous = await save_chat_message(
            async_session,
            session.id,
            "assistant",
            "Choose",
            metadata_json={
                "semantic_option_digests": {
                    "option": _option_spec_digest(session.id, "option", SemanticQuerySpec(metric_ids=[1]), catalog)
                },
                "clarification": {"options": [{"id": "option", "spec": {"metric_ids": [1]}}]},
            },
        )
        body["clarification_selection"] = {"assistant_message_id": previous.id, "option_id": "option"}
    with (
        patch("src.api.routes._chat_can_generate_metrics", new=AsyncMock(return_value=True)),
        patch("src.api.routes.build_parser_catalog", new=AsyncMock(return_value=catalog)),
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
