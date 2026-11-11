"""Review and generate database descriptions."""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user
from src.api.routes import _require_resource_permission
from src.models.db import SemanticDatabaseModel, UserModel, utc_now
from src.services.database import get_db_session, lock_semantic_database
from src.services.database_overview import generate_overview

overview_router = APIRouter(tags=["Database overview"])


class RevisionRequest(BaseModel):
    revision: int = Field(ge=0)


class DraftRequest(RevisionRequest):
    draft_description: str = Field(min_length=1, max_length=2000)

    @field_validator("draft_description")
    @classmethod
    def clean_description(cls, value: str) -> str:
        """Reject whitespace-only descriptions."""
        value = value.strip()
        if not value:
            raise ValueError("Mô tả không được để trống")
        return value


class OverviewResponse(BaseModel):
    description: str | None
    draft_description: str | None
    ai_description: str | None
    revision: int
    reviewed_at: datetime | None
    reviewed_by: int | None


def serialize(record: SemanticDatabaseModel) -> OverviewResponse:
    """Build the public overview representation."""
    return OverviewResponse(
        description=record.description,
        draft_description=record.draft_description,
        ai_description=record.ai_description,
        revision=record.overview_revision,
        reviewed_at=record.overview_reviewed_at,
        reviewed_by=record.overview_reviewed_by,
    )


async def locked(db: AsyncSession, record: SemanticDatabaseModel, revision: int) -> None:
    """Lock and reject stale edits."""
    await lock_semantic_database(db, record.id)
    await db.refresh(record)
    if record.overview_revision != revision:
        raise HTTPException(status_code=409, detail="Mô tả đã thay đổi, vui lòng tải lại")


@overview_router.get("/semantic/{db_id}/overview", response_model=OverviewResponse)
async def get_overview(
    db_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OverviewResponse:
    """Read the database overview."""
    record = await _require_resource_permission(db, user.id, db_id, org_id, "can_use_data_assistant")
    try:
        await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    except HTTPException as exc:
        if exc.status_code != 403:
            raise
        return OverviewResponse(
            description=record.description,
            draft_description=None,
            ai_description=None,
            revision=0,
            reviewed_at=record.overview_reviewed_at,
            reviewed_by=record.overview_reviewed_by,
        )
    return serialize(record)


@overview_router.put("/semantic/{db_id}/overview", response_model=OverviewResponse)
async def edit_overview(
    db_id: int,
    body: DraftRequest,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OverviewResponse:
    """Save a draft."""
    record = await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    await locked(db, record, body.revision)
    record.draft_description = body.draft_description
    record.overview_revision += 1
    await db.commit()
    return serialize(record)


@overview_router.put("/semantic/{db_id}/overview/published", response_model=OverviewResponse)
async def edit_published_overview(
    db_id: int,
    body: DraftRequest,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OverviewResponse:
    """Save the approved overview with review permissions."""
    record = await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    await locked(db, record, body.revision)
    record.description, record.draft_description = body.draft_description, None
    record.overview_reviewed_by, record.overview_reviewed_at = user.id, utc_now()
    record.overview_revision += 1
    await db.commit()
    return serialize(record)


@overview_router.post("/semantic/{db_id}/overview/generate", response_model=OverviewResponse)
async def create_overview(
    db_id: int,
    body: RevisionRequest,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OverviewResponse:
    """Generate a draft without overwriting concurrent edits."""
    record = await _require_resource_permission(db, user.id, db_id, org_id, "can_manage_schema")
    try:
        description = await generate_overview(db, record)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await locked(db, record, body.revision)
    record.ai_description = record.draft_description = description
    record.overview_revision += 1
    await db.commit()
    return serialize(record)


@overview_router.post("/semantic/{db_id}/overview/approve", response_model=OverviewResponse)
async def approve_overview(
    db_id: int,
    body: RevisionRequest,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> OverviewResponse:
    """Publish the draft."""
    record = await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    await locked(db, record, body.revision)
    if not record.draft_description:
        raise HTTPException(status_code=422, detail="Không có bản nháp để duyệt")
    record.description, record.draft_description = record.draft_description, None
    record.overview_reviewed_by, record.overview_reviewed_at = user.id, utc_now()
    record.overview_revision += 1
    await db.commit()
    return serialize(record)
