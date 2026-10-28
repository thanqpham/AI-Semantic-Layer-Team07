"""End-to-end regression test for Data Lead metric context and stored allowed_values."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.db import SemanticColumnModel, SemanticTableModel
from src.services.metric_context import build_metric_context


@pytest.mark.asyncio
async def test_datalead_proposal_context_includes_saved_allowed_values() -> None:
    """Demonstrate that approved metadata reaches the AI metric designer unchanged."""
    status_col = SemanticColumnModel(
        id=1,
        column_name="order_status",
        data_type="VARCHAR(20)",
        is_primary_key=False,
        allowed_values=["cancelled", "completed", "returned"],
        review_status="approved",
    )
    method_col = SemanticColumnModel(
        id=2,
        column_name="payment_method",
        data_type="VARCHAR(30)",
        is_primary_key=False,
        allowed_values=["credit_card", "e_wallet"],
        review_status="approved",
    )
    orders_table = SemanticTableModel(
        id=10,
        table_name="orders",
        physical_schema="public",
        business_name="Đơn hàng",
        description="Bảng đơn hàng",
        columns=[status_col, method_col],
    )

    mock_db = AsyncMock()

    with (
        patch("src.services.metric_context._load_metadata", new_callable=AsyncMock) as mock_load,
        patch("src.services.metric_context._select_tables", new_callable=AsyncMock) as mock_select,
    ):
        mock_load.return_value = ([orders_table], [])
        mock_select.return_value = ({"orders"}, None)

        result = await build_metric_context(
            mock_db,
            db_id=1,
            question="Tạo metric Tỷ lệ đơn hàng hoàn tất thanh toán qua ví điện tử",
            token_budget=4000,
        )

        assert result.diagnostic["status"] == "ready"
        table_schema = result.schema["tables"][0]
        col_map = {c["column_name"]: c for c in table_schema["columns"]}

        assert col_map["order_status"]["allowed_values"] == ["cancelled", "completed", "returned"]
        assert col_map["payment_method"]["allowed_values"] == ["credit_card", "e_wallet"]
