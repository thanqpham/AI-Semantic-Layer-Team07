"""Tests for deterministic catalog metric comparison."""

from src.services.metric_comparison import compare_catalog_metrics


def _metric(metric_id: int, name: str, filters: list[dict] | None = None, function: str = "SUM") -> dict:
    return {
        "metric_id": metric_id,
        "name": name,
        "status": "approved",
        "version": 1,
        "definition": {
            "metric": {
                "name": name,
                "formula": {"function": function, "expression": "amount"},
                "base_entity": "orders",
                "grain": {"column_ids": [1]},
                "filters": filters or [],
            }
        },
    }


def test_same_core_and_filters_is_exact_duplicate() -> None:
    groups = compare_catalog_metrics([_metric(1, "Revenue A"), _metric(2, "Revenue B")])
    assert [group.group_type for group in groups] == ["exact_duplicate"]


def test_same_core_different_filters_is_near_duplicate() -> None:
    groups = compare_catalog_metrics([
        _metric(1, "Revenue", [{"field": "status", "operator": "eq", "value": "done"}]),
        _metric(2, "Revenue Done", [{"field": "status", "operator": "eq", "value": "paid"}]),
    ])
    assert len(groups) == 1
    assert groups[0].group_type == "near_duplicate"


def test_filter_order_and_in_value_order_do_not_change_identity() -> None:
    filters_a = [
        {"field": "status", "operator": "in", "value": ["done", "paid"]},
        {"field": "region", "operator": "eq", "value": "north"},
    ]
    filters_b = [
        {"field": "region", "operator": "eq", "value": "north"},
        {"field": "status", "operator": "in", "value": ["paid", "done"]},
    ]
    groups = compare_catalog_metrics([_metric(1, "A", filters_a), _metric(2, "B", filters_b)])
    assert groups[0].group_type == "exact_duplicate"


def test_different_core_and_invalid_definition_are_ignored() -> None:
    metrics = [_metric(1, "Revenue"), _metric(2, "Count", function="COUNT"), {"metric_id": 3, "definition": None}]
    assert compare_catalog_metrics(metrics) == []
