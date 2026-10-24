"""Real coordinator/validator tests with explicit, correlated model stand-ins."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.models.metric_review import MetricBuildBatch, ReviewIssue
from src.services.metric_correlation import correlate
from src.services.metric_knowledge import metric_knowledge
from src.agents.roles.metric_designer_agent import generate_metric_drafts
from src.services.metric_runtime import MetricCallError, execution_failure
from src.agents.workflows.metric_proposal_workflow import run_metric_workflow
from tests.metric_review_helpers import context, definition, reviewer_mock


def draft(expression="amount", name="Doanh thu trước thuế"):
    return {"name": name, "status": "ready", "definition": definition(expression, name)}


def repair_mock(raw):
    async def repair(_context, items, _task_id):
        return [{**raw, "candidate_id": item["candidate_id"]} for item in items]

    return AsyncMock(side_effect=repair)


async def test_ready_batch_uses_one_builder_and_one_reviewer_call():
    build = AsyncMock(return_value=[draft(), draft("amount * 2", "Doanh thu gấp đôi")])
    review = reviewer_mock()
    with (
        patch("src.agents.workflows.metric_proposal_workflow.generate_metric_drafts", build),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", review),
    ):
        result = await run_metric_workflow(context())
    assert build.await_count == review.await_count == 1
    assert all(item["review"]["status"] == "pass" for item in result)
    assert all(item["final_definition"]["metric"]["status"] == "pending_approval" for item in result)
    assert review.call_args.args[0]["requirement"] == context()["requirement"]
    assert review.call_args.args[2][0]["definition"]["metric"]["filters"][-1]["value"] is False
    assert "handoffs" not in review.call_args.args[0]


async def test_missing_definition_repairs_once_without_business_review_of_prose():
    repair, review = repair_mock(draft()), reviewer_mock()
    with (
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", repair),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", review),
    ):
        result = await run_metric_workflow(context(), drafts=[{"name": "Doanh thu", "reason": "SUM(amount)"}])
    assert repair.await_count == review.await_count == 1
    assert result[0]["review"]["repair_count"] == 1 and result[0]["review"]["status"] == "pass"
    assert repair.call_args.args[1][0]["feedback"]["execution_error"]["code"] == "INVALID_AGENT_OUTPUT"


async def test_repeated_null_definition_is_execution_error_not_business_revision():
    repair, review = repair_mock({"name": "Doanh thu", "status": "ready", "definition": None}), reviewer_mock()
    with (
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", repair),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", review),
    ):
        result = await run_metric_workflow(context(), drafts=[{"name": "Doanh thu", "definition": None}])
    assert repair.await_count == 1
    review.assert_not_awaited()
    assert result[0]["review"]["execution_error"]["code"] == "INVALID_AGENT_OUTPUT"
    assert result[0]["final_definition"] is None


async def test_schema_correction_does_not_waste_a_reviewer_call():
    repair, review = repair_mock(draft()), reviewer_mock()
    with (
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", repair),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", review),
    ):
        result = await run_metric_workflow(context(), drafts=[draft("missing")])
    assert review.await_count == repair.await_count == 1
    assert result[0]["review"]["original_definition"]["metric"]["formula"]["expression"] == "missing"
    assert result[0]["review"]["repair_feedback"][0]["code"] == "INVALID_DEFINITION"


async def test_partial_batch_preserves_passed_sibling_without_regeneration():
    repair = repair_mock({"name": "Invalid", "definition": None})
    review = reviewer_mock()
    with (
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", repair),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", review),
    ):
        result = await run_metric_workflow(context(), drafts=[draft(), {"name": "Invalid", "definition": None}])
    assert result[0]["review"]["status"] == "pass" and result[1]["review"]["status"] == "error"
    assert len(repair.call_args.args[1]) == 1 and review.await_count == 1


async def test_malformed_reviewer_only_retries_reviewer_not_builder():
    review = AsyncMock(side_effect=[[], [{"candidate_id": "incorrect", "status": "pass", "summary": "wrong ID"}]])
    repair = AsyncMock()
    with (
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", review),
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", repair),
    ):
        result = await run_metric_workflow(context(), drafts=[draft()])
    assert review.await_count == 2
    repair.assert_not_awaited()
    assert result[0]["review"]["execution_error"]["stage"] == "reviewer"


async def test_provider_rate_limit_is_not_semantic_repair_and_keeps_prior_success():
    async def review(_context, _task_id, items):
        return [
            {
                "candidate_id": i["candidate_id"],
                "status": "needs_revision" if index else "pass",
                "summary": "Adjust filter",
                "issues": [
                    ReviewIssue(
                        code="FILTER", message="Wrong filter", evidence="Requirement", action="Use completed"
                    ).model_dump()
                ]
                if index
                else [],
            }
            for index, i in enumerate(items)
        ]

    with (
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", AsyncMock(side_effect=review)),
        patch(
            "src.agents.nodes.metric.repair_node.repair_metric_drafts",
            AsyncMock(side_effect=MetricCallError(execution_failure("RATE_LIMITED", "repair", True, 60))),
        ),
    ):
        result = await run_metric_workflow(context(), drafts=[draft(), draft("amount * 2", "Second")])
    assert result[0]["review"]["status"] == "pass"
    assert result[1]["review"]["execution_error"]["code"] == "RATE_LIMITED"


async def test_builder_provider_failure_keeps_task_diagnostic():
    with patch(
        "src.agents.workflows.metric_proposal_workflow.generate_metric_drafts",
        AsyncMock(side_effect=MetricCallError(execution_failure("RATE_LIMITED", "builder", True, 2))),
    ):
        result = await run_metric_workflow(context())
    report = result[0]["review"]
    assert report["execution_error"]["code"] == "RATE_LIMITED"
    assert result[0]["context"]["task_id"]
    assert report["handoffs"] == []


@pytest.mark.parametrize("status", ["needs_clarification", "rejected", "unsupported"])
async def test_feasibility_decisions_never_trigger_repair(status):
    with patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", new_callable=AsyncMock) as repair:
        result = await run_metric_workflow(
            context(), drafts=[{"name": "KPI", "status": status, "reason": "Need business evidence"}]
        )
    assert result[0]["review"]["status"] == status
    repair.assert_not_awaited()


@pytest.mark.parametrize("name,knowledge", [("AOV", "aov"), ("Biên lợi nhuận", "gross_margin")])
async def test_compound_metrics_remain_unsupported(name, knowledge):
    evidence = context()
    evidence["knowledge"] = metric_knowledge(name)
    variant_id = (
        "shopify_order_value" if knowledge == "aov" else evidence["knowledge"]["metrics"][0]["variants"][0]["id"]
    )
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", new_callable=AsyncMock) as review:
        result = await run_metric_workflow(
            evidence, drafts=[{**draft(name=name), "knowledge_id": knowledge, "variant_id": variant_id}]
        )
    assert result[0]["review"]["status"] == "unsupported"
    review.assert_not_awaited()


async def test_unconfirmed_assumptions_cannot_pass_and_sources_are_server_owned():
    evidence = context()
    evidence["assumptions"] = ["Refund population unclear"]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(
            evidence, drafts=[{**draft(), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales"}]
        )
    assert result[0]["review"]["status"] == "needs_clarification"
    assert {s["id"] for s in result[0]["review"]["sources"]} == {"woocommerce_analytics"}


async def test_generic_request_keeps_two_named_tax_variants_as_separate_proposals():
    evidence = context()
    evidence["question"] = evidence["requirement"] = "Đề xuất doanh thu"
    evidence["schema"]["tables"][0]["columns"].append({"column_name": "vat", "data_type": "NUMERIC"})
    variants = [
        {
            **draft("amount", "Doanh thu trước thuế"),
            "knowledge_id": "net_sales",
            "variant_id": "merchandise_net_sales",
            "criteria": {"order_status": "all_statuses"},
        },
        {
            **draft("amount + vat", "Doanh thu gồm VAT"),
            "knowledge_id": "net_sales",
            "variant_id": "merchandise_net_including_vat",
        },
    ]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=variants)
    assert [item["review"]["status"] for item in result] == ["pass", "pass"]
    assert len({item["context"]["candidate"]["id"] for item in result}) == 2
    assert {item["review"]["variant_id"] for item in result} == {
        "merchandise_net_sales",
        "merchandise_net_including_vat",
    }
    assert result[0]["review"]["criteria"]["order_status"] == "all_statuses"


async def test_average_order_variants_use_valid_order_grain_averages():
    evidence = context()
    evidence["question"] = evidence["requirement"] = "Đề xuất giá trị trung bình mỗi đơn hàng"
    evidence["knowledge"] = metric_knowledge("doanh thu trung bình")
    order = evidence["schema"]["tables"][0]
    order["columns"].extend(
        [
            {"column_name": "price_before_tax", "data_type": "NUMERIC", "is_nullable": False},
            {"column_name": "price_after_tax", "data_type": "NUMERIC", "is_nullable": False},
            {"column_name": "total_discount_value", "data_type": "NUMERIC", "is_nullable": False},
        ]
    )
    variants = [
        {
            **draft("price_before_tax", "Giá trị đơn hàng trung bình trước thuế"),
            "knowledge_id": "aov",
            "variant_id": "order_average_pre_tax",
        },
        {
            **draft("price_after_tax", "Giá trị đơn hàng trung bình sau thuế"),
            "knowledge_id": "aov",
            "variant_id": "order_average_after_tax",
        },
        {
            **draft("price_after_tax - total_discount_value", "Giá trị đơn hàng trung bình sau thuế và giảm giá"),
            "knowledge_id": "aov",
            "variant_id": "order_average_after_tax_discount",
        },
    ]
    for item in variants:
        item["definition"]["metric"]["formula"]["function"] = "AVG"
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(evidence, drafts=variants, allow_repair=False)
    assert [item["review"]["status"] for item in result] == ["pass", "pass", "pass"]
    assert review.await_count == 1


@pytest.mark.parametrize("table_name,nullable", [("order_line", False), ("orders", True)])
async def test_order_average_rejects_line_grain_or_nullable_amount(table_name, nullable):
    evidence = context()
    table = evidence["schema"]["tables"][0]
    table["table_name"] = table_name
    table["columns"][1]["is_nullable"] = nullable
    raw = draft("amount", "Giá trị đơn hàng trung bình")
    raw["definition"]["metric"]["base_entity"] = table_name
    raw["definition"]["metric"]["formula"]["function"] = "AVG"
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(evidence, drafts=[raw], allow_repair=False)
    assert result[0]["review"]["status"] == "unsupported"
    review.assert_not_awaited()


async def test_requested_before_tax_blocks_vat_variant_even_if_reviewer_would_pass():
    evidence = context()
    evidence["schema"]["tables"][0]["columns"].append({"column_name": "vat", "data_type": "NUMERIC"})
    raw = {
        **draft("amount + vat", "Doanh thu gồm VAT"),
        "knowledge_id": "net_sales",
        "variant_id": "merchandise_net_including_vat",
    }
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(evidence, drafts=[raw], allow_repair=False)
    assert result[0]["review"]["status"] == "needs_revision"
    assert result[0]["final_definition"] is None
    review.assert_not_awaited()


async def test_unknown_variant_cannot_claim_curated_sources():
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        result = await run_metric_workflow(
            context(), drafts=[{**draft(), "knowledge_id": "net_sales", "variant_id": "invented"}], allow_repair=False
        )
    assert result[0]["review"]["execution_error"]["code"] == "INVALID_AGENT_OUTPUT"
    assert result[0]["review"]["sources"] == []
    review.assert_not_awaited()


def test_duplicate_and_unknown_responses_are_not_applied_twice():
    assert correlate([{"candidate_id": "a"}, {"candidate_id": "a"}, {"candidate_id": "other"}], {"a", "b"}) == {
        "a": None,
        "b": None,
    }


async def test_builder_receives_full_contract_example_and_preserves_untrusted_item():
    captured = []

    async def response(_contract, messages, stage):
        captured.extend(messages)
        payload = json.loads(messages[-1][1])
        return MetricBuildBatch(task_id=payload["task_id"], candidates=[draft("missing")])

    with patch("src.agents.roles.metric_designer_agent.invoke_metric_json", AsyncMock(side_effect=response)):
        drafts = await generate_metric_drafts(context())
    assert drafts[0]["definition"]["metric"]["formula"]["expression"] == "missing"
    assert '"definition":null' not in captured[0][1]
    assert '"function":"COUNT_DISTINCT"' in captured[0][1]
    assert '"metrics":' not in captured[0][1]


async def test_preset_review_without_repair_never_changes_human_definition():
    with patch(
        "src.agents.workflows.metric_proposal_workflow.review_metric_batch",
        reviewer_mock(
            "needs_revision", issues=[{"code": "FILTER", "message": "Wrong", "evidence": "Question", "action": "Fix"}]
        ),
    ):
        result = await run_metric_workflow(context(), drafts=[draft()], allow_repair=False)
    assert result[0]["review"]["repair_count"] == 0 and result[0]["final_definition"] is None
