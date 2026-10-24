"""Tests for deterministic catalog metric comparison."""

from copy import deepcopy

import pytest

from src.models.metric_definition import MetricDefinition
from src.services.metric_comparison import compare_catalog_metrics, metric_identity


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
    groups = compare_catalog_metrics(
        [
            _metric(1, "Revenue", [{"field": "status", "operator": "eq", "value": "done"}]),
            _metric(2, "Revenue Done", [{"field": "status", "operator": "eq", "value": "paid"}]),
        ]
    )
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


@pytest.mark.parametrize(
    "change",
    [
        ("base_entity_id", 9),
        ("grain", {"column_ids": [9]}),
        ("formula", {"function": "COUNT", "expression": "amount"}),
        ("formula", {"function": "SUM", "expression": "amount + 1"}),
        ("filters", [{"field": "status", "column_id": 3, "operator": "eq", "value": 0}]),
        ("filters", [{"field": "region", "column_id": 4, "operator": "eq", "value": "0"}]),
    ],
)
def test_identity_distinguishes_calculation_changes(change: tuple[str, object]) -> None:
    original = _metric(1, "A", [{"field": "status", "column_id": 3, "operator": "eq", "value": "0"}])
    changed = deepcopy(original)
    changed["definition"]["metric"][change[0]] = change[1]
    first = MetricDefinition.model_validate(original["definition"])
    second = MetricDefinition.model_validate(changed["definition"])
    assert metric_identity(first) != metric_identity(second)


def test_identity_ignores_name_filter_order_and_in_order() -> None:
    filters = [
        {"field": "status", "column_id": 3, "operator": "in", "value": ["done", "paid"]},
        {"field": "region", "column_id": 4, "operator": "eq", "value": "north"},
    ]
    first = _metric(1, "A", filters)
    second = _metric(2, "B", [filters[1], {**filters[0], "value": ["paid", "done"]}])
    assert metric_identity(MetricDefinition.model_validate(first["definition"])) == metric_identity(
        MetricDefinition.model_validate(second["definition"])
    )


def _ratio_metric(metric_id=1):
    metric = _metric(metric_id, "Cancellation rate", function="COUNT_DISTINCT")
    formula = metric["definition"]["metric"]["formula"]
    formula.update(
        expression="id",
        ratio={
            "numerator": {
                "function": "COUNT_DISTINCT",
                "expression": "id",
                "filters": [{"field": "status", "operator": "eq", "value": "Canceled"}],
            },
            "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
        },
    )
    return metric


def test_cancellation_ratio_is_not_total_orders():
    ratio = _ratio_metric()
    total = deepcopy(ratio)
    total["definition"]["metric"]["formula"].pop("ratio")
    assert metric_identity(MetricDefinition.model_validate(ratio["definition"])) != metric_identity(
        MetricDefinition.model_validate(total["definition"])
    )
    assert compare_catalog_metrics([ratio, total]) == []


@pytest.mark.parametrize("change", ["numerator", "denominator", "scale", "offset", "filter_scope", "filter_value"])
def test_ratio_identity_includes_both_sides_transforms_and_scoped_filters(change):
    first = _ratio_metric()
    second = deepcopy(first)
    ratio = second["definition"]["metric"]["formula"]["ratio"]
    if change in {"scale", "offset"}:
        ratio[change] = 100
    elif change == "filter_scope":
        ratio["denominator"]["filters"] = ratio["numerator"].pop("filters")
    elif change == "filter_value":
        ratio["numerator"]["filters"][0]["value"] = "Completed"
    else:
        ratio[change]["expression"] = "amount"
    assert metric_identity(MetricDefinition.model_validate(first["definition"])) != metric_identity(
        MetricDefinition.model_validate(second["definition"])
    )
