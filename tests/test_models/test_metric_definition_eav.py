"""MetricSpec EAV reference parsing and backward compatibility."""

from src.models.metric_definition import MetricDefinition


def _eav_definition_payload() -> dict:
    return {
        "metric": {
            "name": "Tổng doanh thu",
            "formula": {"function": "SUM", "expression": "revenue"},
            "base_entity": "entity_eav",
            "eav": {
                "config_id": 1,
                "attribute_id": 2,
                "attribute_key": "revenue",
                "data_type": "number",
                "multi_value_rule": "reject",
                "history_enabled": False,
            },
        }
    }


def test_definition_with_eav_reference_round_trips():
    definition = MetricDefinition.model_validate(_eav_definition_payload())
    assert definition.metric.eav is not None
    assert definition.metric.eav.attribute_id == 2
    dumped = definition.model_dump(mode="json")
    assert dumped["metric"]["eav"]["attribute_key"] == "revenue"
    reparsed = MetricDefinition.model_validate(dumped)
    assert reparsed.metric.eav == definition.metric.eav


def test_definition_without_eav_still_parses():
    definition = MetricDefinition.model_validate(
        {"metric": {"name": "Số đơn", "formula": {"function": "COUNT", "expression": "*"}, "base_entity": "orders"}}
    )
    assert definition.metric.eav is None
    assert "eav" not in definition.model_dump(mode="json", exclude_none=True)["metric"]
