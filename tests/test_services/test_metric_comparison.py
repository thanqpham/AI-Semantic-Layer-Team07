"""Tests for deterministic catalog metric comparison."""

from typing import Any

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


def _ratio_metric(metric_id: int, ratio: dict[str, Any], side_filter: str) -> dict:
    return {
        "metric_id": metric_id,
        "name": f"Metric {metric_id}",
        "status": "approved",
        "version": 1,
        "definition": {
            "schema_version": 2,
            "metric": {
                "name": f"Metric {metric_id}",
                "formula": {
                    "function": "SUM",
                    "expression": "amount",
                    "ratio": {
                        **ratio,
                        "numerator": {
                            **ratio["numerator"],
                            "filters": [{"field": "region", "operator": "eq", "value": side_filter}],
                        },
                    },
                },
                "base_entity": "orders",
                "base_entity_id": 1,
                "grain": {"column_ids": [1]},
                "filters": [],
                "status": "approved",
                "confidence": "high",
            },
        },
    }


def test_ratio_scale_is_part_of_metric_identity() -> None:
    ratio = {
        "numerator": {"function": "SUM", "expression": "amount"},
        "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
        "scale": 1,
    }
    metrics = [
        _ratio_metric(1, ratio, "west"),
        _ratio_metric(2, {**ratio, "scale": 100}, "west"),
    ]

    assert compare_catalog_metrics(metrics) == []


def test_ratio_side_filters_are_compared_and_returned() -> None:
    ratio = {
        "numerator": {"function": "SUM", "expression": "amount"},
        "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
        "scale": 1,
    }
    groups = compare_catalog_metrics(
        [_ratio_metric(1, ratio, "west"), _ratio_metric(2, ratio, "east")]
    )

    assert len(groups) == 1
    assert groups[0].group_type == "near_duplicate"
    assert groups[0].members[0].ratio is not None
    assert groups[0].core_formula == "0.0 + 1.0 × (SUM(amount)) / (COUNT_DISTINCT(id))"


def test_ratio_filter_moving_between_sides_is_not_an_exact_duplicate() -> None:
    ratio = {
        "numerator": {"function": "SUM", "expression": "amount"},
        "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
        "scale": 1,
    }
    numerator_filter = _ratio_metric(1, ratio, "west")
    denominator_filter = _ratio_metric(2, ratio, "west")
    definition = denominator_filter["definition"]["metric"]["formula"]["ratio"]
    definition["numerator"]["filters"] = []
    definition["denominator"]["filters"] = [
        {"field": "region", "operator": "eq", "value": "west"}
    ]

    groups = compare_catalog_metrics([numerator_filter, denominator_filter])
    assert len(groups) == 1
    assert groups[0].group_type == "near_duplicate"
