"""Idempotent sync of schema/metrics pending-review notifications."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    NotificationModel,
    OrganizationMemberModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
)
from src.services.notification_bus import publish
from src.services.schema_review_service import pending_review_counts


async def sync_schema_review_notifications(db: AsyncSession, db_id: int) -> None:
    """Create or resolve the schema-review notification of one database."""
    counts = await pending_review_counts(db, db_id)
    body = (
        f"{counts['pending_tables']} bảng, {counts['pending_columns']} cột, {counts['pending_relationships']} quan hệ"
    )
    await _sync(db, db_id, "schema_review_submitted", "Có đề xuất schema chờ duyệt", body, sum(counts.values()))


async def sync_metrics_pending_notifications(db: AsyncSession, db_id: int) -> None:
    """Create or resolve the metrics-pending-approval notification of one database."""
    pending = await _pending_metric_count(db, db_id)
    await _sync(db, db_id, "metrics_pending_approval", "Có chỉ số chờ duyệt", f"{pending} chỉ số", pending)


async def _pending_metric_count(db: AsyncSession, db_id: int) -> int:
    """Count not-deleted, not-yet-approved metrics of one database."""
    stmt = (
        select(func.count())
        .select_from(SemanticMetricModel)
        .where(
            SemanticMetricModel.db_id == db_id,
            SemanticMetricModel.is_deleted.is_(False),
            SemanticMetricModel.status != "approved",
        )
    )
    return int(await db.scalar(stmt) or 0)


async def _sync(db: AsyncSession, db_id: int, type_: str, title: str, body: str, pending: int) -> None:
    """Reconcile active notification rows of one type; publish after commit."""
    active = list(
        (
            await db.execute(
                select(NotificationModel).where(
                    NotificationModel.type == type_,
                    NotificationModel.db_id == db_id,
                    NotificationModel.handled_at.is_(None),
                )
            )
        ).scalars()
    )
    if pending > 0 and not active:
        recipients = await _create_for_leads(db, db_id, type_, title, body)
    elif pending == 0 and active:
        recipients = _mark_handled(active)
    else:
        return
    if not recipients:
        return
    await db.commit()
    publish(recipients)


async def _create_for_leads(db: AsyncSession, db_id: int, type_: str, title: str, body: str) -> list[int]:
    """Add one notification per workspace data lead and return their ids."""
    recipients = await _data_lead_ids(db, db_id)
    for recipient_id in recipients:
        db.add(NotificationModel(recipient_id=recipient_id, type=type_, title=title, body=body, db_id=db_id))
    return recipients


def _mark_handled(active: list[NotificationModel]) -> list[int]:
    """Mark every active row handled (and read); return recipient ids."""
    now = datetime.now(UTC)
    for row in active:
        row.handled_at = now
        row.read_at = row.read_at or now
    return [row.recipient_id for row in active]


async def _data_lead_ids(db: AsyncSession, db_id: int) -> list[int]:
    """Return every Data Lead user id of the workspace owning the database."""
    stmt = (
        select(OrganizationMemberModel.user_id)
        .join(SemanticDatabaseModel, SemanticDatabaseModel.org_id == OrganizationMemberModel.org_id)
        .where(SemanticDatabaseModel.id == db_id, OrganizationMemberModel.role == "data_lead")
    )
    return list((await db.execute(stmt)).scalars())
