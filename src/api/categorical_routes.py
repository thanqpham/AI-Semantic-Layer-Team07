"""Authorize review of sampled categorical values separately from schema metadata."""

from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user
from src.api.routes import _require_resource_permission
from src.config import get_settings
from src.models.db import LiveTargetDbModel, SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel
from src.models.db_categorical_proposals import ColumnValueProposalModel
from src.services.categorical_proposals import proposal_fingerprint, queue_discovery
from src.services.database import get_db_session, lock_semantic_database

categorical_router = APIRouter(tags=["categorical review"])


class ProposalDecision(BaseModel):
    """One atomic review action over pending proposals."""

    proposal_ids: list[int] = Field(min_length=1, max_length=100)
    action: Literal["approve", "dismiss"]


class DiscoverySettings(BaseModel):
    """Require an explicit opt-in for each live connection."""

    enabled: bool


@categorical_router.get("/semantic/{db_id}/column-value-proposals")
async def list_proposals(db_id: int, org_id: int | None = Header(default=None, alias="X-Organization-ID"),
                         user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)) -> dict:
    """List non-stale pending proposals for one authorized database."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    database = await db.get(SemanticDatabaseModel, db_id)
    rows = await _proposal_rows(db, db_id)
    live = await _live_connection(db, db_id)
    return {"enabled": bool(live and live.categorical_discovery_enabled),
            "available": bool(live and live.dialect in {"postgres", "postgresql"} and get_settings().categorical_discovery_enabled),
            "items": [_proposal_payload(p, t, c) for p, t, c in rows
                      if p.status == "pending" and p.schema_fingerprint == proposal_fingerprint(database, t, c)]}


@categorical_router.put("/semantic/{db_id}/column-value-proposals/settings")
async def update_settings(db_id: int, body: DiscoverySettings,
                          org_id: int | None = Header(default=None, alias="X-Organization-ID"),
                          user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)) -> dict:
    """Enable or disable observation for one authorized Live DB."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    live = await _live_connection(db, db_id)
    if live is None or live.dialect not in {"postgres", "postgresql"}:
        raise HTTPException(status_code=409, detail="Discovery is unavailable for this connection")
    live.categorical_discovery_enabled = body.enabled
    await db.commit()
    return {"enabled": body.enabled}


@categorical_router.post("/semantic/{db_id}/column-value-proposals/scan")
async def start_scan(db_id: int, org_id: int | None = Header(default=None, alias="X-Organization-ID"),
                     user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)) -> dict:
    """Queue a bounded scan if the administrator has enabled discovery."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    live = await _live_connection(db, db_id)
    if live is None or not live.categorical_discovery_enabled or live.dialect not in {"postgres", "postgresql"}:
        raise HTTPException(status_code=409, detail="Discovery is disabled or unavailable for this connection")
    if not queue_discovery(db_id, refresh_dismissed=True):
        raise HTTPException(status_code=409, detail="Categorical discovery is disabled")
    return {"status": "queued"}


@categorical_router.post("/semantic/{db_id}/column-value-proposals/review")
async def review_proposals(db_id: int, body: ProposalDecision,
                           org_id: int | None = Header(default=None, alias="X-Organization-ID"),
                           user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)) -> dict:
    """Approve or dismiss pending proposals atomically after checking freshness."""
    await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    await lock_semantic_database(db, db_id)
    database = await db.get(SemanticDatabaseModel, db_id)
    rows = [row for row in await _proposal_rows(db, db_id) if row[0].id in body.proposal_ids]
    if len(rows) != len(set(body.proposal_ids)) or any(
        p.status != "pending" or p.schema_fingerprint != proposal_fingerprint(database, t, c) for p, t, c in rows
    ):
        raise HTTPException(status_code=409, detail="Proposal is stale or unavailable")
    for proposal, _, column in rows:
        proposal.status = "approved" if body.action == "approve" else "dismissed"
        proposal.reviewed_by = user.id
        if body.action == "approve":
            column.allowed_values = list(proposal.values)
            column.allowed_values_complete = proposal.source == "declared"
    await db.commit()
    return {"updated": len(rows)}


async def _proposal_rows(db: AsyncSession, db_id: int) -> list:
    stmt = (select(ColumnValueProposalModel, SemanticTableModel, SemanticColumnModel)
            .join(SemanticColumnModel, ColumnValueProposalModel.column_id == SemanticColumnModel.id)
            .join(SemanticTableModel, SemanticColumnModel.table_id == SemanticTableModel.id)
            .where(SemanticTableModel.db_id == db_id))
    return list((await db.execute(stmt)).all())


async def _live_connection(db: AsyncSession, db_id: int) -> LiveTargetDbModel | None:
    return await db.scalar(select(LiveTargetDbModel).where(LiveTargetDbModel.semantic_db_id == db_id))


def _proposal_payload(proposal: ColumnValueProposalModel, table: SemanticTableModel, column: SemanticColumnModel) -> dict:
    return {"id": proposal.id, "column_id": column.id, "table_name": table.table_name,
            "physical_schema": table.physical_schema, "column_name": column.column_name,
            "source": proposal.source, "status": proposal.status, "values": proposal.values,
            "observed_at": proposal.observed_at}
