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
    col = SemanticColumnModel(column_name="status", data_type="TEXT", allowed_values=["private@example.test"],
                              review_status="pending_review")
    assert _column_payload(col)["allowed_values"] is None
    col.review_status = "approved"
    assert _column_payload(col)["allowed_values"] is None
