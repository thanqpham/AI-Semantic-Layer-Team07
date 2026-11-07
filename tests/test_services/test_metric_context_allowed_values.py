"""Metric context exposes approved allowed_values without reading live rows."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import SemanticColumnModel, SemanticTableModel
from src.services.metric_context import _column_payload, build_metric_context


@pytest.mark.asyncio
async def test_build_metric_context_uses_stored_allowed_values_only() -> None:
    """Metric context preserves saved allowed_values and does not query the target database."""
    col = SemanticColumnModel(
        id=1,
        column_name="order_status",
        data_type="VARCHAR(20)",
        is_primary_key=False,
        allowed_values=["cancelled", "completed", "returned"],
        review_status="approved",
    )
    table = SemanticTableModel(
        id=10,
        table_name="orders",
        physical_schema="public",
        business_name="Đơn hàng",
        description="Bảng đơn hàng",
        columns=[col],
    )

    mock_db = AsyncMock(spec=AsyncSession)

    with (
        patch("src.services.metric_context._load_metadata", new_callable=AsyncMock) as mock_load,
        patch("src.services.metric_context._select_tables", new_callable=AsyncMock) as mock_select,
    ):
        mock_load.return_value = ([table], [])
        mock_select.return_value = ({"orders"}, None)

        result = await build_metric_context(mock_db, db_id=1, question="Đơn hoàn tất", token_budget=4000)

        assert result.diagnostic["status"] == "ready"
        schema_col = result.schema["tables"][0]["columns"][0]
        assert schema_col["allowed_values"] == ["cancelled", "completed", "returned"]


def test_pending_values_are_not_in_agent_context() -> None:
    """A pending edit cannot leak categorical values to an agent."""
    col = SemanticColumnModel(
        column_name="status", data_type="TEXT", allowed_values=["private@example.test"], review_status="pending_review"
    )
    assert _column_payload(col)["allowed_values"] is None
    col.review_status = "approved"
    assert _column_payload(col)["allowed_values"] is None


def test_pending_business_labels_are_not_in_agent_context() -> None:
    col = SemanticColumnModel(
        column_name="status",
        data_type="TEXT",
        review_status="approved",
        allowed_values=["paid"],
        allowed_value_mappings=[{"db_value": "paid", "business_value": "Paid", "status": "pending"}],
    )
    assert _column_payload(col)["allowed_values"] == ["paid"]
    assert _column_payload(col)["allowed_value_mappings"] == []


def test_context_keeps_approved_mappings_without_sample_value_heuristics() -> None:
    col = SemanticColumnModel(
        column_name="customer_name",
        data_type="TEXT",
        review_status="approved",
        allowed_values_complete=False,
        allowed_value_mappings=[
            {"db_value": "001", "business_value": "Customer Name, Tier 1!", "status": "approved"},
            {"db_value": "alice@example.test", "business_value": "VIP Account Manager", "status": "approved"},
            {"db_value": "pending", "business_value": "Pending", "status": "pending"},
        ],
    )
    payload = _column_payload(col)
    assert [item["db_value"] for item in payload["allowed_value_mappings"]] == ["001", "alice@example.test"]
    assert [type(item["db_value"]) for item in payload["allowed_value_mappings"]] == [str, str]
    assert payload["allowed_values_complete"] is False
    col.review_status = "pending_review"
    assert _column_payload(col)["allowed_value_mappings"] == []


def test_context_keeps_large_approved_mapping_lists_complete() -> None:
    col = SemanticColumnModel(
        column_name="status",
        data_type="TEXT",
        review_status="approved",
        allowed_value_mappings=[
            {"db_value": index, "business_value": f"Tier {index}!", "status": "approved"} for index in range(25)
        ],
    )

    assert len(_column_payload(col)["allowed_value_mappings"]) == 25
