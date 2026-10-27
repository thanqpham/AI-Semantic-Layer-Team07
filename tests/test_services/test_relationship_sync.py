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
async def test_legacy_null_namespace_fk_does_not_guess_schema(async_session):
    from src.models.db import SemanticTableModel

    raw, row = await seed(async_session)
    tables = (await async_session.scalars(select(SemanticTableModel))).all()
    for table in tables:
        table.physical_schema = None
        table.physical_schema_key = None
        table.table_name_key = None
    await async_session.flush()
    with pytest.raises(ValueError, match="FK endpoints must be persisted"):
        await reconcile_relationships(async_session, 90, raw)
    assert row.review_status == "approved" and row.validation_status == "valid"
    assert all(t.physical_schema is None for t in tables)


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


@pytest.mark.asyncio
async def test_unchanged_physical_fk_preserves_different_human_pairs(async_session):
    from src.models.db import SemanticColumnModel, utc_now
    from src.models.db_relationships import RelationshipCandidateModel

    raw, row = await seed(async_session)
    alternate = await async_session.scalar(
        select(SemanticColumnModel).where(
            SemanticColumnModel.table_id == row.from_entity_id, SemanticColumnModel.column_name == "id"
        )
    )
    row.column_pairs = [{"from_column_id": alternate.id, "to_column_id": row.column_pairs[0]["to_column_id"]}]
    row.human_modified, row.reviewed_by, row.reviewed_at = True, 1, utc_now()
    human_pairs, reviewed_at = list(row.column_pairs), row.reviewed_at
    await async_session.flush()
    result = await reconcile_relationships(async_session, 90, raw)
    assert result["unchanged"] == 1 and result["changed"] == result["missing"] == 0
    assert row.column_pairs == human_pairs and row.review_status == "approved" and row.validation_status == "valid"
    assert row.reviewed_by == 1 and row.reviewed_at.replace(tzinfo=None) == reviewed_at.replace(tzinfo=None)
    assert await async_session.scalar(select(RelationshipCandidateModel)) is None


@pytest.mark.asyncio
async def test_human_promotion_retains_original_physical_identity(async_session):
    from src.models.db import SemanticColumnModel
    from src.models.relationship_review import RelationshipDraft
    from src.services.relationship_review_service import save_relationship_candidate
    from tests.test_services.test_relationship_review import approve

    raw, row = await seed(async_session)
    alternate = await async_session.scalar(
        select(SemanticColumnModel).where(
            SemanticColumnModel.table_id == row.from_entity_id, SemanticColumnModel.column_name == "id"
        )
    )
    draft = RelationshipDraft(
        from_entity_id=row.from_entity_id,
        to_entity_id=row.to_entity_id,
        expected_revision=row.revision,
        column_pairs=[{"from_column_id": alternate.id, "to_column_id": row.column_pairs[0]["to_column_id"]}],
        relationship_type="many_to_one",
    )
    physical_key = row.evidence["physical_fk_key"]
    candidate = await save_relationship_candidate(async_session, 90, 1, draft, target_relationship_id=row.id)
    await approve(async_session, 90, candidate)
    assert row.evidence["physical_fk_key"] == physical_key
    assert (await reconcile_relationships(async_session, 90, raw))["unchanged"] == 1
    assert row.column_pairs == [p.model_dump() for p in draft.column_pairs]
    assert row.validation_status == "valid" and row.review_status == "approved"
    assert '"orders"."id"' in row.join_condition


@pytest.mark.asyncio
async def test_retained_dropped_column_cannot_be_approved(async_session):
    from fastapi import HTTPException

    from src.models.db import ImportedSchemaModel
    from src.services.relationship_review_service import draft_for, review_item
    from src.services.relationship_validation import validate_relationship

    raw, row = await seed(async_session)
    async_session.add(
        ImportedSchemaModel(
            created_by=1,
            semantic_db_id=90,
            display_name="Imported",
            dialect="postgresql",
            schema_metadata=raw.model_dump(mode="json"),
        )
    )
    await async_session.flush()
    source = next(t for t in raw.tables if t.foreign_keys)
    dropped = source.model_copy(
        update={"columns": tuple(c for c in source.columns if c.column_name.raw_name != "user_id"), "foreign_keys": ()}
    )
    raw = raw.model_copy(update={"tables": tuple(dropped if t == source else t for t in raw.tables)})
    await reconcile_relationships(async_session, 90, raw)
    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 90, draft_for(row), approval=True)
    assert error.value.detail["errors"][0]["code"] == "ABSENT_COLUMN"
    assert (await review_item(async_session, 90, row, "active")).errors[0]["code"] == "ABSENT_COLUMN"


@pytest.mark.asyncio
async def test_repeat_uppercase_fk_keeps_approved_metric(async_session):
    from src.models.db import SemanticDatabaseModel, SemanticMetricModel
    from src.models.schema_metadata import Identifier

    raw = _make_raw_schema()
    def ident(s):
        return Identifier.from_raw(s.upper(), raw.dialect)
    raw = raw.model_copy(
        update={
            "tables": tuple(
                t.model_copy(
                    update={
                        "schema_name": ident(t.schema_name.raw_name),
                        "table_name": ident(t.table_name.raw_name),
                        "foreign_keys": tuple(
                            f.model_copy(
                                update={
                                    "referred_schema": ident(f.referred_schema.raw_name),
                                    "referred_table": ident(f.referred_table.raw_name),
                                }
                            )
                            for f in t.foreign_keys
                        ),
                    }
                )
                for t in raw.tables
            )
        }
    )
    async_session.add(
        SemanticDatabaseModel(id=90, created_by=1, display_name="Sync", db_type="postgresql", conn_url_enc="sync")
    )
    await async_session.flush()
    await enrich_and_save_canonical_schema(async_session, 1, 90, raw, "postgresql", enrichment={"tables": []})
    row = await async_session.scalar(select(CanonicalRelationshipModel))
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
    await reconcile_relationships(async_session, 90, raw)
    assert row.validation_status == "valid" and row.review_status == "approved"
    assert metric.status == "approved"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["unparsed legacy payload", ["malformed"], [{"from_column_id": 1}]])
async def test_sync_preserves_malformed_legacy_payload(async_session, payload):
    raw, row = await seed(async_session)
    row.column_pairs, row.validation_status, row.join_condition = payload, "needs_review", "legacy"
    await async_session.flush()
    await reconcile_relationships(async_session, 90, raw)
    assert row.column_pairs == payload and row.join_condition == "legacy"


@pytest.mark.asyncio
async def test_migrated_legacy_payload_survives_sync(async_session):
    from unittest.mock import patch

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from tests.test_migrations.test_relationship_review import _legacy_schema, _migration, _seed

    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        old = _legacy_schema(connection)
        _seed(connection, old)
        migration = _migration()
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
        migrated = sa.Table("canonical_relationships", sa.MetaData(), autoload_with=connection)
        payload, status = connection.execute(
            sa.select(migrated.c.column_pairs, migrated.c.validation_status).where(migrated.c.id == 9)
        ).one()
    engine.dispose()
    raw, row = await seed(async_session)
    row.column_pairs, row.validation_status, row.join_condition = payload, status, "legacy"
    await async_session.flush()
    await reconcile_relationships(async_session, 90, raw)
    assert row.column_pairs == "unparsed legacy payload" and row.join_condition == "legacy"
