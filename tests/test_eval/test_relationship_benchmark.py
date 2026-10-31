"""Tests for relationship suggestion benchmark scoring."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from eval.relationship_benchmark import FIXTURE, run, score_relationships


def test_scores_reversed_and_composite_pairs_and_reports_false_predictions():
    expected = [
        {"from_entity_id": 1, "to_entity_id": 2, "column_pairs": [{"from_column_id": 11, "to_column_id": 21}]},
        {
            "from_entity_id": 3,
            "to_entity_id": 4,
            "column_pairs": [
                {"from_column_id": 31, "to_column_id": 41},
                {"from_column_id": 32, "to_column_id": 42},
            ],
        },
    ]
    actual = [
        {"from_entity_id": 2, "to_entity_id": 1, "column_pairs": [{"from_column_id": 21, "to_column_id": 11}]},
        {"from_entity_id": 3, "to_entity_id": 4, "column_pairs": [{"from_column_id": 31, "to_column_id": 41}]},
    ]
    result = score_relationships(expected, actual)
    assert (result["true_positive"], result["false_positive"], result["false_negative"]) == (1, 1, 1)
    assert result["precision"] == result["recall"] == 0.5
    assert len(result["missing"]) == len(result["unexpected"]) == 1


def test_fixture_has_unique_references_and_detects_missing_and_extra():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tables = {table["id"]: {column["id"] for column in table["columns"]} for table in fixture["metadata"]}
    for item in fixture["expected"]:
        for pair in item["column_pairs"]:
            assert pair["from_column_id"] in tables[item["from_entity_id"]]
            assert pair["to_column_id"] in tables[item["to_entity_id"]]
    result = score_relationships(fixture["expected"], fixture["expected"][:1])
    assert (result["true_positive"], result["false_negative"]) == (1, 1)
    groups = {table["id"]: index // 5 for index, table in enumerate(fixture["metadata"])}
    assert len(set(groups.values())) > 1
    assert any(groups[item["from_entity_id"]] != groups[item["to_entity_id"]] for item in fixture["expected"])


@pytest.mark.asyncio
async def test_report_discloses_raw_output_scope():
    config = SimpleNamespace(provider="test", model="test", temperature=0.0)
    request = AsyncMock(return_value=[])
    with (
        patch("src.services.llm._resolve_llm_config", return_value=config),
        patch("src.services.relationship_suggestions.request_all_suggestions", request),
    ):
        result = await run("none")
    assert result["evaluation_scope"] == "raw_llm_output"
    assert result["cardinality_scored"] is False
    assert all(table["existing_relationships"] == [] for table in request.await_args.args[0])


@pytest.mark.asyncio
async def test_report_includes_structured_failed_scope_without_provider_secrets():
    config = SimpleNamespace(provider="test", model="test", temperature=0.0)
    error = HTTPException(422, {"errors": [{"code": "SUGGESTION_BATCH_FAILED", "unscanned_table_ids": [1, 2]}]})
    with (
        patch("src.services.llm._resolve_llm_config", return_value=config),
        patch("src.services.relationship_suggestions.request_all_suggestions", AsyncMock(side_effect=error)),
    ):
        result = await run("none")
    assert result["status"] == "error"
    assert result["errors"][0]["code"] == "SUGGESTION_BATCH_FAILED"
    assert result["errors"][0]["unscanned_table_ids"] == [1, 2]
