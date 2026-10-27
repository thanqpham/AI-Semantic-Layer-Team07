"""Physical relationship reconciliation preserves review history."""

import pytest
from sqlalchemy import select

from src.models.db import CanonicalRelationshipModel
from src.services.relationship_sync import reconcile_relationships
from src.services.semantic_service import enrich_and_save_canonical_schema
from tests.test_services.test_semantic_service import _make_raw_schema


async def seed(db):
    from src.models.db import SemanticDatabaseModel

    db.add(SemanticDatabaseModel(id=90, created_by=1, display_name="Sync", db_type="postgresql", conn_url_enc="sync"))
    await db.flush()
    raw = _make_raw_schema()
    await enrich_and_save_canonical_schema(db, 1, 90, raw, "postgresql", enrichment={"tables": []})
    return raw, await db.scalar(
        select(CanonicalRelationshipModel).where(CanonicalRelationshipModel.connection_id == 90)
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["approved", "disabled"])
async def test_repeat_preserves_manual_decisions(async_session, status):
    raw, row = await seed(async_session)
    from src.models.db import utc_now

    reviewed_at = utc_now()
    row.review_status, row.human_modified, row.reviewed_by = status, True, 1
    row.reviewed_at = reviewed_at
    await async_session.flush()
    result = await reconcile_relationships(async_session, 90, raw)
    assert result == {"added": 0, "unchanged": 1, "changed": 0, "missing": 0}
    assert row.review_status == status and row.reviewed_by == 1
    assert row.reviewed_at.replace(tzinfo=None) == reviewed_at.replace(tzinfo=None)
    assert len((await async_session.scalars(select(CanonicalRelationshipModel))).all()) == 1


@pytest.mark.asyncio
async def test_missing_fk_invalidates_without_deleting(async_session):
    raw, row = await seed(async_session)
    without = raw.model_copy(update={"tables": tuple(t.model_copy(update={"foreign_keys": ()}) for t in raw.tables)})
    result = await reconcile_relationships(async_session, 90, without)
    assert result["missing"] == 1
    assert row.review_status == "needs_review" and row.validation_status != "valid"
    await reconcile_relationships(async_session, 90, raw)
    assert row.review_status == "needs_review"


@pytest.mark.asyncio
async def test_changed_fk_proposes_without_overwriting(async_session):
    raw, row = await seed(async_session)
    old_pairs = list(row.column_pairs)
    table = next(t for t in raw.tables if t.foreign_keys)
    fk = table.foreign_keys[0]
    from src.models.schema_metadata import Identifier

    changed = fk.model_copy(update={"constrained_columns": (Identifier.from_raw("id", raw.dialect),)})
    newer = raw.model_copy(
        update={
            "tables": tuple(t.model_copy(update={"foreign_keys": (changed,)}) if t == table else t for t in raw.tables)
        }
    )
    result = await reconcile_relationships(async_session, 90, newer)
    assert result["changed"] == 1
    assert row.column_pairs == old_pairs
    from src.models.db_relationships import RelationshipCandidateModel

    candidate = await async_session.scalar(select(RelationshipCandidateModel))
    candidate.status, candidate.reviewed_by = "rejected", 1
    await async_session.flush()
    await reconcile_relationships(async_session, 90, newer)
    assert candidate.status == "rejected" and candidate.reviewed_by == 1


@pytest.mark.asyncio
async def test_composite_and_same_constraint_name_across_schemas(async_session):
    from src.models.schema_metadata import Identifier, SchemaMetadata

    raw = _make_raw_schema()

    def ident(name):
        return Identifier.from_raw(name, raw.dialect)

    tables = []
    for namespace in ("public", "archive"):
        for table in raw.tables:
            fks = tuple(
                fk.model_copy(
                    update={
                        "constraint_name": ident("same_fk"),
                        "referred_schema": ident(namespace),
                        "referred_table": ident(
                            ("archive_" if namespace == "archive" else "") + fk.referred_table.raw_name
                        ),
                        "constrained_columns": (ident("user_id"), ident("id")),
                        "referred_columns": (ident("user_id"), ident("email")),
                    }
                )
                for fk in table.foreign_keys
            )
            tables.append(
                table.model_copy(
                    update={
                        "schema_name": ident(namespace),
                        "table_name": ident(("archive_" if namespace == "archive" else "") + table.table_name.raw_name),
                        "foreign_keys": fks,
                    }
                )
            )
    raw = raw.model_copy(
        update={
            "schemas": tuple(SchemaMetadata(schema_name=ident(n)) for n in ("public", "archive")),
            "tables": tuple(tables),
        }
    )
    from src.models.db import SemanticDatabaseModel

    async_session.add(
        SemanticDatabaseModel(id=90, created_by=1, display_name="Sync", db_type="postgresql", conn_url_enc="sync")
    )
    await async_session.flush()
    await enrich_and_save_canonical_schema(async_session, 1, 90, raw, "postgresql", enrichment={"tables": []})
    rows = (await async_session.scalars(select(CanonicalRelationshipModel))).all()
    assert len(rows) == 2 and all(len(r.column_pairs) == 2 for r in rows)
    assert rows[0].relationship_key != rows[1].relationship_key
    assert (await reconcile_relationships(async_session, 90, raw))["unchanged"] == 2


@pytest.mark.asyncio
async def test_new_fk_with_publications_is_candidate(async_session):
    from src.models.db import SemanticMetricModel
    from src.models.db_relationships import RelationshipCandidateModel

    raw, row = await seed(async_session)
    await async_session.delete(row)
    async_session.add(
        SemanticMetricModel(
            db_id=90,
            base_entity_id=row.from_entity_id,
            name="Published",
            description="",
            sql_template="COUNT(*)",
            formula="COUNT(*)",
            status="approved",
            definition={},
        )
    )
    await async_session.flush()
    await reconcile_relationships(async_session, 90, raw)
    assert await async_session.scalar(select(CanonicalRelationshipModel)) is None
    candidate = await async_session.scalar(select(RelationshipCandidateModel))
    assert candidate.status == "pending_review" and candidate.source == "fk"


@pytest.mark.asyncio
async def test_missing_endpoint_invalidates_manual_link_and_metric(async_session):
    from src.models.db import SemanticMetricModel

    raw, row = await seed(async_session)
    row.source = "manual"
    metric = SemanticMetricModel(
        db_id=90,
        base_entity_id=row.from_entity_id,
        name="Published",
        description="",
        sql_template="COUNT(*)",
        formula="COUNT(*)",
        status="approved",
        definition={},
    )
    async_session.add(metric)
    await async_session.flush()
    remaining = raw.model_copy(
        update={"tables": tuple(t.model_copy(update={"foreign_keys": ()}) for t in raw.tables if not t.foreign_keys)}
    )
    await reconcile_relationships(async_session, 90, remaining)
    assert row.validation_status == "invalid" and row.review_status == "needs_review"
    assert metric.status == "needs_review"
    assert metric.id in row.evidence["affected_metric_ids"]


@pytest.mark.asyncio
async def test_empty_snapshot_does_not_remove_links(async_session):
    raw, row = await seed(async_session)
    await reconcile_relationships(async_session, 90, raw.model_copy(update={"tables": ()}))
    assert row.validation_status == "valid" and row.review_status == "approved"


@pytest.mark.asyncio
async def test_sync_invalidation_expires_reviewer_revision(async_session):
    from fastapi import HTTPException

    from src.services.relationship_review_service import claim_revision

    raw, row = await seed(async_session)
    revision = row.revision
    missing = raw.model_copy(update={"tables": tuple(t.model_copy(update={"foreign_keys": ()}) for t in raw.tables)})
    await reconcile_relationships(async_session, 90, missing)
    with pytest.raises(HTTPException) as error:
        await claim_revision(async_session, row, revision)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_disconnected_publication_does_not_block_trusted_fk(async_session):
    from src.models.db import SemanticMetricModel, SemanticTableModel

    raw, row = await seed(async_session)
    await async_session.delete(row)
    unrelated = SemanticTableModel(db_id=90, table_name="unrelated", physical_schema="public", business_name="Other")
    async_session.add(unrelated)
    await async_session.flush()
    async_session.add(
        SemanticMetricModel(
            db_id=90,
            base_entity_id=unrelated.id,
            name="Other",
            description="",
            formula="COUNT(*)",
            sql_template="COUNT(*)",
            status="approved",
            definition={},
        )
    )
    await async_session.flush()
    await reconcile_relationships(async_session, 90, raw)
    active = await async_session.scalar(select(CanonicalRelationshipModel))
    assert active.review_status == "approved" and active.source == "fk"


@pytest.mark.asyncio
async def test_legacy_null_namespace_fk_is_preserved(async_session):
    from src.models.db import SemanticTableModel

    raw, row = await seed(async_session)
    tables = (await async_session.scalars(select(SemanticTableModel))).all()
    for table in tables:
        table.physical_schema = None
    await async_session.flush()
    assert (await reconcile_relationships(async_session, 90, raw))["unchanged"] == 1
    assert row.review_status == "approved" and row.validation_status == "valid"
    assert all(t.physical_schema == "public" for t in tables)


@pytest.mark.asyncio
async def test_reenrichment_type_change_requires_relationship_review(async_session):
    raw, row = await seed(async_session)
    table = next(t for t in raw.tables if t.foreign_keys)
    columns = tuple(
        c.model_copy(update={"data_type": "TEXT", "raw_data_type": "TEXT"})
        if c.column_name.raw_name == "user_id"
        else c
        for c in table.columns
    )
    raw = raw.model_copy(
        update={"tables": tuple(t.model_copy(update={"columns": columns}) if t == table else t for t in raw.tables)}
    )
    await enrich_and_save_canonical_schema(async_session, 1, 90, raw, "postgresql", enrichment={"tables": []})
    assert row.validation_status == "invalid" and row.review_status == "needs_review"
