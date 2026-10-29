"""Metadata suggestion privacy, validation and atomic persistence."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models.db import CanonicalRelationshipModel
from src.models.db_relationships import RelationshipCandidateModel
from src.services.relationship_runtime import safe_join_path
from src.services.relationship_suggestions import metadata_projection, suggest_relationships
from src.services.semantic_compile_error import SemanticCompileError
from tests.test_services.test_relationship_review import seed


@pytest.mark.asyncio
async def test_metadata_only_idempotent_pending(async_session):
    db_id, tables, columns, draft = await seed(async_session)
    payload = {
        "suggestions": [
            {
                **draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"}),
                "reason": "Compatible metadata",
                "confidence": 0.8,
                "unresolved_questions": [],
            }
        ]
    }
    metadata = await metadata_projection(async_session, db_id)
    assert {item["schema"] for item in metadata} == {"sales", "public"}
    assert metadata[0]["columns"][0]["is_nullable"] is True
    assert "encrypted" not in str(metadata) and "business_name" not in str(metadata)
    with (
        patch("src.services.relationship_suggestions.get_llm"),
        patch("src.services.relationship_suggestions.ainvoke_json", AsyncMock(return_value=payload)),
    ):
        first = await suggest_relationships(async_session, db_id, 1)
        again = await suggest_relationships(async_session, db_id, 1)
    assert first[0].source == "ai" and first[0].confidence == 0.8
    assert first[0].unresolved_questions and first[0].evidence["metadata_only"]
    assert first[0].id == again[0].id
    assert list((await async_session.scalars(select(CanonicalRelationshipModel))).all()) == []
    with pytest.raises(SemanticCompileError):
        safe_join_path([], tables[0].id, tables[1].id)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["id", "sql", "type", "json", "timeout"])
async def test_bad_batch_has_no_partial_insert(async_session, failure):
    db_id, tables, columns, draft = await seed(async_session)
    item = {
        **draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"}),
        "reason": "metadata",
        "confidence": 0.5,
        "unresolved_questions": [],
    }
    bad = dict(item)
    if failure == "id":
        bad["from_entity_id"] = 99999
    if failure == "sql":
        bad["sql"] = "SELECT * FROM orders"
    if failure == "type":
        columns[1].data_type = "TEXT"
        await async_session.flush()
    caller = AsyncMock(return_value={"suggestions": [item, bad]})
    if failure in ("json", "timeout"):
        caller.side_effect = ValueError("invalid") if failure == "json" else TimeoutError()
    with (
        patch("src.services.relationship_suggestions.get_llm"),
        patch("src.services.relationship_suggestions.ainvoke_json", caller),
        pytest.raises(HTTPException),
    ):
        await suggest_relationships(async_session, db_id, 1)
    assert list((await async_session.scalars(select(RelationshipCandidateModel))).all()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", ["rejected", "fk", "inverse_fk", "unknown"])
async def test_history_fk_and_unknown(async_session, existing):
    from src.services.relationship_review_service import decide_relationship, preview_relationship_change

    db_id, tables, columns, draft = await seed(async_session)
    item = {
        **draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"}),
        "reason": "metadata",
        "confidence": 0.5,
        "unresolved_questions": [],
    }
    if existing == "unknown":
        item["relationship_type"] = "unknown"
    if existing in ("fk", "inverse_fk"):
        async_session.add(
            CanonicalRelationshipModel(
                connection_id=db_id,
                from_entity_id=tables[0].id,
                to_entity_id=tables[1].id,
                column_pairs=item["column_pairs"],
                relationship_type="many_to_one",
                source="fk",
                join_condition="",
                relationship_key="physical",
                evidence={},
            )
        )
        await async_session.flush()
    if existing == "inverse_fk":
        item["from_entity_id"], item["to_entity_id"] = item["to_entity_id"], item["from_entity_id"]
        item["column_pairs"] = [
            {"from_column_id": pair["to_column_id"], "to_column_id": pair["from_column_id"]}
            for pair in item["column_pairs"]
        ]
        item["relationship_type"] = "one_to_many"
    with (
        patch("src.services.relationship_suggestions.get_llm"),
        patch(
            "src.services.relationship_suggestions.ainvoke_json", AsyncMock(return_value={"suggestions": [item, item]})
        ),
    ):
        rows = await suggest_relationships(async_session, db_id, 1)
        assert len(rows) == (0 if existing in ("fk", "inverse_fk") else 1)
        if existing == "rejected":
            row = await async_session.get(RelationshipCandidateModel, rows[0].id)
            row.status = "rejected"
            await async_session.flush()
            assert await suggest_relationships(async_session, db_id, 1) == []
        if existing == "unknown":
            impact = await preview_relationship_change(
                async_session, db_id, rows[0].id, kind="candidate", action="approve"
            )
            with pytest.raises(HTTPException) as error:
                await decide_relationship(
                    async_session,
                    db_id,
                    1,
                    rows[0].id,
                    kind="candidate",
                    action="approve",
                    expected_revision=1,
                    impact_token=impact.token,
                    acknowledge_impact=True,
                )
            assert error.value.detail["errors"][0]["code"] == "UNKNOWN_CARDINALITY"


@pytest.mark.asyncio
async def test_unknown_cardinality_patch_requires_explicit_confirmation(async_session):
    from src.services.relationship_review_service import save_relationship_candidate

    db_id, _, _, draft = await seed(async_session)
    item = {
        **draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"}),
        "relationship_type": "unknown",
        "reason": "metadata",
        "confidence": 0.5,
        "unresolved_questions": [],
    }
    with (
        patch("src.services.relationship_suggestions.get_llm"),
        patch("src.services.relationship_suggestions.ainvoke_json", AsyncMock(return_value={"suggestions": [item]})),
    ):
        rows = await suggest_relationships(async_session, db_id, 1)
    draft.relationship_type = "many_to_many"
    draft.expected_revision = rows[0].revision
    unchanged = await save_relationship_candidate(async_session, db_id, 1, draft, candidate_id=rows[0].id)
    assert unchanged.evidence["cardinality_unknown"] is True
    draft.expected_revision = unchanged.revision
    draft.relationship_type = "many_to_one"
    changed = await save_relationship_candidate(async_session, db_id, 1, draft, candidate_id=rows[0].id)
    assert changed.evidence["cardinality_unknown"] is True
    draft.expected_revision = changed.revision
    draft.cardinality_confirmation = "I confirm the selected cardinality for these exact columns"
    confirmed = await save_relationship_candidate(async_session, db_id, 1, draft, candidate_id=rows[0].id)
    assert confirmed.evidence.get("cardinality_unknown") is not True
