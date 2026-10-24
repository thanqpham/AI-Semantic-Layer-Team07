"""Approved metric explanations must preserve the compiled calculation."""

from src.services.approved_metric_definition import build_approved_metric_definition_response
from tests.metric_review_helpers import definition
from tests.test_services.test_metric_review import cancellation_definition


def test_approved_ratio_explanation_includes_both_sides_transforms_and_filters():
    raw = cancellation_definition()
    ratio = raw["metric"]["formula"]["ratio"]
    ratio.update(scale=100, offset=1)
    ratio["denominator"]["filters"] = [{"field": "eligible", "operator": "eq", "value": True}]
    raw["metric"]["filters"] = [{"field": "region", "operator": "eq", "value": "north"}]
    name = raw["metric"]["name"]
    response = build_approved_metric_definition_response(
        f"Công thức chỉ số {name}", [{"id": 1, "name": name, "definition": raw}]
    )
    assert "1 + 100 × (COUNT_DISTINCT(id)) / (COUNT_DISTINCT(id))" in response
    assert "Bộ lọc tử số" in response and "status = 'cancelled'" in response
    assert "Bộ lọc mẫu số" in response and "eligible = True" in response
    assert "region = 'north'" in response


def test_approved_simple_aggregation_explanation_stays_available():
    raw = definition()
    name = raw["metric"]["name"]
    response = build_approved_metric_definition_response(
        f"Công thức chỉ số {name}", [{"id": 1, "name": name, "definition": raw}]
    )
    assert "SUM(amount)" in response
    assert "Bộ lọc tử số" not in response
