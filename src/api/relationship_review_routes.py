"""Scoped relationship review endpoints with atomic decision boundaries."""

from collections.abc import AsyncIterator
from contextlib import aclosing
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user
from src.api.llm_settings_routes import use_account_llm
from src.api.routes import _require_resource_permission
from src.models.db import UserModel
from src.models.relationship_review import RelationshipDecision, RelationshipDraft
from src.services.database import get_db_session
from src.services.llm import has_configured_llm
from src.services.relationship_review_service import (
    decide_relationship,
    list_relationship_reviews,
    preview_relationship_change,
    save_relationship_candidate,
)
from src.services.relationship_suggestions import suggest_relationships
from src.services.relationship_validation import validate_relationship
from src.services.review_notifications import sync_schema_review_notifications

relationship_router = APIRouter(prefix="/semantic/{db_id}/relationships", tags=["Relationship Review"])


async def access(
    db_id: int,
    org_id: int | None = Header(default=None, alias="X-Organization-ID"),
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> tuple:
    """Apply the existing resource and organization permission boundary."""
    await _require_resource_permission(db, current_user.id, db_id, org_id, "can_manage_schema")
    return db, current_user, org_id


def counts(items: list) -> dict[str, int]:
    """Count the global queue before filters are applied."""
    result = {"pending_relationships": 0, "approved": 0, "rejected": 0, "disabled": 0, "needs_review": 0}
    for item in items:
        key = "pending_relationships" if item.status == "pending_review" else item.status
        result[key] = result.get(key, 0) + 1
    return result


async def write_result(db: AsyncSession, db_id: int, operation) -> dict:
    """Commit all writes together and roll back validation or persistence failures."""
    try:
        item = await operation
        result = {"item": item, "counts": counts(await list_relationship_reviews(db, db_id))}
        await db.commit()
        await sync_schema_review_notifications(db, db_id)
        return result
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Relationship changed or duplicate proposal") from exc
    except Exception:
        await db.rollback()
        raise


@relationship_router.get("")
async def list_reviews(
    db_id: int, status: str | None = None, search: str = "", context: tuple = Depends(access)
) -> dict:
    """Return filtered review rows with unfiltered counts."""
    db, _, _ = context
    all_items = await list_relationship_reviews(db, db_id)
    items = await list_relationship_reviews(db, db_id, status=status, search=search)
    return {"items": items, "counts": counts(all_items)}


@relationship_router.post("/preview")
async def preview_draft(db_id: int, body: RelationshipDraft, context: tuple = Depends(access)) -> dict:
    """Generate a safely quoted ON preview without executing SQL."""
    validated = await validate_relationship(context[0], db_id, body)
    return {"on_preview": validated["on_preview"], "errors": [], "warnings": validated["warnings"]}


@relationship_router.post("/candidates")
async def create_candidate(db_id: int, body: RelationshipDraft, context: tuple = Depends(access)) -> dict:
    """Create a pending proposal outside the serving graph."""
    db, user, _ = context
    return await write_result(db, db_id, save_relationship_candidate(db, db_id, user.id, body))


@relationship_router.patch("/candidates/{item_id}")
async def update_candidate(db_id: int, item_id: int, body: RelationshipDraft, context: tuple = Depends(access)) -> dict:
    """Edit or explicitly reopen a proposal using its expected revision."""
    db, user, _ = context
    return await write_result(db, db_id, save_relationship_candidate(db, db_id, user.id, body, candidate_id=item_id))


@relationship_router.post("/{item_id}/edit")
async def edit_active(db_id: int, item_id: int, body: RelationshipDraft, context: tuple = Depends(access)) -> dict:
    """Create a pending copy while the approved relationship continues serving."""
    db, user, _ = context
    return await write_result(
        db, db_id, save_relationship_candidate(db, db_id, user.id, body, target_relationship_id=item_id)
    )


@relationship_router.get("/{item_id}/impact")
async def impact(
    db_id: int,
    item_id: int,
    kind: Literal["active", "candidate"],
    action: Literal["approve", "disable"],
    context: tuple = Depends(access),
):
    """Preview the published metrics requiring review after this change."""
    return await preview_relationship_change(context[0], db_id, item_id, kind=kind, action=action)


async def decision(
    db_id: int, item_id: int, body: RelationshipDecision, context: tuple, kind: str, action: str
) -> dict:
    """Authorize publication decisions independently from ordinary metadata edits."""
    db, user, org_id = context
    if action != "reject":
        await _require_resource_permission(db, user.id, db_id, org_id, "can_approve_metrics")
    return await write_result(
        db, db_id, decide_relationship(db, db_id, user.id, item_id, kind=kind, action=action, **body.model_dump())
    )


@relationship_router.post("/candidates/{item_id}/approve")
async def approve(db_id: int, item_id: int, body: RelationshipDecision, context: tuple = Depends(access)) -> dict:
    """Publish a validated proposal after acknowledging current impact."""
    return await decision(db_id, item_id, body, context, "candidate", "approve")


@relationship_router.post("/candidates/{item_id}/reject")
async def reject(db_id: int, item_id: int, body: RelationshipDecision, context: tuple = Depends(access)) -> dict:
    """Reject a proposal while leaving the canonical graph untouched."""
    return await decision(db_id, item_id, body, context, "candidate", "reject")


@relationship_router.post("/{item_id}/disable")
async def disable(db_id: int, item_id: int, body: RelationshipDecision, context: tuple = Depends(access)) -> dict:
    """Disable a serving link and mark dependent publications for review."""
    return await decision(db_id, item_id, body, context, "active", "disable")


async def use_suggestion_llm(
    user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)
) -> AsyncIterator[None]:
    """Reuse account context while giving suggestions a structured config error."""
    try:
        async with aclosing(use_account_llm(user, db)) as context:
            async for _ in context:
                if not has_configured_llm():
                    raise HTTPException(503, "Account AI settings are required")
                yield
    except HTTPException as exc:
        if exc.status_code != 503:
            raise
        raise HTTPException(
            503,
            {
                "errors": [
                    {
                        "code": "ACCOUNT_LLM_NOT_CONFIGURED",
                        "message": "Configure account AI settings before requesting suggestions",
                    }
                ]
            },
        ) from exc


@relationship_router.post("/suggest", dependencies=[Depends(use_suggestion_llm)])
async def suggest(db_id: int, context: tuple = Depends(access)) -> dict:
    """Suggest metadata-only pending relationships with account AI settings."""
    db, user, _ = context
    try:
        items = await suggest_relationships(db, db_id, user.id)
        result = {"items": items, "counts": counts(await list_relationship_reviews(db, db_id))}
        await db.commit()
        return result
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, "Relationship changed or duplicate proposal") from exc
    except Exception:
        await db.rollback()
        raise
