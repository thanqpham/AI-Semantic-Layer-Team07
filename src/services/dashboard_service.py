"""Singleton dashboard layout persistence with optimistic concurrency."""

from __future__ import annotations

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    DashboardLayoutModel,
    OrganizationMemberModel,
    OrganizationModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.metric_definition import MetricDefinition
from src.models.schemas import (
    DashboardLayout,
    DashboardLayoutResponse,
    DashboardSaveRequest,
    DashboardWidgetConfig,
    DimensionSelection,
    SemanticQueryFilter,
    SemanticQuerySpec,
)
from src.services.organization_service import require_permission, resolve_membership
from src.services.query_compiler import SemanticQueryCompiler
from src.services.semantic_compile_error import SemanticCompileError


class DashboardNotFoundError(Exception):
    """Raised when the dashboard resource is missing or masked in the requested scope."""


class DashboardAuthorizationError(Exception):
    """Raised when the caller may not read or mutate the shared dashboard."""


class DashboardValidationError(Exception):
    """Raised when layout references do not belong to the semantic database."""


class DashboardVersionConflictError(Exception):
    """Raised when expected_version does not match the persisted singleton version."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"Dashboard version conflict: current version is {current_version}")


async def get_dashboard_layout(
    db: AsyncSession, user_id: int, db_id: int, org_id: int | None = None
) -> DashboardLayoutResponse:
    """Return the singleton layout or an empty version-0 response."""
    database = await _resolve_database(db, user_id, db_id, org_id)
    row = await db.scalar(select(DashboardLayoutModel).where(DashboardLayoutModel.db_id == database.id))
    if row is None:
        return DashboardLayoutResponse(db_id=database.id)
    return _to_response(row)


async def save_dashboard_layout(
    db: AsyncSession, user_id: int, db_id: int, request: DashboardSaveRequest, org_id: int | None = None
) -> DashboardLayoutResponse:
    """Create or update the singleton layout guarded by optimistic concurrency."""
    database = await _resolve_database(db, user_id, db_id, org_id)
    await _validate_references(db, database.id, request.layout)
    existing = await _select_singleton(db, database.id)
    if existing is None:
        return await _create_singleton(db, user_id, database.id, request)
    return await _update_singleton(db, user_id, existing, request)


async def _resolve_database(db: AsyncSession, user_id: int, db_id: int, org_id: int | None) -> SemanticDatabaseModel:
    """Resolve a database with canonical scoping regardless of any org header.

    Personal databases stay creator-only even when X-Organization-ID is present;
    workspace databases mask foreign workspaces as missing and require can_query.
    """
    database = await db.get(SemanticDatabaseModel, db_id)
    if database is None:
        raise DashboardNotFoundError("Semantic database not found")
    organization, membership = await _resolve_active_membership(db, user_id, org_id)
    if database.org_id is not None and database.org_id != organization.id:
        raise DashboardNotFoundError("Semantic database not found")
    if database.org_id is None:
        if database.created_by != user_id:
            raise DashboardNotFoundError("Semantic database not found")
        return database
    try:
        require_permission(membership, "can_query")
    except PermissionError as exc:
        raise DashboardAuthorizationError("Insufficient Workspace permission") from exc
    return database


async def _resolve_active_membership(
    db: AsyncSession, user_id: int, org_id: int | None
) -> tuple[OrganizationModel, OrganizationMemberModel]:
    """Resolve the active Workspace, falling back to the user's single membership."""
    try:
        return await resolve_membership(db, user_id, org_id)
    except PermissionError as exc:
        raise DashboardAuthorizationError(str(exc)) from exc
    except ValueError as exc:
        raise DashboardAuthorizationError(str(exc)) from exc


def _collect_reference_ids(layout: DashboardLayout) -> tuple[set[int], set[int]]:
    """Collect metric and column IDs referenced by the layout widgets."""
    metric_ids = {metric_id for widget in layout.widgets for metric_id in (widget.metric_ids or [widget.metric_id])}
    column_ids = {
        column_id
        for widget in layout.widgets
        for column_id in (widget.dimension_col_id, widget.date_filter_column_id)
        if column_id is not None
    }
    return metric_ids, column_ids


async def _validate_references(db: AsyncSession, db_id: int, layout: DashboardLayout) -> None:
    """Ensure every referenced metric and column belongs to the semantic database."""
    metric_ids, column_ids = _collect_reference_ids(layout)
    if metric_ids:
        await _validate_metrics(db, db_id, metric_ids)
    if column_ids:
        await _validate_columns(db, db_id, column_ids)
    for widget in layout.widgets:
        if widget.metric_ids:
            await _validate_metric_widget_plan(db, db_id, widget)


async def _validate_metrics(db: AsyncSession, db_id: int, metric_ids: set[int]) -> None:
    """Reject missing, cross-database, or non-approved metric references."""
    stmt = select(SemanticMetricModel.id).where(
        SemanticMetricModel.db_id == db_id,
        SemanticMetricModel.id.in_(metric_ids),
        SemanticMetricModel.status == "approved",
    )
    found = set((await db.execute(stmt)).scalars().all())
    rejected = sorted(metric_ids - found)
    if rejected:
        raise DashboardValidationError(f"Metrics are missing, cross-database, or not approved: {rejected}")


async def _validate_metric_widget_plan(db: AsyncSession, db_id: int, widget: DashboardWidgetConfig) -> None:
    metric_ids = widget.metric_ids or []
    records = await db.execute(
        select(SemanticMetricModel).where(
            SemanticMetricModel.db_id == db_id,
            SemanticMetricModel.id.in_(metric_ids),
            SemanticMetricModel.is_deleted.is_(False),
        )
    )
    metric_records = list(records.scalars().all())
    if len(metric_records) != len(metric_ids) or any(record.definition is None for record in metric_records):
        raise DashboardValidationError("Multi-metric widgets require approved query-plan metrics")
    try:
        definitions = [MetricDefinition.model_validate(record.definition) for record in metric_records]
    except ValidationError as exc:
        raise DashboardValidationError("Multi-metric widget contains an invalid metric definition") from exc
    if any(item.metric.query_plan is None for item in definitions):
        raise DashboardValidationError("Multi-metric widgets require approved query-plan metrics")
    await _compile_widget_plan(db, db_id, widget)


async def _compile_widget_plan(db: AsyncSession, db_id: int, widget: DashboardWidgetConfig) -> None:
    dimensions = []
    if widget.dimension_col_id is not None:
        dimensions = [DimensionSelection(column_id=widget.dimension_col_id, time_grain=widget.time_grain)]
    filters = []
    if widget.date_filter_column_id is not None:
        filters = [
            SemanticQueryFilter(
                column_id=widget.date_filter_column_id,
                operator="is_not_null",
                value=None,
            )
        ]
    spec = SemanticQuerySpec(
        metric_ids=widget.metric_ids or [],
        dimensions=dimensions,
        filters=filters,
        limit=100,
        order_by="metric_desc" if widget.chart_type in ("bar", "table") else None,
        order_metric_id=widget.order_metric_id,
    )
    try:
        await SemanticQueryCompiler(db).compile(db_id, spec)
    except SemanticCompileError as exc:
        raise DashboardValidationError(f"Incompatible widget metric plans or filters ({exc.code}): {exc}") from exc


async def _validate_columns(db: AsyncSession, db_id: int, column_ids: set[int]) -> None:
    """Reject column references outside the semantic database."""
    stmt = (
        select(SemanticColumnModel.id)
        .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
        .where(SemanticTableModel.db_id == db_id, SemanticColumnModel.id.in_(column_ids))
    )
    found = set((await db.execute(stmt)).scalars().all())
    rejected = sorted(column_ids - found)
    if rejected:
        raise DashboardValidationError(f"Columns do not belong to the semantic database: {rejected}")


async def _select_singleton(db: AsyncSession, db_id: int) -> DashboardLayoutModel | None:
    """Select the singleton row for update where the backend supports locking."""
    stmt = select(DashboardLayoutModel).where(DashboardLayoutModel.db_id == db_id).with_for_update()
    return (await db.execute(stmt)).scalar_one_or_none()


async def _create_singleton(
    db: AsyncSession, user_id: int, db_id: int, request: DashboardSaveRequest
) -> DashboardLayoutResponse:
    """Insert the singleton at stored version 1 and map insert races to conflicts."""
    if request.expected_version != 0:
        raise DashboardVersionConflictError(0)
    row = DashboardLayoutModel(
        db_id=db_id,
        layout_json=request.layout.model_dump(),
        version=request.expected_version + 1,
        updated_by=user_id,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raced = await _select_singleton(db, db_id)
        raise DashboardVersionConflictError(raced.version if raced else 0) from exc
    await db.refresh(row)
    return _to_response(row)


async def _update_singleton(
    db: AsyncSession, user_id: int, row: DashboardLayoutModel, request: DashboardSaveRequest
) -> DashboardLayoutResponse:
    """Persist a new layout only when expected_version matches the stored version."""
    if request.expected_version < 1 or row.version != request.expected_version:
        raise DashboardVersionConflictError(row.version)
    row.layout_json = request.layout.model_dump()
    row.version = request.expected_version + 1
    row.updated_by = user_id
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


def _to_response(row: DashboardLayoutModel) -> DashboardLayoutResponse:
    """Map the persisted singleton row onto the API response contract."""
    return DashboardLayoutResponse(
        db_id=row.db_id,
        layout=DashboardLayout.model_validate(row.layout_json),
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )
