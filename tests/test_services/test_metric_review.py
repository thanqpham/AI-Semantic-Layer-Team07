"""Deterministic compiler gates and curated knowledge contracts."""

from unittest.mock import patch

import pytest
import yaml

from src.models.metric_definition import MetricDefinition
from src.services.metric_knowledge import load_metric_knowledge
from src.services.metric_proposal_context import prepare_proposal_context
from src.services.metric_review import validate_review_draft
from src.services.metric_review_validation import technical_review
from tests.metric_review_helpers import context, definition, schema


def cancellation_definition():
    raw = definition("id", "Tỷ lệ đơn hàng bị hủy")
    raw["metric"]["formula"] = {
        "function": "COUNT_DISTINCT",
        "expression": "id",
        "ratio": {
            "numerator": {
                "function": "COUNT_DISTINCT",
                "expression": "id",
                "filters": [{"field": "status", "operator": "eq", "value": "cancelled"}],
            },
            "denominator": {"function": "COUNT_DISTINCT", "expression": "id", "filters": []},
        },
    }
    return raw


def test_technical_review_accepts_column_metadata():
    resolved, review = technical_review(definition(), context())
    assert review is None, str(review)
    assert resolved.metric.grain.column_ids == [1]


@pytest.mark.parametrize("knowledge_id", [None, "cancellation"])
def test_explicit_cancellation_ratio_reaches_business_review(knowledge_id):
    raw = cancellation_definition()
    resolved, review = validate_review_draft(
        context(),
        {
            "name": raw["metric"]["name"],
            "definition": raw,
            "knowledge_id": knowledge_id,
        },
    )
    assert review is None, str(review)
    assert resolved.metric.formula.ratio.numerator.filters[0].value == "cancelled"


def test_misplaced_ratio_is_preserved_in_canonical_formula():
    raw = cancellation_definition()
    raw["metric"]["ratio"] = raw["metric"]["formula"].pop("ratio")
    parsed = MetricDefinition.model_validate(raw)
    assert parsed.metric.formula.ratio.numerator.filters[0].value == "cancelled"
    assert "ratio" not in parsed.model_dump()["metric"]


def test_cancellation_without_ratio_requires_repair():
    raw = cancellation_definition()
    del raw["metric"]["formula"]["ratio"]
    _, review = validate_review_draft(context(), {"name": raw["metric"]["name"], "definition": raw})
    assert review.status == "needs_revision"
    assert review.issues[0].code == "MISSING_RATIO"


@pytest.mark.parametrize("side", ["numerator", "denominator"])
@pytest.mark.parametrize("expression", ["id / id", "amount / amount", "amount / 0"])
def test_ratio_sides_cannot_bypass_expression_validation(side, expression):
    raw = cancellation_definition()
    raw["metric"]["formula"]["ratio"][side]["expression"] = expression
    _, review = technical_review(raw, context())
    assert review.status == "unsupported"


@pytest.mark.parametrize("side", ["numerator", "denominator"])
@pytest.mark.parametrize("field,value", [("status", "invented"), ("is_test_order", "false")])
def test_ratio_filters_validate_metadata_on_both_sides(side, field, value):
    raw = cancellation_definition()
    raw["metric"]["formula"]["ratio"][side]["filters"] = [{"field": field, "operator": "eq", "value": value}]
    _, review = technical_review(raw, context())
    assert review is not None


@pytest.mark.parametrize(
    "expression",
    ["id / id", "amount / amount", "amount / 0", "amount / 100", "CASE WHEN id > 0 THEN amount ELSE 0 END"],
)
def test_compiler_unsupported_arithmetic_never_passes(expression):
    _, review = technical_review(definition(expression), context())
    assert review.status == "unsupported"


@pytest.mark.parametrize(
    "field,operator,value",
    [
        ("missing", "eq", 1),
        ("status", "eq", "invented"),
        ("is_test_order", "eq", "false"),
        ("amount", "eq", "1"),
        ("status", "eq", 1),
        ("amount", "in", []),
    ],
)
def test_bad_filters_are_not_silently_dropped(field, operator, value):
    raw = definition()
    raw["metric"]["filters"] = [{"field": field, "operator": operator, "value": value}]
    _, review = technical_review(raw, context())
    assert review is not None and review.status != "pass"


def test_missing_grain_and_boolean_aggregation_are_invalid():
    evidence = context()
    evidence["schema"]["tables"][0]["columns"][0]["is_primary_key"] = False
    assert "MISSING_GRAIN" in str(technical_review(definition(), evidence)[1])
    assert technical_review(definition("is_test_order"), context())[1] is not None


def test_knowledge_keeps_aov_variants_and_no_evaluation_dependencies():
    data = load_metric_knowledge()
    assert len(data["metrics"]) == 10
    aov = next(m for m in data["metrics"] if m["id"] == "aov")
    assert len(aov["variants"]) == 5
    formulas = {variant["id"]: variant["formula"] for variant in aov["variants"]}
    assert formulas["shopify_order_value"] != formulas["woocommerce_order_value"]
    assert all(
        formulas[key].startswith("AVG(")
        for key in ("order_average_pre_tax", "order_average_after_tax", "order_average_after_tax_discount")
    )
    assert all(s["url"].startswith("https://") for s in data["sources"])
    assert "eval/" not in str(data) and "expected" not in str(data)


def test_knowledge_reload_reads_updated_bundle_without_changing_previous_snapshot():
    original = yaml.safe_dump(load_metric_knowledge(), allow_unicode=True)
    changed = yaml.safe_load(original)
    changed["metrics"][0]["meaning"] = "Updated business meaning"
    with patch(
        "src.services.metric_knowledge.Path.read_text",
        side_effect=[original, yaml.safe_dump(changed, allow_unicode=True)],
    ):
        previous = load_metric_knowledge()
        current = load_metric_knowledge()
    assert current["metrics"][0]["meaning"] == "Updated business meaning"
    assert previous["metrics"][0]["meaning"] != "Updated business meaning"


def test_oversize_context_is_rejected_without_truncation():
    with patch("src.services.metric_proposal_context.get_settings") as settings:
        settings.return_value.metric_context_token_budget = 2
        with pytest.raises(ValueError, match="Context"):
            prepare_proposal_context({"user_message": "Tính doanh thu", "enriched_schema": schema()})


@pytest.mark.parametrize(
    "raw",
    [
        {"metric": None},
        {"metric": {"filters": "invalid"}},
        {"metric": {"filters": [{"field": "status", "operator": "unknown", "value": "x"}]}},
    ],
)
def test_malformed_contract_is_reported_for_repair(raw):
    _, review = technical_review(raw, context())
    assert review.status == "needs_revision"
