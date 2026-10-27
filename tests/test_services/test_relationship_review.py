"""Relationship validation, lifecycle and publication impact regression tests."""

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models.db import (
    CanonicalRelationshipModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.models.db_relationships import RelationshipCandidateModel
from src.models.relationship_review import RelationshipDraft
from src.services.relationship_review_service import (
    decide_relationship,
    preview_relationship_change,
    save_relationship_candidate,
)
from src.services.relationship_validation import validate_relationship
from src.services.schema_review_service import approve_schema


async def seed(db):
    database = SemanticDatabaseModel(
        created_by=1, display_name="Relationships", db_type="postgresql", conn_url_enc="encrypted"
    )
    db.add(database)
    await db.flush()
    tables = [
        SemanticTableModel(
            db_id=database.id,
            table_name="same" if schema == "sales" else "customers",
            physical_schema=schema,
            business_name="",
            description="",
        )
        for schema in ("sales", "public")
    ]
    db.add_all(tables)
    await db.flush()
    columns = [
        SemanticColumnModel(
            table_id=t.id, column_name="id", data_type="INTEGER", business_name="", description="", is_primary_key=True
        )
        for t in tables
    ]
    db.add_all(columns)
    await db.flush()
    draft = RelationshipDraft(
        from_entity_id=tables[0].id,
        to_entity_id=tables[1].id,
        column_pairs=[{"from_column_id": columns[0].id, "to_column_id": columns[1].id}],
        relationship_type="many_to_one",
    )
    return database.id, tables, columns, draft


async def approve(db, db_id, item):
    impact = await preview_relationship_change(db, db_id, item.id, kind="candidate", action="approve")
    return await decide_relationship(
        db,
        db_id,
        1,
        item.id,
        kind="candidate",
        action="approve",
        expected_revision=item.revision,
        impact_token=impact.token,
        acknowledge_impact=True,
    )


@pytest.mark.asyncio
async def test_copy_on_write_approve_reject_disable_and_stale(async_session):
    db = async_session
    db_id, tables, columns, draft = await seed(db)
    item = await save_relationship_candidate(db, db_id, 1, draft)
    assert (await db.scalars(select(CanonicalRelationshipModel))).all() == []
    assert '"sales"."same"."id"' in item.on_preview
    approved = await approve(db, db_id, item)
    active = await db.get(CanonicalRelationshipModel, approved.active_relationship_id)
    assert active.reviewed_by == 1 and active.reviewed_at and active.human_modified
    old_sql = active.join_condition
    edit = draft.model_copy(update={"expected_revision": active.revision, "relationship_type": "one_to_one"})
    pending = await save_relationship_candidate(db, db_id, 1, edit, target_relationship_id=active.id)
    assert active.join_condition == old_sql and active.relationship_type == "many_to_one"
    await decide_relationship(
        db, db_id, 1, pending.id, kind="candidate", action="reject", expected_revision=pending.revision
    )
    assert active.join_condition == old_sql and active.relationship_type == "many_to_one"
    with pytest.raises(HTTPException) as error:
        await decide_relationship(
            db, db_id, 1, pending.id, kind="candidate", action="approve", expected_revision=pending.revision
        )
    assert error.value.status_code == 409
    impact = await preview_relationship_change(db, db_id, active.id, kind="active", action="disable")
    disabled = await decide_relationship(
        db,
        db_id,
        1,
        active.id,
        kind="active",
        action="disable",
        expected_revision=active.revision,
        impact_token=impact.token,
        acknowledge_impact=True,
    )
    assert disabled.status == "disabled" and disabled.reviewed_by == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code,index",
    [
        ("wrong_column", "INVALID_PAIR", 0),
        ("duplicate", "INVALID_PAIR", 1),
        ("type", "INCOMPATIBLE_TYPES", 0),
        ("partial", "PARTIAL_COMPOSITE_KEY", 0),
        ("foreign_table", "FOREIGN_TABLE", None),
    ],
)
async def test_indexed_validation(async_session, change, code, index):
    db_id, tables, columns, draft = await seed(async_session)
    if change == "wrong_column":
        draft.column_pairs[0].from_column_id = columns[1].id
    elif change == "duplicate":
        draft.column_pairs.append(draft.column_pairs[0])
    elif change == "type":
        columns[1].data_type = "TEXT"
    elif change == "partial":
        async_session.add(
            SemanticColumnModel(
                table_id=tables[1].id,
                column_name="second",
                data_type="INTEGER",
                business_name="",
                description="",
                is_primary_key=True,
            )
        )
    else:
        draft.to_entity_id = 99999
    await async_session.flush()
    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, db_id, draft, approval=True)
    detail = error.value.detail["errors"][0]
    assert (detail["code"], detail["pair_index"]) == (code, index)


@pytest.mark.asyncio
async def test_unproven_cardinality_requires_explicit_attestation(async_session):
    db_id, _, columns, draft = await seed(async_session)
    columns[1].is_primary_key = False
    await async_session.flush()
    assert (await validate_relationship(async_session, db_id, draft))["warnings"]
    with pytest.raises(HTTPException):
        await validate_relationship(async_session, db_id, draft, approval=True)
    draft.cardinality_confirmation = "I confirm target IDs are unique"
    await validate_relationship(async_session, db_id, draft, approval=True)


@pytest.mark.asyncio
async def test_impact_ack_stale_and_atomic_metric_review(async_session):
    db = async_session
    db_id, tables, _, draft = await seed(db)
    metric = SemanticMetricModel(
        db_id=db_id,
        name="Published",
        description="",
        sql_template="SELECT 1",
        status="approved",
        base_entity_id=tables[0].id,
    )
    db.add(metric)
    item = await save_relationship_candidate(db, db_id, 1, draft)
    impact = await preview_relationship_change(db, db_id, item.id, kind="candidate", action="approve")
    assert impact.metric_ids == [metric.id]
    for token, ack in ((impact.token, False), ("stale", True)):
        with pytest.raises(HTTPException) as error:
            await decide_relationship(
                db,
                db_id,
                1,
                item.id,
                kind="candidate",
                action="approve",
                expected_revision=item.revision,
                impact_token=token,
                acknowledge_impact=ack,
            )
        assert error.value.status_code == 409 and metric.status == "approved"
    await approve(db, db_id, item)
    assert metric.status == "needs_review"
    with pytest.raises(HTTPException):
        await decide_relationship(
            db,
            db_id,
            1,
            item.id,
            kind="candidate",
            action="approve",
            expected_revision=item.revision,
            impact_token=impact.token,
            acknowledge_impact=True,
        )


@pytest.mark.asyncio
async def test_schema_bulk_approval_preserves_candidates(async_session):
    db_id, _, _, draft = await seed(async_session)
    item = await save_relationship_candidate(async_session, db_id, 1, draft)
    result = await approve_schema(async_session, db_id, 1)
    assert result["pending_relationships"] == 1
    assert (await async_session.get(RelationshipCandidateModel, item.id)).status == "pending_review"


@pytest.mark.asyncio
async def test_stale_graph_and_candidate_revisions_invalidate_impact(async_session):
    db = async_session
    db_id, _, _, draft = await seed(db)
    item = await save_relationship_candidate(db, db_id, 1, draft)
    impact = await preview_relationship_change(db, db_id, item.id, kind="candidate", action="approve")
    changed = draft.model_copy(update={"expected_revision": item.revision, "relationship_type": "one_to_one"})
    updated = await save_relationship_candidate(db, db_id, 1, changed, candidate_id=item.id)
    for revision in (item.revision, updated.revision):
        with pytest.raises(HTTPException) as error:
            await decide_relationship(
                db,
                db_id,
                1,
                item.id,
                kind="candidate",
                action="approve",
                expected_revision=revision,
                impact_token=impact.token,
                acknowledge_impact=True,
            )
        assert error.value.status_code == 409
    assert (await db.scalars(select(CanonicalRelationshipModel))).all() == []


@pytest.mark.asyncio
async def test_foreign_database_columns_and_tables_are_indexed(async_session):
    db_id, _, _, draft = await seed(async_session)
    _, foreign_tables, foreign_columns, _ = await seed(async_session)
    draft.column_pairs[0].to_column_id = foreign_columns[1].id
    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, db_id, draft)
    assert error.value.detail["errors"][0]["pair_index"] == 0
    draft.to_entity_id = foreign_tables[1].id
    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, db_id, draft)
    assert error.value.detail["errors"][0]["code"] == "FOREIGN_TABLE"


@pytest.mark.asyncio
async def test_edit_rejection_preserves_published_metric_and_new_path_has_impact(async_session):
    db = async_session
    db_id, tables, _, draft = await seed(db)
    first = await approve(db, db_id, await save_relationship_candidate(db, db_id, 1, draft))
    metric = SemanticMetricModel(
        db_id=db_id,
        name="Published",
        description="",
        sql_template="SELECT 1",
        status="approved",
        base_entity_id=tables[0].id,
    )
    db.add(metric)
    await db.flush()
    active = await db.get(CanonicalRelationshipModel, first.active_relationship_id)
    edit = draft.model_copy(update={"relationship_type": "one_to_one", "expected_revision": active.revision})
    candidate = await save_relationship_candidate(db, db_id, 1, edit, target_relationship_id=active.id)
    impact = await preview_relationship_change(db, db_id, candidate.id, kind="candidate", action="approve")
    assert metric.id in impact.metric_ids and impact.before_on and impact.after_on
    await decide_relationship(
        db, db_id, 1, candidate.id, kind="candidate", action="reject", expected_revision=candidate.revision
    )
    assert metric.status == "approved"
    alternate = await save_relationship_candidate(db, db_id, 1, edit)
    impact = await preview_relationship_change(db, db_id, alternate.id, kind="candidate", action="approve")
    assert metric.id in impact.metric_ids
    await approve(db, db_id, alternate)
    assert metric.status == "needs_review"


@pytest.mark.asyncio
async def test_compare_and_swap_rejects_an_already_claimed_revision(async_session):
    from src.services.relationship_review_service import claim_revision

    db_id, _, _, draft = await seed(async_session)
    item = await save_relationship_candidate(async_session, db_id, 1, draft)
    row = await async_session.get(RelationshipCandidateModel, item.id)
    await claim_revision(async_session, row, 1)
    with pytest.raises(HTTPException) as error:
        await claim_revision(async_session, row, 1)
    assert error.value.status_code == 409 and row.revision == 2


@pytest.mark.asyncio
async def test_disable_invalid_legacy_link_does_not_require_repair(async_session):
    db_id, tables, _, _ = await seed(async_session)
    active = CanonicalRelationshipModel(
        connection_id=db_id,
        from_entity_id=tables[0].id,
        to_entity_id=tables[1].id,
        relationship_type="many_to_one",
        join_condition="legacy",
        column_pairs=[],
        validation_status="needs_review",
        review_status="approved",
    )
    async_session.add(active)
    await async_session.flush()
    impact = await preview_relationship_change(async_session, db_id, active.id, kind="active", action="disable")
    result = await decide_relationship(
        async_session,
        db_id,
        1,
        active.id,
        kind="active",
        action="disable",
        expected_revision=1,
        impact_token=impact.token,
        acknowledge_impact=True,
    )
    assert result.status == "disabled" and result.errors[0]["code"] == "EMPTY_PAIRS"


@pytest.mark.asyncio
async def test_concurrent_approvals_one_wins(tmp_path):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.models.db import Base

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db_id, _, _, draft = await seed(db)
        item = await save_relationship_candidate(db, db_id, 1, draft)
        impact = await preview_relationship_change(db, db_id, item.id, kind="candidate", action="approve")
        await db.commit()

    async def reviewer():
        async with factory() as db:
            try:
                await decide_relationship(
                    db,
                    db_id,
                    1,
                    item.id,
                    kind="candidate",
                    action="approve",
                    expected_revision=1,
                    impact_token=impact.token,
                    acknowledge_impact=True,
                )
                await db.commit()
                return 200
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    try:
        assert sorted(await asyncio.gather(reviewer(), reviewer())) == [200, 409]
        async with factory() as db:
            assert len((await db.scalars(select(CanonicalRelationshipModel))).all()) == 1
    finally:
        await engine.dispose()
