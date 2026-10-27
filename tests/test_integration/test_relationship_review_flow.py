"""Metadata-only lifecycle across import, suggestion, publication and sync."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models.db import CanonicalRelationshipModel, SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel
from src.models.relationship_review import RelationshipDraft
from src.models.schema_metadata import Identifier
from src.services.query_compiler import SemanticQueryCompiler
from src.services.relationship_review_service import (
    decide_relationship,
    list_relationship_reviews,
    preview_relationship_change,
    save_relationship_candidate,
)
from src.services.relationship_suggestions import suggest_relationships
from src.services.relationship_sync import reconcile_relationships
from src.services.schema_review_service import approve_schema
from src.services.semantic_compile_error import SemanticCompileError
from src.services.semantic_service import approve_metric, create_metric, enrich_and_save_canonical_schema
from tests.test_services.test_semantic_service import _make_def, _make_raw_schema


def compound_schema():
    raw = _make_raw_schema()
    users = next(t for t in raw.tables if t.table_name.raw_name == "users")
    orders = next(t for t in raw.tables if t.table_name.raw_name == "orders")
    regions = users.model_copy(update={"table_name": Identifier.from_raw("regions", raw.dialect)})
    tenant = users.columns[0].model_copy(update={"column_name": Identifier.from_raw("tenant_id", raw.dialect)})
    users = users.model_copy(update={"columns": (*users.columns, tenant)})
    users = users.model_copy(
        update={
            "primary_key": users.primary_key.model_copy(
                update={"constrained_columns": (*users.primary_key.constrained_columns, tenant.column_name)}
            )
        }
    )
    fk = orders.foreign_keys[0]
    orders = orders.model_copy(
        update={
            "columns": (*orders.columns, tenant.model_copy(update={"primary_key": False})),
            "foreign_keys": (
                fk.model_copy(
                    update={
                        "constrained_columns": (*fk.constrained_columns, tenant.column_name),
                        "referred_columns": (*fk.referred_columns, tenant.column_name),
                    }
                ),
            ),
        }
    )
    return raw.model_copy(update={"tables": (users, orders, regions)})


async def import_schema(db):
    database = SemanticDatabaseModel(created_by=1, display_name="Flow", db_type="postgresql", conn_url_enc="enc")
    db.add(database)
    await db.flush()
    raw = compound_schema()
    await enrich_and_save_canonical_schema(db, 1, database.id, raw, "postgresql", enrichment={"tables": []})
    await approve_schema(db, database.id, 1)
    tables = {t.table_name: t for t in (await db.scalars(select(SemanticTableModel))).all()}
    columns = {(c.table_id, c.column_name): c.id for c in (await db.scalars(select(SemanticColumnModel))).all()}
    draft = RelationshipDraft(
        from_entity_id=tables["orders"].id,
        to_entity_id=tables["regions"].id,
        column_pairs=[
            {
                "from_column_id": columns[tables["orders"].id, "id"],
                "to_column_id": columns[tables["regions"].id, "user_id"],
            }
        ],
        relationship_type="many_to_one",
    )
    return database.id, raw, tables, columns, draft


async def publish(db, db_id, item, *, kind="candidate", action="approve"):
    impact = await preview_relationship_change(db, db_id, item.id, kind=kind, action=action)
    result = await decide_relationship(
        db,
        db_id,
        1,
        item.id,
        kind=kind,
        action=action,
        expected_revision=item.revision,
        impact_token=impact.token,
        acknowledge_impact=True,
    )
    assert result.reviewed_by == 1 and result.reviewed_at
    if action == "approve":
        active = await db.get(CanonicalRelationshipModel, result.active_relationship_id)
        assert active.evidence["attested_by"] == 1 and active.evidence["attested_at"]
    return result, impact


async def suggest(db, db_id, draft):
    payload = {
        "suggestions": [
            {
                **draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"}),
                "reason": "Compatible metadata without a physical FK",
                "confidence": 0.8,
                "unresolved_questions": [],
            }
        ]
    }
    with (
        patch("src.services.relationship_suggestions.get_llm"),
        patch("src.services.relationship_suggestions.ainvoke_json", AsyncMock(return_value=payload)),
    ):
        return (await suggest_relationships(db, db_id, 1))[0]


def expected_compound_pairs(tables, columns):
    return [
        {"from_column_id": columns[tables["orders"].id, name], "to_column_id": columns[tables["users"].id, name]}
        for name in ("user_id", "tenant_id")
    ]


async def assert_compound_preserved(db, db_id, original_id, expected_pairs):
    rows = (
        await db.scalars(
            select(CanonicalRelationshipModel).where(
                CanonicalRelationshipModel.connection_id == db_id, CanonicalRelationshipModel.source == "fk"
            )
        )
    ).all()
    assert len(rows) == 1 and rows[0].id == original_id
    assert rows[0].column_pairs == expected_pairs and rows[0].review_status == "approved"


@pytest.mark.asyncio
async def test_relationship_review_flow(async_session):
    db = async_session
    db_id, raw, tables, columns, draft = await import_schema(db)
    trusted = (await list_relationship_reviews(db, db_id))[0]
    expected_pairs = expected_compound_pairs(tables, columns)
    assert trusted.column_pairs == expected_pairs
    assert trusted.source == "fk" and trusted.status == "approved" and len(trusted.column_pairs) == 2
    candidate = await suggest(db, db_id, draft)
    metric = await create_metric(db, db_id, _make_def(), 1)
    await approve_metric(db, metric.id, 1)
    compiler = SemanticQueryCompiler(db)
    dimension = columns[tables["regions"].id, "email"]
    with pytest.raises(SemanticCompileError, match="not reachable"):
        await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])
    approved, impact = await review_suggestion(db, db_id, draft, candidate)
    await assert_compound_preserved(db, db_id, trusted.id, expected_pairs)
    assert metric.id in impact.metric_ids and metric.status == "needs_review"
    await approve_metric(db, metric.id, 1)
    before = await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])
    assert "JOIN" in before.sql and "LIMIT" in before.sql
    await assert_active_edit(db, db_id, approved, draft, metric, compiler, dimension, before.sql)
    await assert_compound_preserved(db, db_id, trusted.id, expected_pairs)
    await assert_disabled_sync(db, db_id, raw, approved.active_relationship_id, metric, compiler, dimension)
    await assert_compound_preserved(db, db_id, trusted.id, expected_pairs)


async def review_suggestion(db, db_id, draft, candidate):
    edited = draft.model_copy(
        update={
            "expected_revision": candidate.revision,
            "relationship_type": "one_to_one",
            "cardinality_confirmation": "Both endpoint IDs are unique",
        }
    )
    candidate = await save_relationship_candidate(db, db_id, 1, edited, candidate_id=candidate.id)
    return await publish(db, db_id, candidate)


async def assert_active_edit(db, db_id, approved, draft, metric, compiler, dimension, old_sql):
    active = await db.get(CanonicalRelationshipModel, approved.active_relationship_id)
    edited = draft.model_copy(update={"expected_revision": active.revision})
    pending = await save_relationship_candidate(db, db_id, 1, edited, target_relationship_id=active.id)
    assert (await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])).sql == old_sql
    impact = await preview_relationship_change(db, db_id, pending.id, kind="candidate", action="approve")
    with pytest.raises(HTTPException) as error:
        await decide_relationship(
            db,
            db_id,
            1,
            pending.id,
            kind="candidate",
            action="approve",
            expected_revision=pending.revision,
            impact_token=impact.token,
            acknowledge_impact=False,
        )
    assert error.value.status_code == 409 and metric.status == "approved"
    await publish(db, db_id, pending)
    assert metric.status == "needs_review"
    with pytest.raises(SemanticCompileError) as error:
        await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])
    assert error.value.code == "METRIC_NEEDS_REVIEW"
    await approve_metric(db, metric.id, 1)
    assert "JOIN" in (await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])).sql


async def assert_disabled_sync(db, db_id, raw, active_id, metric, compiler, dimension):
    active = await db.get(CanonicalRelationshipModel, active_id)
    item = next(i for i in await list_relationship_reviews(db, db_id) if i.kind == "active" and i.id == active_id)
    disabled, _ = await publish(db, db_id, item, kind="active", action="disable")
    assert disabled.status == "disabled" and metric.status == "needs_review"
    await approve_metric(db, metric.id, 1)
    with pytest.raises(SemanticCompileError, match="not reachable"):
        await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])
    await reconcile_relationships(db, db_id, raw)
    assert active.review_status == "disabled" and active.reviewed_by == 1 and active.reviewed_at
    with pytest.raises(SemanticCompileError, match="not reachable"):
        await compiler.compile(db_id, metric_ids=[metric.id], dimension_ids=[dimension])
