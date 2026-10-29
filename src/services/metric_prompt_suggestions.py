"""Return deterministic prompt suggestions supported by a fresh semantic schema."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import SemanticDatabaseModel
from src.models.schemas import MetricPromptSuggestionItem
from src.services.metric_context import load_review_schema
from src.services.metric_review_validation import schema_tables, technical_review


@dataclass(frozen=True)
class _Suggestion:
    item: MetricPromptSuggestionItem
    definition: dict[str, Any]
    required_values: tuple[tuple[str, str, str], ...] = ()


_CATALOG = (
    _Suggestion(
        MetricPromptSuggestionItem(
            id="total_revenue", title="Tổng doanh thu", prompt="Tính tổng doanh thu từ các đơn hàng.", icon="payments"
        ),
        {
            "name": "Tổng doanh thu",
            "base_entity": "orders",
            "formula": {"function": "SUM", "expression": "amount"},
            "filters": [],
        },
    ),
    _Suggestion(
        MetricPromptSuggestionItem(
            id="average_order_value",
            title="Giá trị đơn hàng trung bình",
            prompt="Tính giá trị đơn hàng trung bình từ tổng giá trị chia cho số đơn hàng duy nhất.",
            icon="shopping_bag",
        ),
        {
            "name": "Giá trị đơn hàng trung bình",
            "base_entity": "orders",
            "formula": {
                "function": "COUNT",
                "expression": "*",
                "ratio": {
                    "numerator": {"function": "SUM", "expression": "amount"},
                    "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
                },
            },
            "filters": [],
        },
    ),
    _Suggestion(
        MetricPromptSuggestionItem(
            id="completed_orders",
            title="Đơn hàng hoàn tất",
            prompt="Đếm số đơn hàng có trạng thái hoàn tất.",
            icon="task_alt",
        ),
        {
            "name": "Đơn hàng hoàn tất",
            "base_entity": "orders",
            "formula": {"function": "COUNT_DISTINCT", "expression": "id"},
            "filters": [{"field": "status", "operator": "eq", "value": "completed"}],
        },
        (("orders", "status", "completed"),),
    ),
    _Suggestion(
        MetricPromptSuggestionItem(
            id="revenue_by_region",
            title="Doanh thu theo khu vực",
            prompt="Tính doanh thu theo khu vực của khách hàng.",
            icon="map",
        ),
        {
            "name": "Doanh thu theo khu vực",
            "base_entity": "orders",
            "formula": {"function": "COUNT", "expression": "*"},
            "filters": [],
            "query_plan": {
                "stages": [
                    {
                        "name": "revenue_by_region",
                        "base_entity": "orders",
                        "joins": ["customers"],
                        "group_by": [{"name": "region", "expression": "customers.region"}],
                        "aggregates": [{"name": "revenue", "function": "SUM", "expression": "orders.amount"}],
                    }
                ],
                "output_expression": "revenue_by_region.revenue",
            },
        },
    ),
)


async def get_metric_prompt_suggestions(
    db: AsyncSession, db_id: int, query_supported: bool
) -> list[MetricPromptSuggestionItem]:
    """Return only catalog entries proven by the current canonical metadata."""
    if not query_supported:
        return []
    database = await db.get(SemanticDatabaseModel, db_id)
    if database is None or not database.schema_fingerprint or database.sync_status != "synced":
        return []
    schema = await load_review_schema(db, db_id)
    if not schema.get("tables"):
        return []
    return _eligible_suggestions(schema, query_supported)


def _eligible_suggestions(schema: dict[str, Any], query_supported: bool) -> list[MetricPromptSuggestionItem]:
    if not query_supported:
        return []
    context = {"schema": schema}
    eligible = []
    for candidate in _CATALOG:
        if not _required_values_exist(schema, candidate.required_values):
            continue
        definition, review = technical_review(deepcopy(candidate.definition), context)
        if definition is not None and review is None:
            eligible.append(candidate.item)
    return eligible


def _required_values_exist(schema: dict[str, Any], requirements: tuple[tuple[str, str, str], ...]) -> bool:
    tables = {table["table_name"].casefold(): table for table in schema_tables(schema)}
    for table_name, column_name, value in requirements:
        table = tables.get(table_name.casefold())
        column = (
            next(
                (item for item in table.get("columns", []) if item["column_name"].casefold() == column_name.casefold()),
                None,
            )
            if table
            else None
        )
        if not column or column.get("review_status") != "approved" or value not in (column.get("allowed_values") or []):
            return False
    return True
