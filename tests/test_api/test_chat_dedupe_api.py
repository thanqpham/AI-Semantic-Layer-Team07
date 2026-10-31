"""API tests for dedupe wiring in the AI chat orchestrator route."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.api.auth import create_access_token
from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel
from src.models.metric_definition import MetricDefinition
from src.services.metric_context import MetricContextResult
from src.services.metric_service import create_metric


@pytest.fixture
def auth_headers() -> dict[str, str]:
    user = UserModel(id=1, email="test@company.com", username="tester", hashed_password="hash")
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.fixture
def chat_session_mocks():
    """Patch main's RBAC/session persistence layer around the chat orchestrator."""
    now = datetime(2026, 8, 19, 12, 0, 0)
    session = SimpleNamespace(id="sess-1", db_id=101, title="Phiên test", created_at=now, updated_at=now)
    refreshed = SimpleNamespace(id="sess-1", db_id=101, title="Phiên test", created_at=now, updated_at=now)
    with (
        patch("src.api.routes.get_chat_database", new_callable=AsyncMock),
        patch("src.api.routes._chat_can_generate_metrics", new_callable=AsyncMock) as mock_can,
        patch("src.api.routes._resolve_chat_session", new_callable=AsyncMock) as mock_resolve,
        patch("src.api.routes._replay_chat_response", new_callable=AsyncMock) as mock_replay,
        patch("src.api.routes.get_recent_chat_history", new_callable=AsyncMock) as mock_history,
        patch("src.api.routes.save_chat_message", new_callable=AsyncMock) as mock_save,
        patch("src.api.routes.get_chat_session_with_messages", new_callable=AsyncMock) as mock_refresh,
        patch("src.api.routes.build_metric_context", new_callable=AsyncMock) as mock_context,
        patch("src.agents.nodes.chat.orchestrator_node.orchestrator_node", new_callable=AsyncMock) as mock_orch,
    ):
        mock_can.return_value = True
        mock_resolve.return_value = session
        mock_replay.return_value = None
        mock_history.return_value = []
        mock_save.side_effect = lambda *args, **kwargs: SimpleNamespace(
            id="msg-id",
            content=kwargs.get("content", ""),
            sender=kwargs.get("sender", "user"),
            intent=kwargs.get("intent"),
            metadata_json=kwargs.get("metadata_json"),
        )
        mock_refresh.return_value = refreshed
        mock_context.return_value = MetricContextResult(schema={}, diagnostic={"status": "ready"})
        mock_orch.return_value = {"intent": "metric_query"}
        yield SimpleNamespace(resolve=mock_resolve, save=mock_save)


_MINIMAL_METRIC: dict = {
    "definition": {
        "metric": {
            "name": "Doanh thu",
            "formula": {"function": "SUM", "expression": "quantity * unit_price"},
            "base_entity": "order_items",
            "filters": [],
            "status": "pending_approval",
            "confidence": "high",
        }
    },
    "yaml_preview": "metric:\n  name: Doanh thu\n",
}

_EXISTING_SUMMARY: dict = {
    "id": 12,
    "name": "Doanh thu",
    "status": "approved",
    "function": "SUM",
    "expression": "quantity * unit_price",
    "base_entity": "order_items",
    "filters": [],
}

_DUPLICATE_NOTICE: dict = {
    "proposed_metric_name": "Tổng doanh thu",
    "existing_metric_id": 12,
    "existing_metric_name": "Doanh thu",
    "existing_metric_status": "approved",
    "user_message": "Đã có metric chuẩn",
    "similarity_reason": "",
}


@pytest.mark.asyncio
async def test_replay_uses_saved_proposal_mode() -> None:
    from src.api.routes import _replay_chat_response

    session = SimpleNamespace(id="sess-1")
    user = SimpleNamespace(id="user")
    assistant = SimpleNamespace(id="assistant", intent="metric_query", content="test", metadata_json={"proposal_mode": "discovery"})
    refreshed = SimpleNamespace(id="sess-1", db_id=101, title="Test", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1))
    with (
        patch("src.api.routes.get_chat_message_by_client_id", new=AsyncMock(side_effect=[user, assistant])),
        patch("src.api.routes.get_chat_session_with_messages", new=AsyncMock(return_value=refreshed)),
    ):
        response = await _replay_chat_response(None, session, 1, "client")
    assert response.proposal_mode == "discovery"


@pytest.mark.asyncio
async def test_scope_question_returns_and_persists_options(client, auth_headers, chat_session_mocks) -> None:
    """Scope questions must expose the same selectable choices live and after reload."""
    clarification = {
        "prompt": "AOV theo giá nào?",
        "options": [{"id": "scope_0", "label": "Tính AOV theo price_after_tax"}],
    }
    with patch("src.api.routes.build_metric_context", new_callable=AsyncMock) as context:
        context.return_value = MetricContextResult(
            schema={},
            diagnostic={
                "status": "needs_clarification",
                "message": clarification["prompt"],
                "clarification": clarification,
            },
        )
        response = await client.post("/api/v1/semantic/101/chat", json={"message": "Tính AOV"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["proposal_mode"] == "requested"
    assert response.json()["clarification"]["options"][0]["label"] == clarification["options"][0]["label"]
    metadata = chat_session_mocks.save.call_args.kwargs["metadata_json"]
    assert metadata["proposal_mode"] == "requested"
    assert metadata["clarification"]["options"][0]["id"] == "scope_0"


@pytest.mark.asyncio
async def test_scope_selection_continues_metric_generation() -> None:
    """A scope answer uses the stored choice and stays in the metric generation flow."""
    from src.api.routes import _handle_clarification_selection
    from src.models.schemas import ChatClarificationSelection, ChatRequest

    option = {"id": "scope_0", "label": "Tính AOV theo order_header.price_after_tax", "action": "create_metric"}
    previous = SimpleNamespace(metadata_json={"proposal_mode": "discovery", "clarification": {"options": [option]}})
    selection = ChatClarificationSelection(assistant_message_id="a-1", option_id="scope_0")
    with (
        patch("src.api.routes.get_chat_message", new=AsyncMock(return_value=previous)),
        patch("src.api.routes._process_standard_chat", new_callable=AsyncMock) as process,
    ):
        await _handle_clarification_selection(
            None,
            SimpleNamespace(id="sess-1"),
            SimpleNamespace(id=1),
            101,
            selection,
            ChatRequest(message="Client label", clarification_selection=selection),
            True,
        )
    assert process.call_args.args[4].message == option["label"]
    assert process.call_args.args[4].proposal_mode == "discovery"
    assert process.call_args.kwargs["intent_override"] == "metric_query"


@pytest.mark.asyncio
async def test_legacy_data_clarification_does_not_force_discovery() -> None:
    from src.api.routes import _handle_clarification_selection
    from src.models.schemas import ChatClarificationSelection, ChatRequest

    selection = ChatClarificationSelection(assistant_message_id="a-1", option_id="data-choice")
    previous = SimpleNamespace(metadata_json={"clarification": {"options": [{"id": "data-choice"}]}})
    with (
        patch("src.api.routes.get_chat_message", new=AsyncMock(return_value=previous)),
        patch("src.api.routes._process_standard_chat", new=AsyncMock()) as process,
    ):
        await _handle_clarification_selection(None, SimpleNamespace(id="sess-1"), SimpleNamespace(id=1), 101,
                                            selection, ChatRequest(message="choice", clarification_selection=selection), True)
    assert process.call_args.args[4].proposal_mode == "requested"


@pytest.mark.asyncio
async def test_metric_variant_selection_reuses_stored_requirement_and_reviewed_choice() -> None:
    from src.api.routes import _handle_clarification_selection
    from src.models.schemas import ChatClarificationSelection, ChatRequest

    option = {
        "id": "metric-variant-opaque",
        "action": "generate_metric_variant",
        "action_payload": {
            "requirement": "Net sales for completed orders",
            "knowledge_id": "net_sales",
            "variant_id": "merchandise_net_sales",
            "criteria": {"tax_basis": "excludes_tax"},
        },
    }
    previous = SimpleNamespace(metadata_json={"proposal_mode": "discovery", "clarification": {"options": [option]}})
    selection = ChatClarificationSelection(assistant_message_id="a-1", option_id=option["id"])
    with (
        patch("src.api.routes.get_chat_message", new=AsyncMock(return_value=previous)),
        patch("src.api.routes._process_standard_chat", new_callable=AsyncMock) as process,
    ):
        await _handle_clarification_selection(
            None, SimpleNamespace(id="sess-1"), SimpleNamespace(id=1), 101, selection,
            ChatRequest(message="Client label", clarification_selection=selection), True,
        )
    request = process.call_args.args[4].message
    assert "Net sales for completed orders" in request
    assert "merchandise_net_sales" in request
    assert "tax_basis: excludes_tax" in request
    assert process.call_args.args[4].proposal_mode == "requested"
    assert process.call_args.kwargs["intent_override"] == "metric_query"
    assert process.call_args.kwargs["selected_metric_variant"] == option["action_payload"]


@pytest.mark.asyncio
@patch("src.api.routes.load_existing_for_dedupe", new_callable=AsyncMock)
@patch("src.agents.graphs.chat_graph.chat_agent", new_callable=AsyncMock)
async def test_chat_returns_duplicates(
    mock_agent: AsyncMock,
    mock_load: AsyncMock,
    client: AsyncClient,
    auth_headers: dict[str, str],
    chat_session_mocks: SimpleNamespace,
) -> None:
    mock_load.return_value = ([_EXISTING_SUMMARY], True)
    mock_agent.ainvoke.return_value = {
        "intent": "metric_query",
        "suggested_metrics": [_MINIMAL_METRIC],
        "duplicate_notices": [_DUPLICATE_NOTICE],
        "dedupe_performed": True,
    }
    response = await client.post("/api/v1/semantic/101/chat", json={"message": "tính doanh thu"}, headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["intent"] == "metric_query"
    assert body["duplicates"][0]["existing_metric_name"] == "Doanh thu"
    assert body["dedupe_performed"] is True
    assert body["session_id"] == "sess-1"
    state = mock_agent.ainvoke.call_args.args[0]
    assert state["existing_metrics"]
    assert state["dedupe_performed"] is True
    # The duplicate notice is persisted on the assistant message for replay.
    metadata = chat_session_mocks.save.call_args_list[-1].kwargs["metadata_json"]
    assert metadata["duplicates"] == [_DUPLICATE_NOTICE]


@pytest.mark.asyncio
@patch("src.agents.graphs.chat_graph.chat_agent", new_callable=AsyncMock)
async def test_chat_detects_existing_definition_with_different_name(
    mock_agent: AsyncMock,
    client: AsyncClient,
    async_session,
    auth_headers: dict[str, str],
    chat_session_mocks: SimpleNamespace,
) -> None:
    async_session.add(
        SemanticDatabaseModel(id=101, created_by=1, display_name="Orders", db_type="sqlite", conn_url_enc="enc")
    )
    async_session.add(SemanticTableModel(id=101, db_id=101, table_name="orders", business_name="Orders"))
    await async_session.flush()
    async_session.add_all(
        [
            SemanticColumnModel(
                table_id=101, column_name="id", business_name="ID", data_type="INTEGER", is_primary_key=True
            ),
            SemanticColumnModel(table_id=101, column_name="amount", business_name="Amount", data_type="NUMERIC"),
        ]
    )
    await async_session.flush()
    original = MetricDefinition.model_validate(
        {"metric": {"name": "Revenue", "formula": {"function": "SUM", "expression": "amount"}, "base_entity": "orders"}}
    )
    existing = await create_metric(async_session, 101, {"definition": original.model_dump(mode="json")}, 1)
    draft = original.model_copy(deep=True)
    draft.metric.name = "Total revenue"
    mock_agent.ainvoke.return_value = {
        "intent": "metric_query",
        "suggested_metrics": [{"definition": draft.model_dump(mode="json"), "yaml_preview": "metric:"}],
        "suggestion_action": "save_metric",
    }

    response = await client.post("/api/v1/semantic/101/chat", json={"message": "Revenue"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["suggestions"] == []
    assert response.json()["duplicates"][0]["existing_metric_id"] == existing.id
    metadata = chat_session_mocks.save.call_args_list[-1].kwargs["metadata_json"]
    assert metadata["suggestions"] == []
    assert metadata["duplicates"][0]["existing_metric_id"] == existing.id


@pytest.mark.asyncio
@patch("src.api.routes.load_existing_for_dedupe", new_callable=AsyncMock)
@patch("src.agents.graphs.chat_graph.chat_agent", new_callable=AsyncMock)
async def test_chat_loads_existing_for_numeric_db(
    mock_agent: AsyncMock,
    mock_load: AsyncMock,
    client: AsyncClient,
    auth_headers: dict[str, str],
    chat_session_mocks: SimpleNamespace,
) -> None:
    mock_load.return_value = ([], True)
    mock_agent.ainvoke.return_value = {
        "intent": "metric_query",
        "suggested_metrics": [],
        "duplicate_notices": [],
        "dedupe_performed": True,
    }
    response = await client.post("/api/v1/semantic/101/chat", json={"message": "tính doanh thu"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["dedupe_performed"] is True
    mock_load.assert_awaited_once()


@pytest.mark.asyncio
@patch("src.api.routes.load_existing_for_dedupe", new_callable=AsyncMock)
@patch("src.agents.graphs.chat_graph.chat_agent", new_callable=AsyncMock)
async def test_chat_dedupe_unavailable_still_200(
    mock_agent: AsyncMock,
    mock_load: AsyncMock,
    client: AsyncClient,
    auth_headers: dict[str, str],
    chat_session_mocks: SimpleNamespace,
) -> None:
    mock_load.return_value = ([], False)
    mock_agent.ainvoke.return_value = {
        "intent": "metric_query",
        "suggested_metrics": [],
        "duplicate_notices": [],
        "dedupe_performed": False,
    }
    response = await client.post("/api/v1/semantic/101/chat", json={"message": "tính doanh thu"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["dedupe_performed"] is False
