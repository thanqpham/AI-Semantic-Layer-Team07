"""Metadata suggestion privacy, validation and atomic persistence."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from src.models.db import CanonicalRelationshipModel, SemanticColumnModel, SemanticTableModel
from src.models.db_relationships import RelationshipCandidateModel
from src.services.relationship_runtime import safe_join_path
from src.services.relationship_suggestions import metadata_projection, suggest_relationships
from src.services.semantic_compile_error import SemanticCompileError
from tests.test_services.test_relationship_review import seed


@pytest.mark.asyncio
async def test_batches_cover_all_table_pairs_and_collect_more_than_one_batch():
    from src.services.relationship_suggestions import SuggestionBatch, request_all_suggestions

    metadata = [{"id": i, "columns": []} for i in range(15)]
    calls = []

    async def request(batch):
        calls.append({table["id"] for table in batch})
        item = {
            "from_entity_id": batch[0]["id"],
            "to_entity_id": batch[1]["id"],
            "column_pairs": [{"from_column_id": 1, "to_column_id": 2}],
            "relationship_type": "many_to_one",
            "reason": "metadata",
            "confidence": 0.8,
            "unresolved_questions": [],
        }
        return SuggestionBatch.model_validate({"suggestions": [item] * 5})

    with patch("src.services.relationship_suggestions.request_suggestions", request):
        assert len(await request_all_suggestions(metadata)) == 30
    assert len(calls) > 1
    assert all(any({i, j} <= batch for batch in calls) for i in range(15) for j in range(i + 1, 15))


@pytest.mark.asyncio
async def test_failed_or_saturated_batch_aborts_with_scope_diagnostic():
    from src.services.relationship_suggestions import SuggestionBatch, request_all_suggestions

    metadata = [{"id": i, "columns": []} for i in range(12)]
    with patch(
        "src.services.relationship_suggestions.request_suggestions", AsyncMock(side_effect=HTTPException(422, "bad"))
    ):
        with pytest.raises(HTTPException) as error:
            await request_all_suggestions(metadata)
    assert error.value.detail["errors"][0]["code"] == "SUGGESTION_BATCH_FAILED"
    assert error.value.detail["errors"][0]["unscanned_tables"]
    assert len(error.value.detail["errors"][0]["unscanned_batches"]) == 6
    item = {
        "from_entity_id": 0,
        "to_entity_id": 1,
        "column_pairs": [{"from_column_id": 1, "to_column_id": 2}],
        "relationship_type": "many_to_one",
        "reason": "metadata",
        "confidence": 0.8,
        "unresolved_questions": [],
    }
    existing_fk = [
        {"to_entity_id": 1, "column_pairs": [{"from_column_id": i + 1, "to_column_id": i + 101}]}
        for i in range(25)
    ]
    metadata[0]["existing_relationships"] = existing_fk
    repeated_fk = [{**item, "column_pairs": rel["column_pairs"]} for rel in existing_fk]
    with patch(
        "src.services.relationship_suggestions.request_suggestions",
        AsyncMock(return_value=SuggestionBatch.model_validate({"suggestions": repeated_fk})),
    ):
        with pytest.raises(HTTPException) as error:
            await request_all_suggestions(metadata)
    assert error.value.detail["errors"][0]["code"] == "SUGGESTION_BATCH_SATURATED"
    with patch("src.services.relationship_suggestions.request_suggestions", new_callable=AsyncMock) as caller:
        with pytest.raises(HTTPException) as error:
            await request_all_suggestions([{"id": i, "columns": []} for i in range(46)])
    assert error.value.detail["errors"][0]["code"] == "SUGGESTION_BATCH_LIMIT"
    caller.assert_not_called()


@pytest.mark.asyncio
async def test_batch_failure_does_not_persist_earlier_suggestions(async_session):
    from src.services.relationship_suggestions import SuggestionBatch

    db_id, _, _, draft = await seed(async_session)
    metadata = await metadata_projection(async_session, db_id)
    metadata.extend({"id": i, "columns": []} for i in range(1000, 1010))
    item = {
        **draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"}),
        "reason": "metadata",
        "confidence": 0.8,
        "unresolved_questions": [],
    }
    good = SuggestionBatch.model_validate({"suggestions": [item]})
    with (
        patch("src.services.relationship_suggestions.metadata_projection", AsyncMock(return_value=metadata)),
        patch(
            "src.services.relationship_suggestions.request_suggestions",
            AsyncMock(side_effect=[good, HTTPException(422, "failed")]),
        ),
        pytest.raises(HTTPException),
    ):
        await suggest_relationships(async_session, db_id, 1)
    assert list((await async_session.scalars(select(RelationshipCandidateModel))).all()) == []


@pytest.mark.asyncio
async def test_prompt_excludes_only_existing_approved_fk_pairs(async_session):
    db_id, tables, columns, draft = await seed(async_session)
    async_session.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=tables[0].id,
            to_entity_id=tables[1].id,
            column_pairs=draft.model_dump()["column_pairs"],
            relationship_type="many_to_one",
            source="fk",
            join_condition="",
            relationship_key="physical",
            evidence={},
        )
    )
    await async_session.flush()
    caller = AsyncMock(return_value={"suggestions": []})
    with (
        patch("src.services.relationship_suggestions.get_llm"),
        patch("src.services.relationship_suggestions.ainvoke_json", caller),
    ):
        await suggest_relationships(async_session, db_id, 1)
    prompt = caller.call_args.args[1]
    assert "existing_relationships" in prompt
    assert str(columns[0].id) in prompt and str(columns[1].id) in prompt
    assert "different columns" in prompt


@pytest.mark.asyncio
async def test_many_relationships_across_batches_persist_once(async_session):
    from src.services.relationship_suggestions import SuggestionBatch

    db_id, tables, columns, _ = await seed(async_session)
    sources = [
        SemanticTableModel(db_id=db_id, table_name=f"source_{i}", business_name="", description="") for i in range(26)
    ]
    async_session.add_all(sources)
    await async_session.flush()
    keys = [
        SemanticColumnModel(
            table_id=t.id, column_name="customer_id", data_type="INTEGER", business_name="", description=""
        )
        for t in sources
    ]
    async_session.add_all(keys)
    await async_session.flush()

    async def request(batch):
        ids = {t["id"] for t in batch}
        items = [
            {
                "from_entity_id": table.id,
                "to_entity_id": tables[1].id,
                "column_pairs": [{"from_column_id": column.id, "to_column_id": columns[1].id}],
                "relationship_type": "many_to_one",
                "reason": "metadata",
                "confidence": 0.8,
                "unresolved_questions": [],
            }
            for table, column in zip(sources, keys, strict=True)
            if table.id in ids and tables[1].id in ids
        ]
        return SuggestionBatch.model_validate({"suggestions": items})

    with patch("src.services.relationship_suggestions.request_suggestions", request):
        rows = await suggest_relationships(async_session, db_id, 1)
        again = await suggest_relationships(async_session, db_id, 1)
    assert len(rows) == len(again) == 26
    assert {row.id for row in rows} == {row.id for row in again}


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
            item["from_entity_id"], item["to_entity_id"] = item["to_entity_id"], item["from_entity_id"]
            item["column_pairs"] = [
                {"from_column_id": pair["to_column_id"], "to_column_id": pair["from_column_id"]}
                for pair in item["column_pairs"]
            ]
            item["relationship_type"] = "one_to_many"
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
