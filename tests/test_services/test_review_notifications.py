"""Tests for idempotent schema/metrics pending review notifications."""

import asyncio

import pytest
from sqlalchemy import select

from src.api.auth import create_access_token
from src.models.db import (
    MetricVersionModel,
    NotificationModel,
    OrganizationMemberModel,
    OrganizationModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
    UserModel,
)
from src.services import review_notifications
from src.services.notification_bus import subscribe, unsubscribe

PENDING_COUNTS = {"pending_relationships": 1, "pending_tables": 2, "pending_columns": 3}


async def _fake_pending_counts(db, db_id: int) -> dict[str, int]:
    """Stand-in for the real schema review count query."""
    return PENDING_COUNTS


async def _seed_workspace(db, member_ids: list[int] = ()) -> SemanticDatabaseModel:
    """Create an org-owned semantic database with the given data leads."""
    org = OrganizationModel(name="Org", slug=f"org-{id(db) % 10000}-{len(member_ids)}")
    db.add(org)
    await db.flush()
    database = SemanticDatabaseModel(
        created_by=1, org_id=org.id, display_name="DB", db_type="sqlite", conn_url_enc="enc"
    )
    db.add(database)
    await db.flush()
    for user_id in member_ids:
        db.add(OrganizationMemberModel(org_id=org.id, user_id=user_id, role="data_lead"))
    await db.commit()
    return database


async def _notifications(db) -> list[NotificationModel]:
    return list((await db.execute(select(NotificationModel))).scalars())


@pytest.mark.asyncio
async def test_sync_creates_one_row_per_data_lead_and_publishes_after_commit(async_session, monkeypatch) -> None:
    """Schema sync creates one notification per data lead and wakes streams post-commit."""
    monkeypatch.setattr(review_notifications, "pending_review_counts", _fake_pending_counts)
    database = await _seed_workspace(async_session, member_ids=[11, 12])
    lead_queue = subscribe(11)
    other_queue = subscribe(99)
    try:
        await review_notifications.sync_schema_review_notifications(async_session, database.id)
        rows = await _notifications(async_session)
        assert sorted(r.recipient_id for r in rows) == [11, 12]
        assert all(r.type == "schema_review_submitted" and r.db_id == database.id for r in rows)
        assert all(r.handled_at is None for r in rows)
        # publish fired after commit: rows visible from a fresh query and queues woke.
        assert lead_queue.get_nowait() is None
        with pytest.raises(asyncio.QueueEmpty):
            other_queue.get_nowait()
    finally:
        unsubscribe(11, lead_queue)
        unsubscribe(99, other_queue)


@pytest.mark.asyncio
async def test_sync_is_idempotent_no_duplicate_when_active_exists(async_session, monkeypatch) -> None:
    """Re-running sync while an active notification exists creates no duplicate."""
    monkeypatch.setattr(review_notifications, "pending_review_counts", _fake_pending_counts)
    database = await _seed_workspace(async_session, member_ids=[11])

    await review_notifications.sync_schema_review_notifications(async_session, database.id)
    await review_notifications.sync_schema_review_notifications(async_session, database.id)

    rows = await _notifications(async_session)
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_sync_marks_all_recipients_handled_when_pending_zero(async_session) -> None:
    """Metrics sync grays out every recipient's row once no metric stays pending."""
    database = await _seed_workspace(async_session, member_ids=[11, 12])
    async_session.add(
        SemanticMetricModel(
            db_id=database.id, name="Doanh thu", description="", sql_template="SELECT 1", status="unverified"
        )
    )
    await async_session.commit()

    await review_notifications.sync_metrics_pending_notifications(async_session, database.id)
    metric = (await async_session.execute(select(SemanticMetricModel))).scalar_one()
    metric.status = "approved"
    await async_session.commit()
    await review_notifications.sync_metrics_pending_notifications(async_session, database.id)

    rows = await _notifications(async_session)
    assert len(rows) == 2
    assert all(r.handled_at is not None and r.read_at is not None for r in rows)
    assert all(r.type == "metrics_pending_approval" for r in rows)


@pytest.mark.asyncio
async def test_sync_no_recipients_personal_db_is_noop(async_session, monkeypatch) -> None:
    """A database without an organization has no data leads and no notifications."""
    monkeypatch.setattr(review_notifications, "pending_review_counts", _fake_pending_counts)
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.commit()

    await review_notifications.sync_schema_review_notifications(async_session, database.id)

    assert await _notifications(async_session) == []


@pytest.fixture
def auth_headers() -> dict[str, str]:
    """Bearer token for the seeded owner user (id=1)."""
    user = UserModel(id=1, email="test@company.com", username="tester", hashed_password="hash")
    return {"Authorization": f"Bearer {create_access_token(user)}"}


# ---------------------------------------------------------------------------
# Task 3: wiring — enrichment completion + schema approve endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enrichment_completion_calls_schema_sync(async_session, monkeypatch) -> None:
    """Finishing canonical enrichment wakes the schema-review notification sync."""
    from src.services import semantic_service
    from src.services.semantic_service import ensure_semantic_database
    from tests.test_services.test_semantic_service import _hitl_enrichment, _make_raw_schema

    calls: list[int] = []

    async def fake_sync(db, db_id: int) -> None:
        calls.append(db_id)

    monkeypatch.setattr(semantic_service, "sync_schema_review_notifications", fake_sync)
    sem_db_id = await ensure_semantic_database(
        db=async_session,
        source_type="live_target",
        source_id=1,
        user_id=1,
        display_name="T",
        dialect="postgresql",
    )

    await semantic_service.enrich_and_save_canonical_schema(
        db=async_session,
        user_id=1,
        connection_id=sem_db_id,
        raw_schema=_make_raw_schema(),
        dialect="postgresql",
        enrichment=_hitl_enrichment(),
    )

    assert calls == [sem_db_id]


@pytest.mark.asyncio
async def test_approve_schema_endpoint_marks_notification_handled(client, auth_headers, async_session) -> None:
    """Approving the last pending schema rows grays out the notification via sync."""
    from src.models.db import SemanticTableModel

    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    async_session.add(
        SemanticTableModel(
            db_id=database.id, table_name="orders", business_name="Đơn hàng", review_status="pending_review"
        )
    )
    async_session.add(
        NotificationModel(recipient_id=1, type="schema_review_submitted", title="t", body="b", db_id=database.id)
    )
    await async_session.commit()

    response = await client.post(f"/api/v1/semantic/{database.id}/schema/approve", headers=auth_headers)

    assert response.status_code == 200
    row = (await async_session.execute(select(NotificationModel))).scalar_one()
    assert row.handled_at is not None


# ---------------------------------------------------------------------------
# Final review fixes: metric approval endpoints + database deletion
# ---------------------------------------------------------------------------


async def _seed_pending_metric_with_notification(db, recipient_id: int = 1) -> tuple[int, int]:
    """Create a personal database, one approvable metric, and its bell row."""
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="enc")
    db.add(database)
    await db.flush()
    table = SemanticTableModel(
        db_id=database.id, table_name="orders", business_name="Đơn hàng", primary_key_column="id"
    )
    db.add(table)
    await db.flush()
    db.add(
        SemanticColumnModel(
            table_id=table.id, column_name="total_amount", data_type="NUMERIC", business_name="Tổng tiền"
        )
    )
    db.add(
        SemanticColumnModel(
            table_id=table.id, column_name="id", data_type="INTEGER", business_name="ID", is_primary_key=True
        )
    )
    metric = SemanticMetricModel(
        db_id=database.id,
        name="Total Orders",
        description="Count",
        sql_template="SELECT COUNT(*) FROM orders",
        source="manual",
        formula="COUNT(*)",
        aggregation_type="COUNT",
        definition={
            "metric": {
                "name": "Total Orders",
                "formula": {"function": "COUNT", "expression": "total_amount"},
                "base_entity": "orders",
                "filters": [],
                "status": "pending_approval",
                "confidence": "high",
                "excluded_notes": "",
            }
        },
        status="pending_approval",
        created_by=1,
        version=1,
    )
    db.add(metric)
    await db.flush()
    db.add(MetricVersionModel(metric_id=metric.id, version=1, formula="COUNT(*)", changed_by=1))
    db.add(
        NotificationModel(
            recipient_id=recipient_id,
            type="metrics_pending_approval",
            title="Có chỉ số chờ duyệt",
            body="1 chỉ số",
            db_id=database.id,
        )
    )
    await db.commit()
    return database.id, metric.id


@pytest.mark.asyncio
async def test_bulk_approve_endpoint_marks_notification_handled(client, auth_headers, async_session) -> None:
    """Approving every pending metric via /semantic/approve grays out the bell row."""
    db_id, _ = await _seed_pending_metric_with_notification(async_session)

    response = await client.post("/api/v1/semantic/approve", json={"db_id": db_id}, headers=auth_headers)

    assert response.status_code == 200
    row = (await async_session.execute(select(NotificationModel))).scalar_one()
    assert row.handled_at is not None


@pytest.mark.asyncio
async def test_single_approve_endpoint_marks_notification_handled(client, auth_headers, async_session) -> None:
    """Approving the last pending metric via the single-metric route grays out the bell row."""
    db_id, metric_id = await _seed_pending_metric_with_notification(async_session)

    response = await client.post(
        f"/api/v1/semantic/{db_id}/metric/{metric_id}/approve", headers=auth_headers
    )

    assert response.status_code == 200
    row = (await async_session.execute(select(NotificationModel))).scalar_one()
    assert row.handled_at is not None


@pytest.mark.asyncio
async def test_delete_database_removes_its_notifications(async_session) -> None:
    """Deleting a semantic database drops its notifications so none outlive it."""
    from src.services.semantic_service import delete_semantic_database

    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    async_session.add(
        NotificationModel(
            recipient_id=1, type="metrics_pending_approval", title="t", body="b", db_id=database.id
        )
    )
    await async_session.commit()

    assert await delete_semantic_database(async_session, database.id, user_id=1) is True

    assert await _notifications(async_session) == []
