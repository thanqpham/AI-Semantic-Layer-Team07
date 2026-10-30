"""End-to-end pin of the existing metric reject route over the new reject behavior."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_access_token
from src.models.db import MetricProposalModel, NotificationModel, SemanticMetricModel, UserModel
from src.services.metric_service import approve_metric, update_metric
from tests.test_services.test_metric_reject import (
    _manual_definition,
    _seed_ai_metric_with_proposal,
    _seed_manual_metric,
)


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer token for the seeded owner user (id=1)."""
    user = UserModel(id=1, email="test@company.com", username="tester", hashed_password="hash")
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.mark.asyncio
async def test_reject_route_rejects_metric_releases_proposal_and_handles_bell(
    client, auth_headers, async_session: AsyncSession
) -> None:
    """POST reject on a pending AI metric rejects it, frees the proposal, grays the bell."""
    db_id, metric_id, proposal_id = await _seed_ai_metric_with_proposal(async_session)
    async_session.add(
        NotificationModel(
            recipient_id=1,
            type="metrics_pending_approval",
            title="Có chỉ số chờ duyệt",
            body="1 chỉ số",
            db_id=db_id,
        )
    )
    await async_session.commit()

    response = await client.post(
        f"/api/v1/semantic/{db_id}/metric/{metric_id}/reject",
        json={"reason": "Thiếu căn cứ nghiệp vụ"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["change_reason"] == "[Từ chối] Thiếu căn cứ nghiệp vụ"
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric.status == "rejected"
    proposal = await async_session.get(MetricProposalModel, proposal_id)
    assert proposal.metric_id is None
    assert proposal.rejection_reason == "Thiếu căn cứ nghiệp vụ"
    notification = (await async_session.execute(select(NotificationModel))).scalar_one()
    assert notification.handled_at is not None


@pytest.mark.asyncio
async def test_reject_route_blank_reason_returns_422(client, auth_headers, async_session: AsyncSession) -> None:
    """A whitespace-only reason is a 422, not a silent success."""
    db_id, metric_id = await _seed_manual_metric(async_session)

    response = await client.post(
        f"/api/v1/semantic/{db_id}/metric/{metric_id}/reject",
        json={"reason": "   "},
        headers=auth_headers,
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reject_route_metric_of_other_database_returns_404(
    client, auth_headers, async_session: AsyncSession
) -> None:
    """A metric id from another database is a 404, not a cross-database reject."""
    _db_a, metric_id = await _seed_manual_metric(async_session, name="Doanh thu A", source_id=1)
    db_b, _other = await _seed_manual_metric(async_session, name="Doanh thu B", source_id=2)

    response = await client.post(
        f"/api/v1/semantic/{db_b}/metric/{metric_id}/reject",
        json={"reason": "Sai phạm vi"},
        headers=auth_headers,
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reject_route_published_edit_draft_keeps_metric_approved(
    client, auth_headers, async_session: AsyncSession
) -> None:
    """Rejecting an edit draft of an approved metric leaves the live metric approved."""
    db_id, metric_id = await _seed_manual_metric(async_session)
    await approve_metric(db=async_session, metric_id=metric_id, user_id=1)
    await update_metric(
        db=async_session,
        metric_id=metric_id,
        metric_data={"definition": _manual_definition("Doanh thu thuần"), "change_reason": "Đổi công thức"},
        user_id=1,
    )
    await async_session.commit()

    response = await client.post(
        f"/api/v1/semantic/{db_id}/metric/{metric_id}/reject",
        json={"reason": "Chưa khớp tài chính"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric.status == "approved"
