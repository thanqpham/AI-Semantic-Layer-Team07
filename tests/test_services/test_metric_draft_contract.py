"""Regression cases captured from real metric model outputs."""

from unittest.mock import patch

import pytest

from src.agents.workflows.metric_proposal_workflow import run_metric_workflow
from src.config import get_settings
from src.models.metric_review import MetricBuildBatch, MetricReviewBatch
from src.services.metric_knowledge import metric_knowledge
from src.services.metric_review_validation import technical_review
from tests.metric_review_helpers import context, definition, reviewer_mock
from tests.test_services.test_metric_review import cancellation_definition


@pytest.fixture(autouse=True)
def enable_metric_knowledge(monkeypatch):
    monkeypatch.setattr(get_settings(), "metric_knowledge_enabled", True)


def test_backend_rebuilds_agent_supplied_metadata_without_losing_ratio_filters():
    raw = definition()
    spec = raw["metric"]
    spec.update(base_entity_id="orders", grain={"column_ids": ["id"]})
    spec["formula"].update(
        expression_ast="invented",
        ratio={
            "numerator": {
                "function": "SUM",
                "expression": "amount",
                "expression_ast": "invented",
                "filters": [{"field": "status", "column_id": "status", "operator": "eq", "value": "completed"}],
            },
            "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
        },
    )
    resolved, report = technical_review(raw, context())
    assert report is None, str(report)
    assert resolved.metric.grain.column_ids == [1]
    assert resolved.metric.formula.ratio.numerator.filters[0].column_id == 3
    assert resolved.metric.formula.ratio.numerator.filters[0].value == "completed"
    raw["metric"]["formula"]["ratio"]["numerator"]["expression"] = "invented_amount"
    assert technical_review(raw, context())[1] is not None


async def test_reviewer_receives_explicit_scope_for_an_unfiltered_denominator():
    raw = cancellation_definition()
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(
            context(),
            drafts=[
                {
                    "name": raw["metric"]["name"],
                    "definition": raw,
                }
            ],
            allow_repair=False,
        )
    scopes = review.call_args.args[2][0]["filter_scope"]
    assert scopes["denominator"] == "Toàn bộ tập chung, không thêm điều kiện lọc ở phạm vi này."
    assert scopes["numerator"][0] == {"field": "status", "operator": "eq", "value": "cancelled"}
    assert result[0]["review"]["status"] == "pass"


@pytest.mark.parametrize("family", [None, "order_average_pre_tax", "aov"])
async def test_unique_registry_variant_resolves_family_without_guessing_business_logic(family):
    evidence = context()
    evidence["knowledge"] = metric_knowledge("AOV")
    raw = definition(name="Giá trị đơn hàng trung bình trước thuế")
    raw["metric"]["formula"]["function"] = "AVG"
    draft = {
        "name": raw["metric"]["name"],
        "definition": raw,
        "knowledge_id": family,
        "variant_id": "order_average_pre_tax",
    }
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=[draft], allow_repair=False)
    assert result[0]["review"]["status"] == "pass", result[0]["review"]
    assert result[0]["context"]["candidate"]["knowledge_id"] == "aov"
    assert result[0]["review"]["variant_id"] == "order_average_pre_tax"


async def test_discovery_does_not_relabel_before_tax_sales_as_an_aov():
    evidence = context()
    evidence["knowledge"] = metric_knowledge("", discovery=True)
    draft = {"name": "Doanh thu trước thuế", "definition": definition()}
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=[draft], allow_repair=False)
    assert result[0]["review"]["status"] == "pass", result[0]["review"]
    assert result[0]["context"]["candidate"]["knowledge_id"] is None


@pytest.mark.parametrize(
    "family,criteria",
    [
        ("net_sales", {}),
        ("invented", {}),
        ("aov", {"tax_basis": "includes_tax"}),
    ],
)
async def test_conflicting_registry_identity_or_criteria_are_not_silently_corrected(family, criteria):
    evidence = context()
    evidence["knowledge"] = metric_knowledge("", discovery=True)
    raw = definition(name="Giá trị đơn hàng trung bình trước thuế")
    raw["metric"]["formula"]["function"] = "AVG"
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(
            evidence,
            drafts=[
                {
                    "name": raw["metric"]["name"],
                    "definition": raw,
                    "knowledge_id": family,
                    "variant_id": "order_average_pre_tax",
                    "criteria": criteria,
                }
            ],
            allow_repair=False,
        )
    assert result[0]["review"]["status"] == "error"
    review.assert_not_awaited()


async def test_disabled_knowledge_accepts_existing_identity_without_claiming_curated_sources():
    evidence = context()
    draft = {
        "name": "Doanh thu trước thuế",
        "definition": definition(),
        "knowledge_id": "net_sales",
        "variant_id": "merchandise_net_sales",
        "criteria": {"tax_basis": "excludes_tax"},
    }
    with (
        patch("src.services.metric_knowledge.get_settings") as settings,
        patch("src.agents.nodes.metric.validate_node.get_settings") as node_settings,
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()),
    ):
        settings.return_value.metric_knowledge_enabled = False
        node_settings.return_value.metric_knowledge_enabled = False
        evidence["knowledge"] = metric_knowledge("doanh thu")
        result = await run_metric_workflow(evidence, drafts=[draft], allow_repair=False)
    assert evidence["knowledge"] == {"metrics": [], "sources": []}
    assert result[0]["review"]["status"] == "pass", result[0]["review"]
    assert result[0]["review"]["sources"] == []
    assert result[0]["context"]["candidate"]["knowledge_id"] is None
    assert result[0]["review"]["criteria"]["tax_basis"] == "excludes_tax"


def test_cancellation_word_order_retrieves_the_cancellation_recipe():
    knowledge = metric_knowledge("Định nghĩa chỉ số tỷ lệ đơn hàng bị hủy so với tổng đơn")
    assert "cancellation" in {item["id"] for item in knowledge["metrics"]}


def test_disabled_knowledge_does_not_read_the_bundle():
    with (
        patch("src.services.metric_knowledge.get_settings") as settings,
        patch("src.services.metric_knowledge.load_metric_knowledge") as load,
    ):
        settings.return_value.metric_knowledge_enabled = False
        assert metric_knowledge("AOV", discovery=True) == {"metrics": [], "sources": []}
    load.assert_not_called()


def test_provider_schema_is_typed_while_raw_invalid_siblings_survive_batch_parsing():
    schema = MetricBuildBatch.model_json_schema()
    assert "definition" in schema["properties"]["candidates"]["items"]["properties"]
    assert "ratio" in schema["$defs"]["AgentFormula"]["properties"]
    assert "grain" not in schema["$defs"]["AgentMetricSpec"]["properties"]
    assert "expression_ast" not in schema["$defs"]["AgentFormula"]["properties"]
    bad = {"name": "Broken", "status": "ready", "definition": None}
    batch = MetricBuildBatch.model_validate({"task_id": "test", "candidates": [bad, {"definition": definition()}]})
    assert batch.candidates[0] == bad
    assert batch.candidates[1]["definition"]["metric"]["formula"]["function"] == "SUM"


def test_reviewer_provider_schema_requires_evidence_but_validates_items_individually():
    schema = MetricReviewBatch.model_json_schema()
    assert {"evidence", "action"} <= set(schema["$defs"]["ReviewIssue"]["required"])
    bad = {"candidate_id": "bad", "status": "needs_revision", "issues": [{"code": "missing"}]}
    good = {"candidate_id": "good", "status": "pass", "summary": "Đúng yêu cầu"}
    batch = MetricReviewBatch.model_validate({"task_id": "test", "decisions": [bad, good]})
    assert batch.decisions == [bad, good]


async def test_disabled_knowledge_does_not_disable_the_ratio_gate():
    evidence = context()
    raw = definition("id", "Tỷ lệ đơn hàng bị hủy")
    raw["metric"]["formula"]["function"] = "COUNT_DISTINCT"
    with patch.object(get_settings(), "metric_knowledge_enabled", False):
        result = await run_metric_workflow(
            evidence,
            drafts=[
                {
                    "name": raw["metric"]["name"],
                    "definition": raw,
                    "knowledge_id": "cancellation",
                    "variant_id": "enterprise_cancellation_rate",
                }
            ],
            allow_repair=False,
        )
    assert result[0]["review"]["status"] == "needs_revision"
    assert result[0]["review"]["issues"][0]["code"] == "MISSING_RATIO"


async def test_blocked_family_without_a_selected_variant_is_a_business_decision():
    evidence = context()
    evidence["knowledge"] = metric_knowledge("AOV")
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(
            evidence,
            drafts=[
                {
                    "name": "AOV",
                    "status": "needs_clarification",
                    "definition": None,
                    "knowledge_id": "aov",
                    "variant_id": None,
                    "reason": "Cần xác nhận biến thể thuế áp dụng.",
                }
            ],
            allow_repair=False,
        )
    assert result[0]["review"]["status"] == "needs_clarification"
    assert result[0]["review"]["execution_error"] is None
    assert result[0]["review"]["variant_id"] is None and result[0]["review"]["sources"] == []
    review.assert_not_awaited()


async def test_unknown_variant_feedback_lists_exact_registry_ids_even_for_a_blocked_candidate():
    evidence = context()
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(
            evidence,
            drafts=[
                {
                    "name": "Doanh số thuần",
                    "status": "unsupported",
                    "definition": None,
                    "knowledge_id": "net_sales",
                    "variant_id": "woocommerce_net_sales",
                    "reason": "Chưa chọn được biến thể.",
                }
            ],
            allow_repair=False,
        )
    error = result[0]["review"]["execution_error"]
    assert error["code"] == "INVALID_AGENT_OUTPUT"
    assert "merchandise_net_sales" in error["validation_errors"][0]["message"]
    assert "thiếu definition" not in error["validation_errors"][0]["message"]
    review.assert_not_awaited()


@pytest.mark.parametrize("column_name", ["order_amount_before_tax", "net_sales_amount"])
async def test_after_tax_average_cannot_use_a_direct_before_tax_column(column_name):
    evidence = context()
    evidence["question"] = "Khám phá các biến thể AOV"
    evidence["knowledge"] = metric_knowledge("AOV")
    evidence["schema"]["tables"][0]["columns"][1].update(
        column_name=column_name, description="Giá trị đơn hàng trước thuế, không NULL."
    )
    raw = definition(name="Giá trị đơn hàng trung bình sau thuế")
    raw["metric"]["formula"] = {"function": "AVG", "expression": column_name}
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(
            evidence,
            drafts=[
                {
                    "name": raw["metric"]["name"],
                    "definition": raw,
                    "knowledge_id": "aov",
                    "variant_id": "order_average_after_tax",
                }
            ],
            allow_repair=False,
        )
    assert result[0]["review"]["status"] == "needs_revision"
    assert "cột giá trước thuế" in result[0]["review"]["summary"]
    review.assert_not_awaited()
