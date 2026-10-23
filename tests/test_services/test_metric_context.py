"""Regression tests for relationship-complete Metric AI context."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.services.metric_context import (
    _DATA_SCOPE_PROMPT,
    _SCOPE_PROMPT,
    _expand_context,
    _select_tables,
    _temporal_context,
    _token_estimate,
)
from tests.metric_review_helpers import scope_mock


@pytest.mark.asyncio
async def test_data_scope_clarification_preserves_selectable_options() -> None:
    """Data questions can still ask users to narrow an unclear domain."""
    payload = {
        "needs_clarification": True,
        "question": "Bạn muốn xem bảng nào?",
        "options": ["Bảng đơn hàng", "Bảng khách hàng"],
    }
    with (
        patch("src.services.metric_context.get_llm"),
        patch("src.services.metric_context.ainvoke_json", new=AsyncMock(return_value=payload)),
    ):
        _, diagnostic = await _select_tables(
            "Tìm thông tin", [], [_table("order_header"), _table("customer")], None, _DATA_SCOPE_PROMPT
        )
    assert [item["label"] for item in diagnostic["clarification"]["options"]] == payload["options"]
    assert all(item.get("action") is None for item in diagnostic["clarification"]["options"])


@pytest.mark.asyncio
async def test_metric_scope_uses_selected_table_without_asking_for_price_column() -> None:
    payload = {
        "table_names": ["order_header"],
        "needs_clarification": True,
        "question": "Chọn price_after_tax hay price_after_discount?",
        "options": ["price_after_tax", "price_after_discount"],
    }
    model = scope_mock(payload)
    with patch("src.services.metric_context.invoke_metric_json", new=model):
        selected, diagnostic = await _select_tables(
            "Tính giá trị trung bình mỗi đơn", [], [_table("order_header")], None
        )
    assert selected == {"order_header"}
    assert diagnostic is None
    prompt = model.call_args.args[1]
    assert "Không hỏi người dùng chọn cột giá" in prompt
    assert "Ví dụ hỏi AOV theo giá nào" not in prompt


@pytest.mark.parametrize("options", [None, "price", [None, {}, "  "]])
def test_scope_clarification_ignores_invalid_options(options) -> None:
    """Malformed model choices leave a usable free-text question without crashing."""
    from src.services.metric_context import _clarification

    result = _clarification("Chọn giá nào?", options)
    assert result.diagnostic["clarification"]["options"] == []


def _column(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        column_name=name,
        data_type="INTEGER",
        business_name=name,
        description="",
        is_primary_key=name == "id",
        is_nullable=False,
        allowed_values=None,
        review_status="approved",
        is_foreign_key=name.endswith("_id") and name != "id",
        fk_target_table=None,
        fk_target_column=None,
    )


def _table(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        table_name=name, business_name=name, description="", columns=[_column("id")], review_status="approved"
    )


def test_context_keeps_late_business_tables_and_relationships() -> None:
    """A context must retain order tables regardless of their original JSON position."""
    tables = [_table(f"lookup_{index}") for index in range(30)] + [_table("order_header"), _table("order_line")]
    relation = SimpleNamespace(
        from_entity=tables[-1],
        to_entity=tables[-2],
        join_condition="order_line.order_id = order_header.id",
        relationship_type="many_to_one",
    )

    context = _expand_context(tables, [relation], {"order_header", "order_line"})

    assert {table["table_name"] for table in context["tables"]} == {"order_header", "order_line"}
    assert context["relationships"][0]["join_condition"] == "order_line.order_id = order_header.id"


def test_context_does_not_expand_unrelated_direct_neighbors() -> None:
    """A table-only question keeps all its columns without adding joined tables."""
    order_header, customer = _table("order_header"), _table("customer")
    relation = SimpleNamespace(
        from_entity=order_header,
        to_entity=customer,
        join_condition="order_header.customer_id = customer.id",
        relationship_type="many_to_one",
    )

    context = _expand_context([order_header, customer], [relation], {"order_header"})

    assert [table["table_name"] for table in context["tables"]] == ["order_header"]
    assert context["relationships"] == []


def test_token_estimate_has_no_character_truncation_contract() -> None:
    """Budgeting reports a size and never mutates or slices the input payload."""
    payload = {"tables": [{"table_name": f"table_{index}"} for index in range(1000)]}

    assert _token_estimate(payload) > 2000
    assert len(payload["tables"]) == 1000


def test_scope_prompt_formats_its_json_contract() -> None:
    """The JSON example must not be interpreted as a Python format field."""
    prompt = _SCOPE_PROMPT.format(inventory="[]", question="Tính doanh thu theo ngày")

    assert '"table_names"' in prompt
    assert "Tính doanh thu theo ngày" in prompt


def test_temporal_context_lists_fields_across_schema() -> None:
    """Date/time discovery must not be rejected as a broad KPI."""
    order = _table("order_header")
    order.columns.append(SimpleNamespace(**{**_column("completed_time").__dict__, "data_type": "TIMESTAMP"}))
    customer = _table("customer")
    customer.columns.append(SimpleNamespace(**{**_column("birth_date").__dict__, "data_type": "DATE"}))

    result = _temporal_context([order, customer])

    assert result.diagnostic["status"] == "ready"
    assert {item["table_name"] for item in result.schema["tables"]} == {"order_header", "customer"}
    assert result.schema["tables"][0]["columns"][0]["column_name"] == "completed_time"
