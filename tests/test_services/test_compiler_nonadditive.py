import pytest

from src.models.metric_definition import MetricPlanStage
from src.services.query_compiler_plan import _stage_sql
from src.services.semantic_compile_error import SemanticCompileError


@pytest.mark.parametrize("function", ["AVG", "COUNT_DISTINCT"])
def test_rejects_rollup_of_non_additive_aggregate(function: str) -> None:
    source = MetricPlanStage.model_validate(
        {
            "name": "per_customer",
            "base_entity": "orders",
            "group_by": [{"name": "customer", "expression": "orders.customer_id"}],
            "aggregates": [{"name": "value", "function": function, "expression": "orders.amount"}],
        }
    )
    result = MetricPlanStage.model_validate(
        {
            "name": "summary",
            "source_stage": "per_customer",
            "aggregates": [{"name": "total", "function": "SUM", "expression": "per_customer.value"}],
        }
    )
    with pytest.raises(SemanticCompileError) as error:
        _stage_sql(result, {source.name: source}, {}, {}, {}, "sqlite", {}, {})
    assert error.value.code == "INCOMPATIBLE_GRAIN"


def test_rejects_rollup_of_ratio_from_aggregate_outputs() -> None:
    source = MetricPlanStage.model_validate(
        {
            "name": "per_customer",
            "base_entity": "orders",
            "group_by": [{"name": "customer", "expression": "orders.customer_id"}],
            "aggregates": [
                {"name": "sales", "function": "SUM", "expression": "orders.amount"},
                {"name": "count", "function": "COUNT", "expression": "orders.id"},
            ],
        }
    )
    result = MetricPlanStage.model_validate(
        {
            "name": "summary",
            "source_stage": "per_customer",
            "aggregates": [
                {"name": "average", "function": "AVG", "expression": "per_customer.sales / per_customer.count"}
            ],
        }
    )
    with pytest.raises(SemanticCompileError) as error:
        _stage_sql(result, {source.name: source}, {}, {}, {}, "sqlite", {}, {})
    assert error.value.code == "INCOMPATIBLE_GRAIN"


def test_rejects_nonadditive_aggregate_as_grouping_key() -> None:
    source = MetricPlanStage.model_validate({
        "name": "per_customer", "base_entity": "orders",
        "group_by": [{"name": "customer", "expression": "orders.customer_id"}],
        "aggregates": [{"name": "average", "function": "AVG", "expression": "orders.amount"}],
    })
    result = MetricPlanStage.model_validate({
        "name": "summary", "source_stage": "per_customer",
        "group_by": [{"name": "average", "expression": "per_customer.average"}],
        "aggregates": [{"name": "count", "function": "COUNT", "expression": "*"}],
    })
    with pytest.raises(SemanticCompileError) as error:
        _stage_sql(result, {source.name: source}, {}, {}, {}, "sqlite", {}, {})
    assert error.value.code == "INCOMPATIBLE_GRAIN"
