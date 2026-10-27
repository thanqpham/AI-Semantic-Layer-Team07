from __future__ import annotations

from typing import Any

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
from src.models.relationship_review import ColumnPair, RelationshipDraft
from src.services.metric_context import _load_metadata
from src.services.query_compiler_metadata import QueryCompilerMetadata
from src.services.relationship_review_service import (
    decide_relationship,
    preview_relationship_change,
    save_relationship_candidate,
)


async def _seed(async_session: Any) -> dict[str, Any]:
    database = SemanticDatabaseModel(
        id=1,
        display_name="Main",
        db_type="postgresql",
        conn_url_enc="metadata-only",
    )
    tables = [
        SemanticTableModel(db_id=1, table_name=name, business_name=name.title(), physical_schema="public")
        for name in ("orders", "customers", "regions")
    ]
    async_session.add_all([database, *tables])
    await async_session.flush()
    columns = [
        SemanticColumnModel(
            table_id=tables[0].id,
            column_name="customer_id",
            data_type="integer",
            business_name="Customer ID",
        ),
        SemanticColumnModel(
            table_id=tables[1].id,
            column_name="id",
            data_type="integer",
            business_name="ID",
            is_primary_key=True,
        ),
        SemanticColumnModel(
            table_id=tables[1].id,
            column_name="region_id",
            data_type="integer",
            business_name="Region ID",
        ),
        SemanticColumnModel(
            table_id=tables[2].id,
            column_name="id",
            data_type="integer",
            business_name="ID",
            is_primary_key=True,
        ),
    ]
    async_session.add_all(columns)
    await async_session.flush()
    return {"database": database, "tables": tables, "columns": columns}


def _draft(
    metadata: dict[str, Any],
    *,
    from_table: int = 0,
    to_table: int = 1,
    from_column: int = 0,
    to_column: int = 1,
    expected_revision: int | None = None,
) -> RelationshipDraft:
    return RelationshipDraft(
        from_entity_id=metadata["tables"][from_table].id,
        to_entity_id=metadata["tables"][to_table].id,
        column_pairs=[
            ColumnPair(
                from_column_id=metadata["columns"][from_column].id,
                to_column_id=metadata["columns"][to_column].id,
            )
        ],
        relationship_type="many_to_one",
        expected_revision=expected_revision,
    )


async def _active(
    async_session: Any,
    metadata: dict[str, Any],
    *,
    from_table: int,
    to_table: int,
    from_column: int,
    to_column: int,
) -> CanonicalRelationshipModel:
    row = CanonicalRelationshipModel(
        connection_id=1,
        from_entity_id=metadata["tables"][from_table].id,
        to_entity_id=metadata["tables"][to_table].id,
        relationship_type="many_to_one",
        join_condition='"orders"."customer_id" = "customers"."id"',
        relationship_key=f"active-{from_table}-{to_table}",
        column_pairs=[
            {
                "from_column_id": metadata["columns"][from_column].id,
                "to_column_id": metadata["columns"][to_column].id,
            }
        ],
        validation_status="valid",
        review_status="approved",
        source="manual",
    )
    async_session.add(row)
    await async_session.flush()
    return row


async def _published_metric(async_session: Any, metadata: dict[str, Any], table_index: int) -> SemanticMetricModel:
    metric = SemanticMetricModel(
        db_id=1,
        name=f"Metric {table_index}",
        description="Published metric",
        sql_template="SELECT COUNT(*) FROM published_definition",
        status="approved",
        base_entity_id=metadata["tables"][table_index].id,
        formula="COUNT(*)",
        definition={"metric": {"name": f"Metric {table_index}", "base_entity": "unchanged"}},
        version=3,
    )
    async_session.add(metric)
    await async_session.flush()
    return metric


@pytest.mark.asyncio
async def test_saving_candidate_does_not_change_serving_graph(async_session: Any) -> None:
    metadata = await _seed(async_session)

    item = await save_relationship_candidate(async_session, 1, 1, _draft(metadata))

    candidate = await async_session.get(RelationshipCandidateModel, item.id)
    canonical = list((await async_session.scalars(select(CanonicalRelationshipModel))).all())
    assert item.kind == "candidate"
    assert candidate is not None and candidate.status == "pending_review"
    assert canonical == []


@pytest.mark.asyncio
async def test_candidate_duplicate_fingerprint_conflicts(async_session: Any) -> None:
    metadata = await _seed(async_session)
    await save_relationship_candidate(async_session, 1, 1, _draft(metadata))

    with pytest.raises(HTTPException) as error:
        await save_relationship_candidate(async_session, 1, 1, _draft(metadata))

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_active_edit_is_copy_on_write_until_approval(async_session: Any) -> None:
    metadata = await _seed(async_session)
    active = await _active(
        async_session,
        metadata,
        from_table=0,
        to_table=1,
        from_column=0,
        to_column=1,
    )
    old_condition = active.join_condition
    old_revision = active.revision

    item = await save_relationship_candidate(
        async_session,
        1,
        1,
        _draft(metadata, to_table=2, to_column=3, expected_revision=old_revision),
        target_relationship_id=active.id,
    )

    await async_session.refresh(active)
    assert item.kind == "candidate"
    assert item.active_relationship_id == active.id
    assert active.review_status == "approved"
    assert active.join_condition == old_condition
    assert active.revision == old_revision


@pytest.mark.asyncio
async def test_stale_candidate_revision_is_rejected(async_session: Any) -> None:
    metadata = await _seed(async_session)
    item = await save_relationship_candidate(async_session, 1, 1, _draft(metadata))

    with pytest.raises(HTTPException) as error:
        await save_relationship_candidate(
            async_session,
            1,
            1,
            _draft(metadata, expected_revision=99),
            candidate_id=item.id,
        )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_stale_active_revision_is_rejected_when_editing(async_session: Any) -> None:
    metadata = await _seed(async_session)
    active = await _active(
        async_session,
        metadata,
        from_table=0,
        to_table=1,
        from_column=0,
        to_column=1,
    )

    with pytest.raises(HTTPException) as error:
        await save_relationship_candidate(
            async_session,
            1,
            1,
            _draft(metadata, to_table=2, to_column=3, expected_revision=active.revision + 1),
            target_relationship_id=active.id,
        )

    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_rejecting_edit_leaves_serving_relationship_unchanged(async_session: Any) -> None:
    metadata = await _seed(async_session)
    active = await _active(
        async_session,
        metadata,
        from_table=0,
        to_table=1,
        from_column=0,
        to_column=1,
    )
    old_condition = active.join_condition
    item = await save_relationship_candidate(
        async_session,
        1,
        1,
        _draft(metadata, to_table=2, to_column=3, expected_revision=active.revision),
        target_relationship_id=active.id,
    )

    await decide_relationship(
        async_session,
        1,
        1,
        item.id,
        kind="candidate",
        action="reject",
        expected_revision=item.revision,
    )

    await async_session.refresh(active)
    candidate = await async_session.get(RelationshipCandidateModel, item.id)
    assert active.review_status == "approved"
    assert active.join_condition == old_condition
    assert candidate is not None and candidate.status == "rejected"


@pytest.mark.asyncio
async def test_approval_publishes_relationship_and_marks_metrics_atomically(async_session: Any) -> None:
    metadata = await _seed(async_session)
    direct_metric = await _published_metric(async_session, metadata, 0)
    indirect_metric = await _published_metric(async_session, metadata, 2)
    definitions = {
        direct_metric.id: (direct_metric.definition, direct_metric.sql_template, direct_metric.version),
        indirect_metric.id: (indirect_metric.definition, indirect_metric.sql_template, indirect_metric.version),
    }
    await _active(
        async_session,
        metadata,
        from_table=1,
        to_table=2,
        from_column=2,
        to_column=3,
    )
    item = await save_relationship_candidate(async_session, 1, 1, _draft(metadata))
    impact = await preview_relationship_change(async_session, 1, item.id, kind="candidate", action="approve")

    assert {direct_metric.id, indirect_metric.id} <= set(impact.metric_ids)
    assert len(impact.join_paths) == 2
    await decide_relationship(
        async_session,
        1,
        1,
        item.id,
        kind="candidate",
        action="approve",
        expected_revision=item.revision,
        impact_token=impact.token,
        acknowledge_impact=True,
    )

    active_rows = list((await async_session.scalars(select(CanonicalRelationshipModel))).all())
    assert any(row.review_status == "approved" and row.validation_status == "valid" for row in active_rows)
    for metric in (direct_metric, indirect_metric):
        await async_session.refresh(metric)
        assert metric.status == "needs_review"
        assert (metric.definition, metric.sql_template, metric.version) == definitions[metric.id]


@pytest.mark.asyncio
async def test_impact_requires_fresh_token_and_acknowledgment(async_session: Any) -> None:
    metadata = await _seed(async_session)
    await _published_metric(async_session, metadata, 0)
    item = await save_relationship_candidate(async_session, 1, 1, _draft(metadata))
    impact = await preview_relationship_change(async_session, 1, item.id, kind="candidate", action="approve")

    with pytest.raises(HTTPException) as error:
        await decide_relationship(
            async_session,
            1,
            1,
            item.id,
            kind="candidate",
            action="approve",
            expected_revision=item.revision,
            impact_token="stale-token",
            acknowledge_impact=True,
        )

    assert error.value.status_code == 409
    fresh = await preview_relationship_change(async_session, 1, item.id, kind="candidate", action="approve")
    assert fresh.token == impact.token


@pytest.mark.asyncio
async def test_compiler_metadata_excludes_disabled_and_invalid_relationships(async_session: Any) -> None:
    metadata = await _seed(async_session)
    approved = await _active(
        async_session,
        metadata,
        from_table=0,
        to_table=1,
        from_column=0,
        to_column=1,
    )
    disabled = await _active(
        async_session,
        metadata,
        from_table=1,
        to_table=2,
        from_column=2,
        to_column=3,
    )
    disabled.review_status = "disabled"
    invalid = await _active(
        async_session,
        metadata,
        from_table=0,
        to_table=2,
        from_column=0,
        to_column=3,
    )
    invalid.validation_status = "invalid"
    await save_relationship_candidate(async_session, 1, 1, _draft(metadata))

    _, relationships = await _load_metadata(async_session, 1)
    plan_metadata = await QueryCompilerMetadata(async_session).load_metric_plan_metadata(1)

    assert {relationship.id for relationship in relationships} == {approved.id}
    assert {relationship.id for relationship in plan_metadata.relationships} == {approved.id}


@pytest.mark.asyncio
async def test_graph_change_invalidates_impact_token(async_session: Any) -> None:
    metadata = await _seed(async_session)
    item = await save_relationship_candidate(async_session, 1, 1, _draft(metadata))
    impact = await preview_relationship_change(async_session, 1, item.id, kind="candidate", action="approve")
    await _active(
        async_session,
        metadata,
        from_table=1,
        to_table=2,
        from_column=2,
        to_column=3,
    )

    with pytest.raises(HTTPException) as error:
        await decide_relationship(
            async_session,
            1,
            1,
            item.id,
            kind="candidate",
            action="approve",
            expected_revision=item.revision,
            impact_token=impact.token,
            acknowledge_impact=True,
        )

    assert error.value.status_code == 409
