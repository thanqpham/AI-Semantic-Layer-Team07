"""Deterministic compiler gates and curated knowledge contracts."""

from unittest.mock import patch

import pytest

from src.services.metric_knowledge import load_metric_knowledge
from src.services.metric_proposal_generation import prepare_proposal_context
from src.services.metric_review_validation import technical_review
from tests.metric_review_helpers import context, definition, schema


@pytest.mark.parametrize(
    "expression", ["id / id", "amount / amount", "amount / 0", "CASE WHEN id > 0 THEN amount ELSE 0 END"]
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
    assert len(aov["variants"]) == 2 and aov["variants"][0]["formula"] != aov["variants"][1]["formula"]
    assert all(s["url"].startswith("https://") for s in data["sources"])
    assert "eval/" not in str(data) and "expected" not in str(data)


def test_oversize_context_is_rejected_without_truncation():
    with patch("src.services.metric_proposal_generation.get_settings") as settings:
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
