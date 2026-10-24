"""Regression checks for duplicate reviewed proposals before they reach users."""

from unittest.mock import AsyncMock

import pytest

from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel
from src.models.metric_definition import MetricDefinition
from src.services.metric_dedupe import dedupe_reviewed_suggestions
from src.services.metric_proposals import persist_reviewed_state
from src.services.metric_service import create_metric


def _definition(name: str, filters: list[dict] | None = None) -> dict:
    return MetricDefinition.model_validate(
        {
            "metric": {
                "name": name,
                "formula": {"function": "COUNT_DISTINCT", "expression": "id"},
                "base_entity": "order_header",
                "grain": {"column_ids": [1]},
                "filters": filters
                or [
                    {"field": "latest_status", "operator": "eq", "value": "Completed"},
                    {"field": "is_test_order", "operator": "eq", "value": "0"},
                ],
            }
        }
    ).model_dump(mode="json")


async def _seed_order_table(async_session) -> int:
    database = SemanticDatabaseModel(created_by=1, display_name="Orders", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="order_header", business_name="Orders")
    async_session.add(table)
    await async_session.flush()
    async_session.add_all(
        SemanticColumnModel(table_id=table.id, column_name=name, business_name=name, data_type=type_, is_primary_key=pk)
        for name, type_, pk in [
            ("id", "INTEGER", True),
            ("latest_status", "TEXT", False),
            ("is_test_order", "TEXT", False),
        ]
    )
    await async_session.flush()
    return database.id


@pytest.mark.asyncio
async def test_reviewed_proposal_reuses_same_metric_with_different_name(async_session) -> None:
    db_id = await _seed_order_table(async_session)

    existing = await create_metric(
        async_session,
        db_id,
        {"definition": _definition("Số đơn hàng hoàn tất (loại trừ test)")},
        1,
        status_override="approved",
    )
    draft = _definition("Số đơn hàng hoàn tất, không tính đơn thử nghiệm")
    state = {
        "suggested_metrics": [{"definition": draft, "yaml_preview": "metric:"}],
        "suggestion_action": "save_metric",
        "duplicate_notices": [],
    }

    await dedupe_reviewed_suggestions(async_session, db_id, state)
    result = state

    assert result["suggested_metrics"] == []
    assert result["suggestion_action"] is None
    assert result["duplicate_notices"][0]["existing_metric_id"] == existing.id
    assert result["duplicate_notices"][0]["existing_definition"]["metric"]["name"] == existing.name
    assert result["duplicate_notices"][0]["existing_yaml"]


@pytest.mark.asyncio
async def test_prefers_approved_existing_and_ignores_deleted(async_session) -> None:
    db_id = await _seed_order_table(async_session)
    older = await create_metric(async_session, db_id, {"definition": _definition("Older draft")}, 1)
    approved = await create_metric(
        async_session, db_id, {"definition": _definition("Approved")}, 1, status_override="approved"
    )
    later = await create_metric(
        async_session, db_id, {"definition": _definition("Later approved")}, 1, status_override="approved"
    )
    state = {"suggested_metrics": [{"definition": _definition("New")}]}
    await dedupe_reviewed_suggestions(async_session, db_id, state)
    result = state
    assert result["duplicate_notices"][0]["existing_metric_id"] == approved.id

    approved.is_deleted = True
    later.is_deleted = True
    result = {"suggested_metrics": [{"definition": _definition("New")}]}
    await dedupe_reviewed_suggestions(async_session, db_id, result)
    assert result["duplicate_notices"][0]["existing_metric_id"] == older.id

    older.is_deleted = True
    result = {"suggested_metrics": [{"definition": _definition("New")}]}
    await dedupe_reviewed_suggestions(async_session, db_id, result)
    assert len(result["suggested_metrics"]) == 1
    assert result.get("duplicate_notices", []) == []


@pytest.mark.asyncio
async def test_uncanonical_existing_preserves_suggestion_and_reports_incomplete(async_session) -> None:
    db_id = await _seed_order_table(async_session)
    existing = await create_metric(async_session, db_id, {"definition": _definition("Saved")}, 1)
    existing.definition = {}
    state = {"suggested_metrics": [{"definition": _definition("New")}]}

    await dedupe_reviewed_suggestions(async_session, db_id, state)
    result = state

    assert len(result["suggested_metrics"]) == 1
    assert result["dedupe_performed"] is False


@pytest.mark.asyncio
async def test_unresolvable_proposal_preserves_suggestion_and_reports_incomplete(async_session) -> None:
    db_id = await _seed_order_table(async_session)
    await create_metric(async_session, db_id, {"definition": _definition("Saved")}, 1)
    draft = _definition("New")
    draft["metric"]["base_entity"] = "missing_table"
    state = {"suggested_metrics": [{"definition": draft}]}

    await dedupe_reviewed_suggestions(async_session, db_id, state)
    result = state

    assert len(result["suggested_metrics"]) == 1
    assert result["dedupe_performed"] is False


@pytest.mark.asyncio
async def test_unavailable_catalog_preserves_suggestion_and_reports_incomplete() -> None:
    db = AsyncMock()
    db.scalars.side_effect = RuntimeError("catalog unavailable")
    state = {"suggested_metrics": [{"definition": _definition("New")}]}

    await dedupe_reviewed_suggestions(db, 1, state)

    assert len(state["suggested_metrics"]) == 1
    assert state["dedupe_performed"] is False


async def test_persistence_cannot_reclassify_reviewed_decision():
    db = AsyncMock()
    state = {"suggested_metrics": [{"definition": _definition("Reviewed")}], "reviewed_proposals": []}
    result = await persist_reviewed_state(db, 1, 1, state)
    assert result is state
    assert len(result["suggested_metrics"]) == 1
    assert "duplicate_notices" not in result
    db.scalars.assert_not_awaited()
