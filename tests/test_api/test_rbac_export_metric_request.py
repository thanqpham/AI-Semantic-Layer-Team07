"""RBAC tests for Export access and metric-request submission (GitHub #60).

Coach feedback: Export must be restricted to ``data_lead`` only (server-side 403 for
admin/member), and admin must no longer be able to submit metric requests through chat
while member remains allowed. Admin ordinary Q&A chat stays available.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_access_token
from src.models.db import (
    ChatSessionModel,
    OrganizationMemberModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    UserModel,
)
from src.models.schemas import ChatResponse
from src.services.organization_service import create_organization


def _workspace_headers(user: UserModel, org_id: int) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token(user)}",
        "X-Organization-ID": str(org_id),
    }


async def _seed_workspace(async_session: AsyncSession, role: str) -> tuple[UserModel, int, int]:
    """Create a workspace with one member of ``role`` and a shared semantic DB."""
    owner = await async_session.get(UserModel, 1)
    organization = await create_organization(async_session, owner.id, f"{role} RBAC WS", f"rbac-{role}")
    if role == "admin":
        actor = owner  # create_organization already made owner the admin member
    else:
        actor = UserModel(
            id=2,
            email=f"{role}@company.com",
            username=role,
            full_name=role.replace("_", " ").title(),
            hashed_password="hash",
            status="active",
        )
        async_session.add(actor)
        async_session.add(OrganizationMemberModel(org_id=organization.id, user_id=actor.id, role=role))
    sem_db = SemanticDatabaseModel(
        org_id=organization.id,
        created_by=owner.id,
        display_name="RBAC DB",
        db_type="postgresql",
        conn_url_enc="dummy",
        status="saved",
    )
    async_session.add(sem_db)
    await async_session.flush()
    await async_session.commit()
    return actor, organization.id, sem_db.id


# ---------------------------------------------------------------------------
# Export endpoint RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "expected_status"),
    [
        ("data_lead", 200),
        ("admin", 403),
        ("member", 403),
    ],
)
async def test_export_requires_can_export(
    client: AsyncClient, async_session: AsyncSession, role: str, expected_status: int
) -> None:
    """Export is callable only by data_lead; admin/member receive 403."""
    actor, org_id, db_id = await _seed_workspace(async_session, role)
    res = await client.get(
        f"/api/v1/semantic/{db_id}/export",
        headers=_workspace_headers(actor, org_id),
    )
    assert res.status_code == expected_status


# ---------------------------------------------------------------------------
# Metric-request submission RBAC
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_metric_request_submission_is_forbidden(client: AsyncClient, async_session: AsyncSession) -> None:
    """Admin can no longer submit a metric request via chat (loophole closed)."""
    actor, org_id, db_id = await _seed_workspace(async_session, "admin")
    res = await client.post(
        f"/api/v1/semantic/{db_id}/metric-requests",
        json={"assistant_message_id": str(uuid.uuid4()), "suggestion_index": 0},
        headers=_workspace_headers(actor, org_id),
    )
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_member_metric_request_submission_remains_allowed(
    client: AsyncClient, async_session: AsyncSession
) -> None:
    """Member keeps the ability to submit metric requests (not 403)."""
    actor, org_id, db_id = await _seed_workspace(async_session, "member")
    res = await client.post(
        f"/api/v1/semantic/{db_id}/metric-requests",
        json={"assistant_message_id": str(uuid.uuid4()), "suggestion_index": 0},
        headers=_workspace_headers(actor, org_id),
    )
    assert res.status_code != 403


@pytest.mark.asyncio
async def test_admin_ordinary_chat_remains_allowed(client: AsyncClient, async_session: AsyncSession) -> None:
    """Admin ordinary Q&A chat is unaffected by the metric-request guard."""
    actor, org_id, db_id = await _seed_workspace(async_session, "admin")
    session = ChatSessionModel(id=str(uuid.uuid4()), user_id=actor.id, db_id=db_id, title="Cuộc trò chuyện mới")
    async_session.add(session)
    await async_session.commit()

    fake_response = ChatResponse(
        intent="data_question",
        chat_response="Chào bạn",
        session_id=str(session.id),
        user_message_id="u1",
        assistant_message_id="a1",
    )
    with patch("src.api.routes._process_standard_chat", new_callable=AsyncMock) as mock_proc:
        mock_proc.return_value = fake_response
        res = await client.post(
            f"/api/v1/semantic/{db_id}/chat",
            json={"message": "Xin chào", "session_id": str(session.id)},
            headers=_workspace_headers(actor, org_id),
        )
    assert res.status_code != 403


@pytest.mark.asyncio
async def test_member_missing_metric_uses_real_graph_and_requires_manual_submit(
    client: AsyncClient, async_session: AsyncSession
) -> None:
    from types import SimpleNamespace

    from src.models.metric_review import MetricReview
    from src.services.metric_context import MetricContextResult
    from tests.metric_review_helpers import definition, schema

    actor, org_id, db_id = await _seed_workspace(async_session, "member")
    proposal = {
        "name": "Revenue",
        "final_definition": definition(),
        "review": MetricReview(status="pass", summary="Valid").model_dump(mode="json"),
    }
    with (
        patch(
            "src.agents.roles.orchestrator_agent.get_llm",
            return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="semantic_query"))),
        ),
        patch("src.agents.roles.semantic_query_parser_agent.get_llm", return_value=None),
        patch(
            "src.agents.roles.semantic_query_parser_agent.ainvoke_json",
            new=AsyncMock(return_value={"status": "missing_metric", "metric_name": "Revenue"}),
        ),
        patch(
            "src.api.routes._build_chat_context",
            new=AsyncMock(return_value=MetricContextResult(schema=schema(), diagnostic={"status": "ready"})),
        ),
        patch("src.agents.nodes.metric.coordinator_node.prepare_proposal_context", return_value={}),
        patch("src.agents.nodes.metric.coordinator_node.run_metric_workflow", new=AsyncMock(return_value=[proposal])),
        patch("src.api.routes.persist_reviewed_state", new_callable=AsyncMock),
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/chat",
            json={"message": "Show revenue"},
            headers=_workspace_headers(actor, org_id),
        )
    assert response.status_code == 200
    assert response.json()["intent"] == "metric_query"
    assert response.json()["suggestion_action"] == "submit_metric_request"
    assert response.json()["suggestions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("has_approved", [True, False])
async def test_member_lists_approved_metric_catalog_without_schema_selection(
    client: AsyncClient, async_session: AsyncSession, has_approved: bool
) -> None:
    from types import SimpleNamespace

    actor, org_id, db_id = await _seed_workspace(async_session, "member")
    metrics = [
        SemanticMetricModel(
            db_id=db_id, name="Deleted metric", description="", sql_template="", status="approved", is_deleted=True
        ),
        SemanticMetricModel(db_id=db_id, name="Draft metric", description="", sql_template="", status="draft"),
    ]
    if has_approved:
        metrics.append(
            SemanticMetricModel(db_id=db_id, name="Approved metric", description="", sql_template="", status="approved")
        )
    async_session.add_all(metrics)
    await async_session.commit()
    with (
        patch(
            "src.agents.roles.orchestrator_agent.get_llm",
            return_value=SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="data_question"))),
        ),
        patch("src.api.routes.build_data_context", new_callable=AsyncMock) as context,
        patch("src.api.routes._query_target", new_callable=AsyncMock) as query,
        patch("src.agents.roles.data_assistant_agent.get_llm") as llm,
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/chat",
            json={"message": "Hiện có những metric nào đã được phê duyệt?"},
            headers=_workspace_headers(actor, org_id),
        )
    assert response.status_code == 200
    answer = response.json()["chat_response"]
    assert ("Approved metric" in answer) is has_approved
    assert "Deleted metric" not in answer
    assert "Draft metric" not in answer
    if not has_approved:
        assert "chưa có metric" in answer
    context.assert_not_awaited()
    query.assert_not_awaited()
    llm.assert_not_called()


@pytest.mark.asyncio
async def test_schema_question_still_builds_data_context(async_session: AsyncSession) -> None:
    from src.api.routes import _build_chat_context
    from src.services.metric_context import MetricContextResult

    expected = MetricContextResult(schema={}, diagnostic={"status": "ready"})
    with patch("src.api.routes.build_data_context", new=AsyncMock(return_value=expected)) as context:
        result = await _build_chat_context(async_session, 1, "Bảng customers có những cột nào?", "data_question", 1000)
    assert result is expected
    context.assert_awaited_once()
