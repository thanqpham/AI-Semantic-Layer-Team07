from src.models.metric_definition import MetricDefinition, MetricPlanStage
from src.models.schemas import SemanticQuerySpec
from src.services.query_compiler_lowering import lower_simple_metric


def test_lower_simple_average_preserves_raw_aggregate_and_definition():
    definition = MetricDefinition.model_validate({
        "schema_version": 2,
        "metric": {"name": "average", "base_entity": "orders", "grain": {"column_ids": []},
                   "formula": {"function": "AVG", "expression": "amount", "expression_ast":
                               {"kind": "column", "column_id": 7}}}
    })
    original_plan = definition.metric.query_plan

    plan = lower_simple_metric(definition, SemanticQuerySpec(metric_ids=[1]))

    assert plan.stages[0].aggregates[0].function == "AVG"
    assert plan.stages[0].aggregates[0].expression == "amount"
    assert definition.metric.query_plan is original_plan
    assert plan.stages[0].group_by == []


def test_lower_simple_metric_preserves_requested_canonical_dimensions():
    definition = MetricDefinition.model_validate({
        "metric": {"name": "revenue", "base_entity": "orders", "formula": {
            "function": "SUM", "expression": "amount"
        }}
    })
    spec = SemanticQuerySpec(metric_ids=[1], dimensions=[{"column_id": 9}])

    plan = lower_simple_metric(definition, spec)

    assert plan.stages[0].group_by[0].column_id == 9
    assert plan.stages[0].group_by[0].expression == "column_9"


def test_lower_simple_metric_preserves_ratio_aggregate_filters():
    definition = MetricDefinition.model_validate({
        "schema_version": 2,
        "metric": {
            "name": "ratio", "base_entity": "orders", "grain": {"column_ids": [9]},
            "formula": {
                "function": "SUM", "expression": "amount",
                "ratio": {
                    "numerator": {"function": "SUM", "expression": "amount", "filters": [
                        {"field": "status", "column_id": 4, "operator": "eq", "value": "paid"}
                    ]},
                    "denominator": {"function": "COUNT", "expression": "*", "filters": [
                        {"field": "status", "column_id": 4, "operator": "eq", "value": "all"}
                    ]},
                },
            },
        },
    })
    spec = SemanticQuerySpec(metric_ids=[1], dimensions=[])

    plan = lower_simple_metric(definition, spec)

    assert len(plan.stages) == 1
    assert plan.stages[0].aggregates[0].filters[0].value == "paid"
    assert plan.stages[0].aggregates[1].filters[0].value == "all"
    assert "/ source.denominator" in plan.output_expression
    assert definition.metric.query_plan is None


def test_simple_and_plan_metrics_can_be_normalized_to_one_bundle_shape():
    plan = lower_simple_metric(
        MetricDefinition.model_validate({
            "metric": {"name": "count", "base_entity": "orders", "formula": {
                "function": "COUNT", "expression": "*"
            }}
        }),
        SemanticQuerySpec(metric_ids=[1]),
    )
    plan_stage = MetricPlanStage(
        name="plan_source", base_entity="returns", aggregates=[{"name": "total", "function": "SUM", "expression": "amount"}]
    )

    assert plan.stages[0].base_entity == "orders"
    assert plan_stage.base_entity == "returns"
