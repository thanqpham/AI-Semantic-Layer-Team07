"""Authorize review of sampled categorical values separately from schema metadata."""

import asyncio
import hashlib
import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user
from src.api.routes import _require_resource_permission
from src.config import get_settings
from src.models.db import LiveTargetDbModel, SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel
from src.models.db_categorical_proposals import ColumnValueProposalModel
from src.services.categorical_proposals import proposal_fingerprint
from src.services.database import get_db_session, lock_semantic_database
from src.services.value_mapping_import import parse_value_mapping_batch, parse_value_mapping_file

categorical_router = APIRouter(tags=["categorical review"])


class ValueMapping(BaseModel):
    """Approved manual meaning for one database value."""

    db_value: str | int | float | bool
    business_value: str = Field(max_length=200)


class ValueMappingsUpdate(BaseModel):
    """Replace the managed mappings for one semantic column."""

    items: list[ValueMapping] = Field(max_length=100)
    complete: bool = False
    version: str


class ValueMappingsDecision(BaseModel):
    """Approve or dismiss pending value meanings by their database values."""

    db_values: list[str | int | float | bool] = Field(max_length=100)
    items: list[ValueMapping] | None = Field(default=None, max_length=100)
    complete: bool | None = None
    action: Literal["approve", "dismiss"]
    version: str


@categorical_router.post("/semantic/{db_id}/columns/{column_id}/value-mappings/preview")
async def preview_value_mappings(
    db_id: int,
    column_id: int,
    request: Request,
    file_type: Literal["json", "csv", "xlsx"],
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Preview a bounded mapping file for an authorized column."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    if await _semantic_column(db, db_id, column_id) is None:
        raise HTTPException(status_code=404, detail="Column not found")
    content = await _read_import_content(request)
    try:
        items = await asyncio.to_thread(parse_value_mapping_file, content, file_type, db_id, column_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"items": items}


@categorical_router.post("/semantic/{db_id}/value-mappings/preview")
async def preview_value_mapping_batch(
    db_id: int,
    request: Request,
    file_type: Literal["json", "csv", "xlsx"],
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Preview file mappings for columns in one authorized database."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    content = await _read_import_content(request)
    try:
        groups = await asyncio.to_thread(parse_value_mapping_batch, content, file_type, db_id)
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    stmt = (
        select(SemanticColumnModel.id)
        .join(SemanticTableModel)
        .where(SemanticTableModel.db_id == db_id, SemanticColumnModel.id.in_(groups))
    )
    if set((await db.scalars(stmt)).all()) != set(groups):
        raise HTTPException(status_code=422, detail="File contains columns outside this database")
    return {"columns": [{"column_id": key, "items": items} for key, items in groups.items()]}


async def _read_import_content(request: Request) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 2_000_000:
            raise HTTPException(status_code=413, detail="File exceeds 2 MB")
    return bytes(content)


@categorical_router.get("/semantic/{db_id}/columns/{column_id}/value-mappings")
async def get_value_mappings(
    db_id: int,
    column_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Read saved value meanings for one authorized semantic column."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    column = await _semantic_column(db, db_id, column_id)
    if column is None:
        raise HTTPException(status_code=404, detail="Column not found")
    return {
        "column_id": column.id,
        "items": _existing_mappings(column),
        "complete": bool(
            column.allowed_values
            and column.allowed_values_complete
            and all(item.get("status") != "pending" for item in _existing_mappings(column))
        ),
        "version": _mappings_version(column),
    }


class ProposalDecision(BaseModel):
    """One atomic review action over pending proposals."""

    proposal_ids: list[int] = Field(min_length=1, max_length=100)
    action: Literal["approve", "dismiss"]


class DiscoverySettings(BaseModel):
    """Require an explicit opt-in for each live connection."""

    enabled: bool


@categorical_router.get("/semantic/{db_id}/column-value-proposals")
async def list_proposals(
    db_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """List non-stale pending proposals for one authorized database."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    database = await db.get(SemanticDatabaseModel, db_id)
    rows = await _proposal_rows(db, db_id)
    live = await _live_connection(db, db_id)
    return {
        "enabled": bool(live and live.categorical_discovery_enabled),
        "available": bool(
            live and live.dialect in {"postgres", "postgresql"} and get_settings().categorical_discovery_enabled
        ),
        "items": [
            _proposal_payload(p, t, c)
            for p, t, c in rows
            if p.source == "declared"
            and p.status == "pending"
            and p.schema_fingerprint == proposal_fingerprint(database, t, c)
        ],
    }


@categorical_router.put("/semantic/{db_id}/column-value-proposals/settings")
async def update_settings(
    db_id: int,
    body: DiscoverySettings,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Enable or disable observation for one authorized Live DB."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    raise HTTPException(status_code=410, detail="Row-value discovery is disabled")


@categorical_router.put("/semantic/{db_id}/columns/{column_id}/value-mappings")
async def update_value_mappings(
    db_id: int,
    column_id: int,
    body: ValueMappingsUpdate,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Save manually approved value meanings without querying the target database."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    await lock_semantic_database(db, db_id)
    column = await _semantic_column(db, db_id, column_id)
    if column is None:
        raise HTTPException(status_code=404, detail="Column not found")
    _require_current_version(column, body.version)
    _replace_value_mappings(column, body)
    await db.commit()
    return {
        "column_id": column.id,
        "items": column.allowed_value_mappings,
        "complete": column.allowed_values_complete,
        "version": _mappings_version(column),
    }


def _replace_value_mappings(column: SemanticColumnModel, body: ValueMappingsUpdate) -> None:
    values = [item.db_value for item in body.items]
    if len(set((type(value).__name__, str(value)) for value in values)) != len(values):
        raise HTTPException(status_code=422, detail="Database values must be unique")
    old = {
        (_value_key(item.get("db_value")), item.get("business_value")): item
        for item in _existing_mappings(column)
        if item.get("status") != "dismissed"
    }
    if any(
        not item.business_value.strip() and (_value_key(item.db_value), item.business_value) not in old
        for item in body.items
    ):
        raise HTTPException(status_code=422, detail="Business value is required")
    column.allowed_value_mappings = [
        old.get(
            (_value_key(item.db_value), item.business_value),
            {
                "db_value": item.db_value,
                "business_value": item.business_value,
                "source": "manual",
                "status": "pending",
            },
        )
        for item in body.items
    ]
    column.allowed_values = _approved_values(column.allowed_value_mappings)
    column.allowed_values_complete = (
        body.complete
        and bool(column.allowed_value_mappings)
        and all(item["status"] == "approved" for item in column.allowed_value_mappings)
    )


def _existing_mappings(column: SemanticColumnModel) -> list[dict]:
    if column.allowed_value_mappings is not None:
        return column.allowed_value_mappings
    return [
        {
            "db_value": value,
            "business_value": "",
            "source": "legacy",
            "status": "approved" if column.review_status == "approved" else "pending",
        }
        for value in column.allowed_values or []
    ]


def _mappings_version(column: SemanticColumnModel) -> str:
    payload = [
        column.allowed_values,
        column.allowed_value_mappings,
        column.allowed_values_complete,
        column.review_status,
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _require_current_version(column: SemanticColumnModel, version: str) -> None:
    if version != _mappings_version(column):
        raise HTTPException(status_code=409, detail="Values changed; reload before saving or reviewing")


@categorical_router.post("/semantic/{db_id}/columns/{column_id}/value-mappings/review")
async def review_value_mappings(
    db_id: int,
    column_id: int,
    body: ValueMappingsDecision,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Approve or dismiss mappings only for users allowed to approve schema values."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    await lock_semantic_database(db, db_id)
    column = await _semantic_column(db, db_id, column_id)
    if column is None:
        raise HTTPException(status_code=404, detail="Column not found")
    _require_current_version(column, body.version)
    if body.items is not None:
        await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
        if body.action != "approve" or body.complete is None or not body.items:
            raise HTTPException(status_code=422, detail="Approval requires values and a list scope")
        if any(item.get("status") == "dismissed" for item in _existing_mappings(column)):
            raise HTTPException(status_code=409, detail="Dismissed values cannot be replaced")
        _replace_value_mappings(column, ValueMappingsUpdate(items=body.items, version=body.version))
        selected = {_value_key(item["db_value"]) for item in column.allowed_value_mappings if item["status"] == "pending"}
    else:
        if not body.db_values or body.complete is not None:
            raise HTTPException(status_code=422, detail="Select values to review")
        selected = {_value_key(value) for value in body.db_values}
    updated = 0
    mappings = [dict(item) for item in column.allowed_value_mappings or []]
    for item in mappings:
        if _value_key(item["db_value"]) in selected and item["status"] == "pending":
            if body.action == "approve" and not item["business_value"].strip():
                raise HTTPException(status_code=422, detail="Business value is required before approval")
            item["status"] = "approved" if body.action == "approve" else "dismissed"
            item["reviewed_by"] = user.id
            updated += 1
    if updated != len(selected):
        raise HTTPException(status_code=409, detail="A selected value is unavailable or already reviewed")
    column.allowed_value_mappings = mappings
    column.allowed_values = _approved_values(mappings)
    if body.items is not None:
        column.allowed_values_complete = bool(body.complete and mappings and all(item["status"] == "approved" for item in mappings))
    await db.commit()
    return {"updated": updated, "version": _mappings_version(column)}


async def _semantic_column(db: AsyncSession, db_id: int, column_id: int) -> SemanticColumnModel | None:
    return await db.scalar(
        select(SemanticColumnModel)
        .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
        .where(SemanticTableModel.db_id == db_id, SemanticColumnModel.id == column_id)
    )


def _value_key(value: Any) -> tuple[str, str]:
    return type(value).__name__, str(value)


def _approved_values(items: list[dict]) -> list | None:
    values = [item["db_value"] for item in items if item.get("status") == "approved"]
    return values or None


@categorical_router.post("/semantic/{db_id}/column-value-proposals/scan")
async def start_scan(
    db_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Queue a bounded scan if the administrator has enabled discovery."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    raise HTTPException(
        status_code=410, detail="Row-value discovery is disabled; configure values manually or use schema metadata"
    )


@categorical_router.post("/semantic/{db_id}/column-value-proposals/review")
async def review_proposals(
    db_id: int,
    body: ProposalDecision,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Approve or dismiss pending proposals atomically after checking freshness."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    await lock_semantic_database(db, db_id)
    database = await db.get(SemanticDatabaseModel, db_id)
    rows = [row for row in await _proposal_rows(db, db_id) if row[0].id in body.proposal_ids]
    if len(rows) != len(set(body.proposal_ids)) or any(
        p.source != "declared" or p.status != "pending" or p.schema_fingerprint != proposal_fingerprint(database, t, c)
        for p, t, c in rows
    ):
        raise HTTPException(status_code=409, detail="Proposal is stale or unavailable")
    for proposal, _, column in rows:
        proposal.status = "approved" if body.action == "approve" else "dismissed"
        proposal.reviewed_by = user.id
        if body.action == "approve" and column.allowed_value_mappings is None and column.allowed_values is None:
            column.allowed_value_mappings = [
                {
                    "db_value": value,
                    "business_value": "",
                    "source": "declared",
                    "status": "approved",
                    "reviewed_by": user.id,
                }
                for value in proposal.values
            ]
            column.allowed_values = list(proposal.values)
            column.allowed_values_complete = proposal.source == "declared"
    await db.commit()
    return {"updated": len(rows)}


async def _proposal_rows(db: AsyncSession, db_id: int) -> list:
    stmt = (
        select(ColumnValueProposalModel, SemanticTableModel, SemanticColumnModel)
        .join(SemanticColumnModel, ColumnValueProposalModel.column_id == SemanticColumnModel.id)
        .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
        .where(SemanticTableModel.db_id == db_id)
    )
    return list((await db.execute(stmt)).all())


async def _live_connection(db: AsyncSession, db_id: int) -> LiveTargetDbModel | None:
    return await db.scalar(select(LiveTargetDbModel).where(LiveTargetDbModel.semantic_db_id == db_id))


def _proposal_payload(
    proposal: ColumnValueProposalModel, table: SemanticTableModel, column: SemanticColumnModel
) -> dict:
    return {
        "id": proposal.id,
        "column_id": column.id,
        "table_name": table.table_name,
        "physical_schema": table.physical_schema,
        "column_name": column.column_name,
        "source": proposal.source,
        "status": proposal.status,
        "values": proposal.values,
        "observed_at": proposal.observed_at,
    }
