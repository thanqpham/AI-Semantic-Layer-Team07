"""Reject flow for unpublished AI metrics: rejected status, proposal release, dedupe exemptions."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    MetricProposalModel,
    NotificationModel,
    SemanticColumnModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.services.metric_dedupe import dedupe_reviewed_suggestions
from src.services.metric_service import (
    _ensure_unique_metric_name,
    approve_metric,
    create_metric,
    reject_metric_update,
    update_metric,
)
from src.services.review_notifications import sync_metrics_pending_notifications
from src.services.semantic_service import ensure_semantic_database
from tests.metric_review_helpers import definition, seed_proposal


async def _seed_db(db: AsyncSession, source_id: int = 1) -> int:
    """Create one semantic database (unique per source_id) for the test."""
    return await ensure_semantic_database(
        db=db,
        source_type="live_target",
        source_id=source_id,
        user_id=1,
        display_name="Reject DB",
        dialect="postgresql",
    )


async def _seed_orders_table(db: AsyncSession, db_id: int) -> None:
    """Seed the orders table referenced by manual metric definitions."""
    table = SemanticTableModel(db_id=db_id, table_name="orders", business_name="Đơn hàng", primary_key_column="id")
    db.add(table)
    await db.flush()
    db.add(
        SemanticColumnModel(
            table_id=table.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
        )
    )
    db.add(SemanticColumnModel(table_id=table.id, column_name="total", data_type="NUMERIC", business_name="Tổng"))
    await db.flush()


def _manual_definition(name: str) -> dict:
    """Build a manual metric payload with the given name."""
    payload = definition(name=name)
    payload["metric"]["formula"]["expression"] = "total"
    return payload


async def _seed_ai_metric_with_proposal(db: AsyncSession, source_id: int = 1) -> tuple[int, int, str]:
    """Create a pending AI metric linked to a passing proposal."""
    db_id = await _seed_db(db, source_id)
    proposal = await seed_proposal(db, db_id, 1)
    metric = await create_metric(
        db=db,
        connection_id=db_id,
        metric_data={"source": "ai", "proposal_id": proposal.id, "definition": definition()},
        user_id=1,
    )
    return db_id, metric.id, proposal.id


async def _seed_manual_metric(db: AsyncSession, name: str = "Doanh thu", source_id: int = 1) -> tuple[int, int]:
    """Create a pending manual metric with no proposal."""
    db_id = await _seed_db(db, source_id)
    await _seed_orders_table(db, db_id)
    metric = await create_metric(
        db=db, connection_id=db_id, metric_data={"source": "manual", "definition": _manual_definition(name)}, user_id=1
    )
    return db_id, metric.id


@pytest.mark.asyncio
async def test_reject_unpublished_metric_marks_rejected_and_releases_proposal(async_session: AsyncSession) -> None:
    """Rejecting a never-published AI metric rejects it and releases its proposal."""
    db_id, metric_id, proposal_id = await _seed_ai_metric_with_proposal(async_session)

    record = await reject_metric_update(async_session, metric_id, 1, reason="Thiếu căn cứ nghiệp vụ")

    assert record.status == "rejected"
    assert record.change_reason == "[Từ chối] Thiếu căn cứ nghiệp vụ"
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric.status == "rejected"
    proposal = await async_session.get(MetricProposalModel, proposal_id)
    assert proposal.metric_id is None
    assert proposal.metric_version is None
    assert proposal.rejection_reason == "Thiếu căn cứ nghiệp vụ"


@pytest.mark.asyncio
async def test_reject_published_metric_edit_keeps_current_behavior(async_session: AsyncSession) -> None:
    """Rejecting an edit draft of an approved metric keeps the metric approved and releases nothing."""
    db_id, metric_id = await _seed_manual_metric(async_session)
    await approve_metric(db=async_session, metric_id=metric_id, user_id=1)
    await update_metric(
        db=async_session,
        metric_id=metric_id,
        metric_data={"definition": _manual_definition("Doanh thu thuần"), "change_reason": "Đổi công thức"},
        user_id=1,
    )

    record = await reject_metric_update(async_session, metric_id, 2, reason="Chưa khớp tài chính")

    assert record.status == "rejected"
    assert record.change_reason == "Chưa khớp tài chính"
    metric = await async_session.get(SemanticMetricModel, metric_id)
    assert metric.status == "approved"
    assert (await async_session.execute(select(MetricProposalModel))).scalars().first() is None


@pytest.mark.asyncio
async def test_reject_blank_reason_raises(async_session: AsyncSession) -> None:
    """A whitespace-only rejection reason is rejected by the version gate."""
    _db_id, metric_id = await _seed_manual_metric(async_session)

    with pytest.raises(ValueError, match="Lý do từ chối"):
        await reject_metric_update(async_session, metric_id, 1, reason="   ")


@pytest.mark.asyncio
async def test_reject_manual_metric_without_proposal_is_noop_release(async_session: AsyncSession) -> None:
    """Rejecting a manual metric with no linked proposals succeeds without release work."""
    _db_id, metric_id = await _seed_manual_metric(async_session)

    record = await reject_metric_update(async_session, metric_id, 1, reason="Không dùng nữa")

    assert record.status == "rejected"
    assert (await async_session.execute(select(MetricProposalModel))).scalars().first() is None


@pytest.mark.asyncio
async def test_resave_same_proposal_after_reject_creates_new_metric(async_session: AsyncSession) -> None:
    """After release, saving the same proposal again creates a fresh pending metric."""
    db_id, metric_id, proposal_id = await _seed_ai_metric_with_proposal(async_session)
    await reject_metric_update(async_session, metric_id, 1, reason="Thiếu căn cứ nghiệp vụ")

    new_metric = await create_metric(
        db=async_session,
        connection_id=db_id,
        metric_data={"source": "ai", "proposal_id": proposal_id, "definition": definition()},
        user_id=1,
    )

    assert new_metric.id != metric_id
    assert new_metric.status == "pending_approval"
    proposal = await async_session.get(MetricProposalModel, proposal_id)
    assert proposal.metric_id == new_metric.id
    assert proposal.metric_version == 1
    old_metric = await async_session.get(SemanticMetricModel, metric_id)
    assert old_metric.status == "rejected"


@pytest.mark.asyncio
async def test_unique_metric_name_ignores_rejected(async_session: AsyncSession) -> None:
    """A rejected metric frees its name for a new catalog record."""
    db_id, metric_id = await _seed_manual_metric(async_session)
    metric = await async_session.get(SemanticMetricModel, metric_id)
    metric.status = "rejected"
    await async_session.flush()

    await _ensure_unique_metric_name(async_session, db_id, "Doanh thu")


@pytest.mark.asyncio
async def test_dedupe_keeps_suggestion_matching_rejected_metric(async_session: AsyncSession) -> None:
    """A rejected catalog metric no longer blocks the same formula in new suggestions."""
    db_id, metric_id, _proposal_id = await _seed_ai_metric_with_proposal(async_session)
    await reject_metric_update(async_session, metric_id, 1, reason="Trùng nhu cầu khác")

    state = {"suggested_metrics": [{"definition": definition()}]}
    await dedupe_reviewed_suggestions(async_session, db_id, state)

    assert len(state["suggested_metrics"]) == 1
    assert not state.get("duplicate_notices")


@pytest.mark.asyncio
async def test_pending_metric_count_excludes_rejected(async_session: AsyncSession) -> None:
    """Rejecting the last pending metric grays out the bell notification after sync."""
    db_id, metric_id = await _seed_manual_metric(async_session)
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

    await reject_metric_update(async_session, metric_id, 1, reason="Không còn nhu cầu")
    await sync_metrics_pending_notifications(async_session, db_id)

    row = (await async_session.execute(select(NotificationModel))).scalar_one()
    assert row.handled_at is not None
