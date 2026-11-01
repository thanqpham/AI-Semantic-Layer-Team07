"""Chat session detail must annotate suggestions with real metric lifecycle state."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_access_token
from src.models.db import (
    MetricProposalModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    UserModel,
)
from src.services.chat_service import create_chat_session, save_chat_message


@pytest.fixture
async def chat_database(async_session: AsyncSession) -> int:
    """One personal semantic database owned by user 1."""
    database = SemanticDatabaseModel(created_by=1, display_name="Lifecycle DB", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.commit()
    return database.id


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer token for the seeded owner user (id=1)."""
    user = UserModel(id=1, email="test@company.com", username="tester", hashed_password="hash")
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _metric(db: AsyncSession, db_id: int, name: str, status: str) -> SemanticMetricModel:
    """Insert one catalog metric row directly for read-path annotation tests."""
    metric = SemanticMetricModel(
        db_id=db_id, name=name, description="d", sql_template="SELECT 1", formula="SUM(x)", status=status, version=1
    )
    db.add(metric)
    await db.flush()
    return metric


async def _proposal(db: AsyncSession, db_id: int, metric_id: int | None, reason: str | None) -> MetricProposalModel:
    """Insert one proposal row directly, optionally linked or released-with-reason."""
    proposal = MetricProposalModel(
        db_id=db_id,
        created_by=1,
        context={},
        review={"status": "pass"},
        status="pass",
        schema_fingerprint="f" * 64,
        metric_id=metric_id,
        metric_version=1 if metric_id else None,
        rejection_reason=reason,
    )
    db.add(proposal)
    await db.flush()
    return proposal


@pytest.mark.asyncio
async def test_session_detail_annotates_suggestion_lifecycle(
    client, async_session, chat_database, auth_headers
) -> None:
    """Each suggestion carries the live lifecycle of its proposal-backed metric."""
    session = await create_chat_session(async_session, 1, chat_database)
    pending = await _metric(async_session, chat_database, "Đơn chờ duyệt", "pending_approval")
    approved = await _metric(async_session, chat_database, "Đơn đã duyệt", "approved")
    proposal_pending = await _proposal(async_session, chat_database, pending.id, None)
    proposal_approved = await _proposal(async_session, chat_database, approved.id, None)
    proposal_rejected = await _proposal(async_session, chat_database, None, "Thiếu căn cứ nghiệp vụ")
    suggestions = [
        {"definition": {"metric": {"name": "Gợi ý mới"}}, "review": {"status": "pass"}},
        {"definition": {"metric": {"name": "Đơn chờ duyệt"}}, "proposal_id": proposal_pending.id},
        {"definition": {"metric": {"name": "Đơn đã duyệt"}}, "proposal_id": proposal_approved.id},
        {"definition": {"metric": {"name": "Đơn bị từ chối"}}, "proposal_id": proposal_rejected.id},
    ]
    await save_chat_message(
        async_session,
        session.id,
        "assistant",
        "Đề xuất chỉ số",
        intent="metric_suggestion",
        metadata_json={"suggestions": suggestions, "status": "completed"},
    )
    await async_session.commit()

    response = await client.get(f"/api/v1/semantic/{chat_database}/chat/sessions/{session.id}", headers=auth_headers)

    assert response.status_code == 200
    messages = response.json()["messages"]
    payload = messages[-1]["metadata_json"]["suggestions"]
    assert payload[0]["lifecycle"] is None
    assert payload[1]["lifecycle"] == {
        "metric_id": pending.id,
        "metric_status": "pending_approval",
        "rejection_reason": None,
    }
    assert payload[2]["lifecycle"] == {
        "metric_id": approved.id,
        "metric_status": "approved",
        "rejection_reason": None,
    }
    assert payload[3]["lifecycle"] == {
        "metric_id": None,
        "metric_status": None,
        "rejection_reason": "Thiếu căn cứ nghiệp vụ",
    }
    assert payload[1]["proposal_id"] == proposal_pending.id
