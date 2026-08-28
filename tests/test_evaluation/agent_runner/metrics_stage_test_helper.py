"""Shared fake MetricDefinition builder for agent_runner tests."""

from src.models.metric_definition import MetricDefinition, MetricSpec


def make_definition(name: str, expression: str = "gross_amount") -> MetricDefinition:
    """Build a minimal draft definition with a SUM-over-expression formula.

    The default expression must be a real ``fact_orders`` column so definitions
    survive the DB-backed create/approve path (golden schema has ``gross_amount``,
    not ``total_amount``).
    """
    return MetricDefinition(
        schema_version=1,
        metric=MetricSpec(
            name=name,
            formula={"function": "SUM", "expression": expression},
            base_entity="fact_orders",
            filters=[],
            status="pending_approval",
        ),
    )
