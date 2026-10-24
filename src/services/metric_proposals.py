"""Persist review evidence and enforce server-owned AI proposal gates."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import MetricProposalModel
from src.models.metric_definition import MetricDefinition
from src.models.metric_review import MetricReview
from src.services.metric_context import load_review_schema
from src.services.metric_dedupe import dedupe_reviewed_suggestions, load_existing_for_dedupe
from src.services.metric_knowledge import metric_knowledge
from src.services.metric_proposal_context import check_context_budget
from src.services.metric_review import review_metric_draft
from src.services.metric_review_validation import schema_tables


def review_schema_fingerprint(schema: dict[str, Any]) -> str:
    """Include semantics and constraints, not only physical column names."""
    tables = [
        {**t, "columns": sorted(t.get("columns", []), key=lambda c: c.get("column_name", ""))}
        for t in schema_tables(schema)
    ]
    value = {
        "tables": sorted(tables, key=lambda t: t["table_name"]),
        "relationships": sorted(schema.get("relationships", []), key=lambda r: json.dumps(r, sort_keys=True)),
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def persist_reviewed_state(db: AsyncSession, db_id: int, user_id: int, state: dict[str, Any]) -> dict[str, Any]:
    """Assign durable proposal IDs before suggestions leave the backend."""
    for evidence in state.get("reviewed_proposals", []):
        proposal = await persist_proposal(db, db_id, user_id, evidence)
        for item in state.get("suggested_metrics", []):
            if item["definition"] == proposal.final_definition and not item.get("proposal_id"):
                item["proposal_id"] = proposal.id
                break
        for item in state.get("blocked_candidates", []):
            if item["name"] == evidence["name"] and not item.get("proposal_id"):
                item["proposal_id"] = proposal.id
                break
    return state


async def persist_proposal(
    db: AsyncSession, db_id: int, user_id: int, evidence: dict[str, Any], parent_id: str | None = None
) -> MetricProposalModel:
    """Store immutable evidence without publishing a catalog metric."""
    review = MetricReview.model_validate(evidence["review"])
    proposal = MetricProposalModel(
        db_id=db_id,
        created_by=user_id,
        parent_id=parent_id,
        context=evidence["context"],
        original_definition=evidence["original_definition"],
        final_definition=evidence["final_definition"],
        review=review.model_dump(mode="json"),
        status=review.status,
        schema_fingerprint=review_schema_fingerprint(evidence["context"]["schema"]),
    )
    db.add(proposal)
    await db.flush()
    return proposal


async def require_proposal(
    db: AsyncSession, db_id: int, proposal_id: str | None, user_id: int, allow_lead: bool = False
) -> MetricProposalModel:
    """Require an owned proposal; callers must authorize Data Lead access first."""
    proposal = await db.get(MetricProposalModel, proposal_id) if proposal_id else None
    if proposal is None or proposal.db_id != db_id or (proposal.created_by != user_id and not allow_lead):
        raise ValueError("Không tìm thấy proposal thẩm định trong phạm vi quyền. Hãy sinh lại đề xuất AI.")
    return proposal


async def require_passing_proposal(
    db: AsyncSession,
    db_id: int,
    proposal_id: str | None,
    user_id: int,
    definition: MetricDefinition,
    allow_lead: bool = False,
) -> MetricProposalModel:
    """Reject forged, changed, stale, failed or already-saved proposals."""
    proposal = await require_proposal(db, db_id, proposal_id, user_id, allow_lead)
    if proposal.status != "pass" or proposal.final_definition is None:
        raise ValueError("Metric chưa thẩm định đạt; không thể lưu hoặc gửi duyệt.")
    if proposal.metric_id is not None or proposal.metric_version is not None:
        raise ValueError("Proposal đã được lưu vào catalog.")
    if MetricDefinition.model_validate(proposal.final_definition) != definition:
        raise ValueError("Định nghĩa đã thay đổi. Hãy thẩm định lại trước khi lưu.")
    names = [t["table_name"] for t in schema_tables(proposal.context["schema"])]
    current = await load_review_schema(db, db_id, names)
    if review_schema_fingerprint(current) != proposal.schema_fingerprint:
        raise ValueError("Metadata đã thay đổi. Hãy thẩm định lại trước khi lưu hoặc gửi duyệt.")
    check = {"suggested_metrics": [{"definition": definition.model_dump(mode="json")}]}
    await dedupe_reviewed_suggestions(db, db_id, check)
    if not check["suggested_metrics"]:
        raise ValueError("Metric có cùng công thức và phạm vi đã tồn tại trong catalog. Hãy dùng metric có sẵn.")
    return proposal


async def re_review_proposal(
    db: AsyncSession, proposal: MetricProposalModel, user_id: int, definition: MetricDefinition
) -> MetricProposalModel:
    """Review an edit as a new proposal with fresh metadata and original requirements."""
    names = list({t["table_name"] for t in schema_tables(proposal.context["schema"])} | {definition.metric.base_entity})
    existing, _ = await load_existing_for_dedupe(db, str(proposal.db_id))
    context = {
        **proposal.context,
        "schema": await load_review_schema(db, proposal.db_id, names),
        "existing_metrics": existing or [],
        "knowledge": metric_knowledge(
            proposal.context["requirement"], proposal.context.get("proposal_mode") == "discovery"
        ),
    }
    check_context_budget(context)
    candidate = proposal.context.get("candidate", {})
    draft = {
        "name": definition.metric.name,
        "definition": definition.model_dump(mode="json"),
        "knowledge_id": candidate.get("knowledge_id"),
        "variant_id": candidate.get("variant_id"),
        "criteria": candidate.get("criteria", {}),
    }
    evidence = await review_metric_draft(context, draft, allow_repair=False)
    result = await persist_proposal(db, proposal.db_id, user_id, evidence, proposal.id)
    result.request_id = proposal.request_id
    return result


async def proposal_for_request(db: AsyncSession, message_id: str, index: int) -> str | None:
    """Resolve an immutable message selection to its server-owned proposal."""
    from src.models.db import ChatMessageModel

    message = await db.get(ChatMessageModel, message_id)
    metadata = message.metadata_json if message and isinstance(message.metadata_json, dict) else {}
    items = metadata.get("suggestions") or []
    return items[index].get("proposal_id") if 0 <= index < len(items) and isinstance(items[index], dict) else None


async def request_review_details(
    db: AsyncSession, message_id: str, index: int, request_id: int | None = None
) -> dict[str, Any]:
    """Attach review evidence when authorized callers serialize a metric request."""
    proposal_id = await proposal_for_request(db, message_id, index)
    proposal = await db.get(MetricProposalModel, proposal_id) if proposal_id else None
    if request_id:
        proposal = (
            await db.scalar(
                select(MetricProposalModel)
                .where(MetricProposalModel.request_id == request_id)
                .order_by(MetricProposalModel.metric_version.is_not(None).desc(), MetricProposalModel.created_at.desc())
                .limit(1)
            )
            or proposal
        )
        proposal_id = proposal.id if proposal else proposal_id
    details = {"proposal_id": proposal_id, "review": proposal.review if proposal else None}
    if proposal and proposal.final_definition:
        details["definition"] = proposal.final_definition
    return details


async def link_saved_proposal(db: AsyncSession, proposal: MetricProposalModel, metric_id: int, version: int) -> None:
    """Atomically consume one proposal; concurrent saves must not create two metrics."""
    from sqlalchemy import update

    result = await db.execute(
        update(MetricProposalModel)
        .where(
            MetricProposalModel.id == proposal.id,
            MetricProposalModel.metric_id.is_(None),
            MetricProposalModel.metric_version.is_(None),
        )
        .values(metric_id=metric_id, metric_version=version)
    )
    if result.rowcount != 1:
        raise ValueError("Proposal đã được lưu bởi một yêu cầu khác.")
    await db.refresh(proposal, ["metric_id", "metric_version"])


async def metric_version_review(db: AsyncSession, metric_id: int, version: int) -> dict[str, Any] | None:
    """Find the review that produced a specific catalog version."""
    proposal = await db.scalar(
        select(MetricProposalModel).where(
            MetricProposalModel.metric_id == metric_id, MetricProposalModel.metric_version == version
        )
    )
    return proposal.review if proposal else None


async def generate_reviewed_metrics(
    db: AsyncSession, db_id: int, user_id: int, state: dict[str, Any]
) -> dict[str, Any]:
    """Use the same generation/review pipeline for non-chat API clients."""
    from src.agents.nodes.metric.coordinator_node import coordinator_node

    state = {**state, **await coordinator_node(state)}
    return await persist_reviewed_state(db, db_id, user_id, state)
