"""Direct unit tests for shared/residual filter keying in query_compiler_sql."""

from typing import Any

import pytest

from src.models.metric_definition import MetricDefinition, MetricExpressionNode, MetricFilter
from src.services.query_compiler_sql import _compile_argument, _residual_filters, _resolved_filter, _shared_filters
from src.services.semantic_compile_error import SemanticCompileError


def _definition(name: str, filters: list[dict[str, Any]]) -> MetricDefinition:
    """Build a canonical v2 definition mirroring the compiler test fixture shape."""
    return MetricDefinition.model_validate(
        {
            "schema_version": 2,
            "metric": {
                "name": name,
                "formula": {
                    "function": "SUM",
                    "expression": "amount",
                    "expression_ast": {"kind": "column", "column_id": 2},
                },
                "base_entity": "orders",
                "base_entity_id": 1,
                "grain": {"column_ids": [1]},
                "filters": filters,
                "status": "approved",
                "confidence": "high",
                "excluded_notes": "",
            },
        }
    )


def test_same_declared_key_different_column_id_is_not_shared() -> None:
    """Same (field, operator, value) on different columns must not intersect."""
    first = _definition("A", [{"field": "status", "column_id": 101, "operator": "eq", "value": "completed"}])
    second = _definition("B", [{"field": "status", "column_id": 202, "operator": "eq", "value": "completed"}])

    shared = _shared_filters([first, second])
    assert shared == []
    assert _residual_filters(first, shared) == first.metric.filters
    assert _residual_filters(second, shared) == second.metric.filters


def test_identical_filters_are_shared() -> None:
    """Identical (field, operator, value, column_id) hoists and leaves no residual."""
    first = _definition("A", [{"field": "status", "column_id": 101, "operator": "eq", "value": "completed"}])
    second = _definition("B", [{"field": "status", "column_id": 101, "operator": "eq", "value": "completed"}])

    shared = _shared_filters([first, second])
    assert shared == first.metric.filters
    assert _residual_filters(first, shared) == []
    assert _residual_filters(second, shared) == []


def test_empty_definitions_yield_no_shared_filters() -> None:
    """No definitions means no shared filters."""
    assert _shared_filters([]) == []


def test_partial_overlap_keeps_only_common() -> None:
    """Only the predicate common to every definition is hoisted."""
    first = _definition(
        "A",
        [
            {"field": "status", "column_id": 101, "operator": "eq", "value": "completed"},
            {"field": "is_test", "column_id": 103, "operator": "eq", "value": 0},
        ],
    )
    second = _definition(
        "B",
        [
            {"field": "is_test", "column_id": 103, "operator": "eq", "value": 0},
            {"field": "region", "column_id": 104, "operator": "eq", "value": "north"},
        ],
    )

    shared = _shared_filters([first, second])
    assert shared == [first.metric.filters[1]]
    assert _residual_filters(first, shared) == [first.metric.filters[0]]
    assert _residual_filters(second, shared) == [second.metric.filters[1]]


# ---------------------------------------------------------------------------
# _resolved_filter guard — INVALID_FILTER_VALUE (spec §2)
# ---------------------------------------------------------------------------


def test_resolved_filter_rejects_column_reference_value() -> None:
    """A dotted column-reference value is a join in disguise — must fail loud."""
    item = MetricFilter(field="order_id", operator="eq", value="fact_orders.order_id", column_id=101)
    with pytest.raises(SemanticCompileError) as exc_info:
        _resolved_filter(item, {101: "order_id"})
    assert exc_info.value.code == "INVALID_FILTER_VALUE"


def test_resolved_filter_allows_ordinary_string_value() -> None:
    """Ordinary literal values pass through and get the physical column name."""
    item = MetricFilter(field="status", operator="eq", value="completed", column_id=101)
    resolved = _resolved_filter(item, {101: "order_status"})
    assert resolved.field == "order_status"
    assert resolved.value == "completed"


def test_resolved_filter_allows_version_like_and_date_values() -> None:
    """Values that merely contain dots but are not bare identifiers stay allowed."""
    for value in ("v1.0", "2024-01-01"):
        item = MetricFilter(field="v", operator="eq", value=value, column_id=101)
        assert _resolved_filter(item, {101: "v"}).value == value


def test_resolved_filter_allows_non_string_values() -> None:
    """Numeric values bypass the guard entirely."""
    for value in (0, 1.5):
        item = MetricFilter(field="f", operator="eq", value=value, column_id=101)
        assert _resolved_filter(item, {101: "f"}).value == value


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [
        ("sqlite", '(julianday("orders"."delivered_time") - julianday("orders"."order_date")) * 24.0'),
        ("mysql", "TIMESTAMPDIFF(SECOND, `orders`.`order_date`, `orders`.`delivered_time`) / 3600.0"),
        ("postgres", 'EXTRACT(EPOCH FROM ("orders"."delivered_time" - "orders"."order_date")) / 3600.0'),
    ],
)
def test_compile_timestamp_difference_hours_for_each_dialect(dialect: str, expected: str) -> None:
    node = MetricExpressionNode(
        kind="timestamp_diff_hours",
        children=[
            MetricExpressionNode(kind="column", column_id=2),
            MetricExpressionNode(kind="column", column_id=1),
        ],
    )
    assert _compile_argument(node, "orders", {1: "order_date", 2: "delivered_time"}, dialect) == expected
