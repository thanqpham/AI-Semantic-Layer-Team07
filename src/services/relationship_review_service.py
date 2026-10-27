"""Transactional relationship lifecycle and conservative published-metric impact."""

import hashlib
import json

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import CanonicalRelationshipModel as Active
from src.models.db import SemanticMetricModel, UserModel, utc_now
from src.models.db_relationships import RelationshipCandidateModel as Candidate
from src.models.relationship_review import ColumnPair, RelationshipDraft, RelationshipImpact, RelationshipReviewItem
from src.services.database import lock_semantic_database
from src.services.relationship_runtime import active_relationship_filters, safe_join_path
from src.services.relationship_validation import endpoints, fingerprint, invalid, validate_relationship
from src.services.semantic_compile_error import SemanticCompileError


async def scoped(db: AsyncSession, db_id: int, item_id: int, kind: str) -> Active | Candidate:
    """Load a locked review row without permitting cross-database access."""
    model = Candidate if kind == "candidate" else Active
    row = await db.scalar(select(model).where(model.id == item_id, model.connection_id == db_id).with_for_update())
    if row is None:
        raise HTTPException(404, "Relationship not found")
    return row


def draft_for(row: Active | Candidate) -> RelationshipDraft:
    """Reconstruct editable metadata from a persisted review row."""
    pairs = parsed_pairs(row.column_pairs)
    return RelationshipDraft.model_construct(
        from_entity_id=row.from_entity_id,
        to_entity_id=row.to_entity_id,
        column_pairs=pairs,
        relationship_type=row.relationship_type,
        cardinality_confirmation=row.evidence.get("cardinality_confirmation"),
    )


async def review_item(db: AsyncSession, db_id: int, row: Active | Candidate, kind: str) -> RelationshipReviewItem:
    """Present the same qualified metadata for canonical and candidate rows."""
    errors, preview, warnings = [], "", []
    endpoint_draft = RelationshipDraft.model_construct(from_entity_id=row.from_entity_id, to_entity_id=row.to_entity_id)
    sides = await endpoints(db, db_id, endpoint_draft)
    try:
        validated = await validate_relationship(db, db_id, draft_for(row))
        preview, warnings = validated["on_preview"], validated["warnings"]
    except HTTPException as exc:
        errors = exc.detail["errors"]
    warnings.extend(await runtime_warnings(db, db_id, row))
    actor = await db.get(UserModel, row.reviewed_by) if row.reviewed_by else None
    values = row_values(row, "id revision column_pairs relationship_type source evidence reviewed_by reviewed_at")
    return RelationshipReviewItem(
        **values,
        kind=kind,
        active_relationship_id=row.target_relationship_id if kind == "candidate" else row.id,
        from_entity=entity_view(sides[0]),
        to_entity=entity_view(sides[1]),
        status=row.status if kind == "candidate" else row.review_status,
        confidence=getattr(row, "confidence", None),
        unresolved_questions=getattr(row, "unresolved_questions", []),
        reviewer_name=actor.full_name if actor else None,
        on_preview=preview,
        errors=errors,
        warnings=warnings,
    )


async def runtime_warnings(db: AsyncSession, db_id: int, row: Active | Candidate) -> list[dict]:
    """Expose compiler graph diagnostics without allowing candidates into runtime paths."""
    graph = list(
        (await db.scalars(select(Active).where(Active.connection_id == db_id, *active_relationship_filters()))).all()
    )
    try:
        safe_join_path(graph, row.from_entity_id, row.to_entity_id)
    except SemanticCompileError as exc:
        if exc.code in {"AMBIGUOUS_JOIN_PATH", "UNSAFE_FANOUT"}:
            return [exc.to_detail()]
    return []


def entity_view(side: tuple) -> dict:
    """Expose qualified identity and only columns belonging to the endpoint."""
    table, columns = side
    return {
        "id": table.id,
        "schema": table.physical_schema,
        "name": table.table_name,
        "columns": [{"id": c.id, "name": c.column_name, "type": c.data_type} for c in columns],
    }


async def list_relationship_reviews(
    db: AsyncSession, db_id: int, *, status: str | None = None, search: str = ""
) -> list[RelationshipReviewItem]:
    """List review rows; counts must be computed from the unfiltered result."""
    result = []
    for model, kind in ((Active, "active"), (Candidate, "candidate")):
        rows = (await db.scalars(select(model).where(model.connection_id == db_id).order_by(model.id))).all()
        for row in rows:
            item = await review_item(db, db_id, row, kind)
            if (status is None or item.status == status) and search.lower() in json.dumps(
                item.model_dump(), default=str
            ).lower():
                result.append(item)
    return result


async def claim_revision(db: AsyncSession, row: Active | Candidate, expected_revision: int | None) -> None:
    """Use compare-and-swap as well as row locks to reject concurrent reviewers."""
    if expected_revision is None:
        raise HTTPException(409, "expected_revision is required")
    model = type(row)
    result = await db.execute(
        update(model)
        .where(model.id == row.id, model.revision == expected_revision)
        .values(revision=expected_revision + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Relationship revision is stale")
    await db.refresh(row)


async def save_relationship_candidate(
    db: AsyncSession,
    db_id: int,
    actor_id: int,
    draft: RelationshipDraft,
    *,
    candidate_id: int | None = None,
    target_relationship_id: int | None = None,
) -> RelationshipReviewItem:
    """Save copy-on-write metadata without changing the serving relationship."""
    await lock_database(db, db_id)
    await validate_relationship(db, db_id, draft)
    if target_relationship_id is not None:
        target = await scoped(db, db_id, target_relationship_id, "active")
        if target.review_status != "approved" or target.revision != draft.expected_revision:
            raise HTTPException(409, "Active relationship is stale or not approved")
    existing = await editable_candidate(db, db_id, candidate_id) if candidate_id else None
    target_relationship_id = target_relationship_id or (existing.target_relationship_id if existing else None)
    key = fingerprint(draft, target_relationship_id)
    await require_unique_candidate(db, db_id, key, candidate_id)
    row = existing or Candidate(connection_id=db_id, created_by=actor_id, source="manual")
    if candidate_id:
        await claim_revision(db, row, draft.expected_revision)
    else:
        db.add(row)
    apply_draft(row, draft, target_relationship_id, key, actor_id)
    await db.flush()
    return await review_item(db, db_id, row, "candidate")


def apply_draft(row: Candidate, draft: RelationshipDraft, target_id: int | None, key: str, actor_id: int) -> None:
    """Reset prior review and attestation whenever proposal content changes."""
    row.from_entity_id, row.to_entity_id = draft.from_entity_id, draft.to_entity_id
    row.column_pairs = [pair.model_dump() for pair in draft.column_pairs]
    row.relationship_type, row.fingerprint = draft.relationship_type, key
    row.target_relationship_id = target_id if target_id is not None else row.target_relationship_id
    row.status, row.updated_by = "pending_review", actor_id
    row.reviewed_by, row.reviewed_at = None, None
    evidence = {
        key: value
        for key, value in (row.evidence or {}).items()
        if key not in ("attested_by", "attested_at", "cardinality_confirmation")
    }
    row.evidence = {**evidence, "cardinality_confirmation": (draft.cardinality_confirmation or "").strip()}


async def impact_state(db: AsyncSession, db_id: int, row: Active | Candidate, kind: str, action: str) -> dict:
    """Find every published metric reachable through old or proposed endpoints."""
    graph = list((await db.scalars(select(Active).where(Active.connection_id == db_id).with_for_update())).all())
    reached = reachable_paths(graph, row, kind)
    metrics = await published_metrics(db, db_id)
    affected = [m for m in metrics if m.base_entity_id in reached or m.base_entity_id is None]
    paths = [reached.get(m.base_entity_id, []) for m in affected]
    graph_values = [
        row_values(
            r,
            "id revision review_status validation_status column_pairs from_entity_id to_entity_id relationship_type evidence",
        )
        for r in graph
    ]
    metric_values = [row_values(m, "id version status updated_at") for m in affected]
    state = [kind, action, row.id, row.revision, row.column_pairs, row.evidence, graph_values, metric_values]
    return {
        "token": hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest(),
        "graph": graph,
        "metrics": affected,
        "paths": paths,
    }


async def published_metrics(db: AsyncSession, db_id: int) -> list[SemanticMetricModel]:
    """Lock current publications so their status cannot race a graph decision."""
    metrics = list(
        (
            await db.scalars(
                select(SemanticMetricModel)
                .where(
                    SemanticMetricModel.db_id == db_id,
                    SemanticMetricModel.status == "approved",
                    SemanticMetricModel.is_deleted.is_(False),
                )
                .with_for_update()
            )
        ).all()
    )
    return metrics


def reachable_paths(graph: list[Active], row: Active | Candidate, kind: str) -> dict[int, list[int]]:
    """Bound traversal by visited nodes and retain representative old/proposed paths."""
    edges = [
        (r.from_entity_id, r.to_entity_id, r.id)
        for r in graph
        if r.review_status == "approved" and r.validation_status == "valid"
    ]
    edges.append((row.from_entity_id, row.to_entity_id, row.id if kind == "active" else -row.id))
    reached, _ = {row.from_entity_id: [], row.to_entity_id: []}, []
    target_id = getattr(row, "target_relationship_id", None)
    for old in graph:
        if old.id == target_id:
            reached.update({old.from_entity_id: [], old.to_entity_id: []})
    for _ in range(len(edges) + 1):
        for left, right, edge in edges:
            for source, target in ((left, right), (right, left)):
                if source in reached and target not in reached:
                    reached[target] = reached[source] + [edge]
    return reached


async def preview_relationship_change(
    db: AsyncSession, db_id: int, item_id: int, *, kind: str, action: str
) -> RelationshipImpact:
    """Issue a snapshot token binding proposal, graph and affected publications."""
    await lock_database(db, db_id)
    row = await scoped(db, db_id, item_id, kind)
    state = await impact_state(db, db_id, row, kind, action)
    target_id = row.target_relationship_id if kind == "candidate" else row.id
    old = next((r for r in state["graph"] if r.id == target_id), None)
    validated = await validate_relationship(db, db_id, draft_for(row)) if action != "disable" else {"on_preview": ""}
    return RelationshipImpact(
        token=state["token"],
        relationship_ids=[r.id for r in state["graph"]],
        metric_ids=[m.id for m in state["metrics"]],
        join_paths=state["paths"],
        published_metrics=[{"id": m.id, "name": m.name} for m in state["metrics"]],
        warnings=[
            {
                "code": "METRIC_REVIEW_REQUIRED",
                "message": "Acknowledgment marks these published metrics needs_review; saved external SQL cannot be recalled.",
            }
        ],
        before_on=old.join_condition if old else "",
        after_on=validated["on_preview"] if action != "disable" else "",
    )


async def decide_relationship(
    db: AsyncSession,
    db_id: int,
    actor_id: int,
    item_id: int,
    *,
    kind: str,
    action: str,
    expected_revision: int,
    impact_token: str | None = None,
    acknowledge_impact: bool = False,
) -> RelationshipReviewItem:
    """Apply a guarded decision; caller commits or rolls back the entire transaction."""
    await lock_database(db, db_id)
    row = await scoped(db, db_id, item_id, kind)
    require_transition(row, kind, action, expected_revision)
    if action != "reject":
        state = await impact_state(db, db_id, row, kind, action)
        if not acknowledge_impact or impact_token != state["token"]:
            raise HTTPException(409, "Matching impact token and acknowledgment are required")
        validated = await validate_relationship(db, db_id, draft_for(row), approval=True) if action == "approve" else {}
    await claim_revision(db, row, expected_revision)
    if action == "approve":
        await promote(db, db_id, row, actor_id, validated["on_preview"])
    stamp_decision(row, kind, action, actor_id)
    for metric in state["metrics"] if action != "reject" else []:
        metric.status = "needs_review"
    await db.flush()
    return await review_item(db, db_id, row, kind)


async def promote(db: AsyncSession, db_id: int, row: Candidate, actor_id: int, on_sql: str) -> None:
    """Copy an approved proposal to canonical storage with audit provenance."""
    active = (
        await scoped(db, db_id, row.target_relationship_id, "active")
        if row.target_relationship_id
        else Active(connection_id=db_id)
    )
    if row.target_relationship_id:
        await claim_revision(db, active, active.revision)
    else:
        db.add(active)
    for name in ("from_entity_id", "to_entity_id", "column_pairs", "relationship_type", "source"):
        setattr(active, name, getattr(row, name))
    active.relationship_key = row.fingerprint
    active.join_condition, active.validation_status, active.review_status = on_sql, "valid", "approved"
    active.human_modified, active.reviewed_by, active.reviewed_at = True, actor_id, utc_now()
    active.evidence = {**row.evidence, "attested_by": actor_id, "attested_at": utc_now().isoformat()}
    await db.flush()
    row.target_relationship_id = active.id


async def lock_database(db: AsyncSession, db_id: int) -> None:
    """Serialize graph mutations, including insertion into a previously empty graph."""
    await lock_semantic_database(db, db_id)


def row_values(row: Active | Candidate | SemanticMetricModel, fields: str) -> dict:
    """Select persisted fields for stable presentation and impact snapshots."""
    return {name: getattr(row, name) for name in fields.split()}


async def require_unique_candidate(db: AsyncSession, db_id: int, key: str, candidate_id: int | None) -> None:
    """Reject duplicates including historical rejected proposals."""
    duplicate = await db.scalar(select(Candidate).where(Candidate.connection_id == db_id, Candidate.fingerprint == key))
    if duplicate is not None and duplicate.id != candidate_id:
        raise HTTPException(409, "This relationship proposal already exists")


def require_transition(row: Active | Candidate, kind: str, action: str, revision: int) -> None:
    """Reject decisions on stale or terminal review states."""
    valid = (kind == "candidate" and action in ("approve", "reject") and row.status == "pending_review") or (
        kind == "active" and action == "disable" and row.review_status == "approved"
    )
    if not valid:
        raise HTTPException(409, "Invalid relationship state transition")
    if row.revision != revision:
        raise HTTPException(409, "Relationship revision is stale")


def stamp_decision(row: Active | Candidate, kind: str, action: str, actor_id: int) -> None:
    """Record explicit review provenance without changing a rejected edit's target."""
    if action == "disable":
        row.review_status, row.human_modified = "disabled", True
    if kind == "candidate":
        row.status = "approved" if action == "approve" else "rejected"
    row.reviewed_by, row.reviewed_at = actor_id, utc_now()


def parsed_pairs(payload: object) -> list[ColumnPair]:
    """Convert stored legacy payloads into indexed review errors without rewriting them."""
    if not isinstance(payload, list):
        invalid("INVALID_PAIR", "Stored column pairs must be a list")
    pairs = []
    for index, raw in enumerate(payload):
        try:
            pairs.append(ColumnPair.model_validate(raw))
        except ValidationError:
            invalid("INVALID_PAIR", "Stored column pair requires valid column IDs", index)
    return pairs


async def editable_candidate(db: AsyncSession, db_id: int, candidate_id: int) -> Candidate:
    """Keep approved proposals immutable so their published audit trail survives edits."""
    row = await scoped(db, db_id, candidate_id, "candidate")
    if row.status == "approved":
        raise HTTPException(409, "Approved proposals are immutable; edit the active relationship instead")
    return row
