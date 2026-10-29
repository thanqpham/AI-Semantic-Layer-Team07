"""Lower canonical simple metrics into the existing staged-plan compiler."""

from __future__ import annotations

from src.models.metric_definition import (
    MetricAggregate,
    MetricDefinition,
    MetricPlanAggregate,
    MetricPlanField,
    MetricPlanFilter,
    MetricPlanStage,
    MetricQueryPlan,
)
from src.models.schemas import SemanticQuerySpec


def lower_simple_metric(definition: MetricDefinition, spec: SemanticQuerySpec) -> MetricQueryPlan:
    """Create an in-memory source aggregation plan without changing the definition."""
    metric = definition.metric
    dimensions = [
        MetricPlanField(
            name=f"dimension_{item.column_id}",
            expression=f"column_{item.column_id}",
            column_id=item.column_id,
        )
        for item in spec.dimensions
    ]
    formula = metric.formula
    if formula.ratio is None:
        aggregate = MetricPlanAggregate(
            name="value",
            function=formula.function,
            expression=formula.expression,
        )
        return MetricQueryPlan(
            stages=[
                MetricPlanStage(
                    name="source", base_entity=metric.base_entity, group_by=dimensions, aggregates=[aggregate]
                )
            ],
            output_expression="source.value",
        )
    ratio = formula.ratio
    aggregates = [
        _aggregate("numerator", ratio.numerator),
        _aggregate("denominator", ratio.denominator),
    ]
    expression = f"({ratio.offset} + {ratio.scale} * source.numerator / source.denominator)"
    return MetricQueryPlan(
        stages=[
            MetricPlanStage(name="source", base_entity=metric.base_entity, group_by=dimensions, aggregates=aggregates)
        ],
        output_expression=expression,
    )


def _aggregate(name: str, aggregate: MetricAggregate) -> MetricPlanAggregate:
    return MetricPlanAggregate(
        name=name,
        function=aggregate.function,
        expression=aggregate.expression,
        filters=[_plan_filter(item) for item in aggregate.filters],
    )


def _plan_filter(item) -> MetricPlanFilter:
    return MetricPlanFilter.model_validate(item.model_dump())
