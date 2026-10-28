"""Real coordinator/validator tests with explicit, correlated model stand-ins."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.agents.nodes.metric.metric_review_node import reviewed_state
from src.agents.roles.metric_designer_agent import generate_metric_drafts
from src.agents.workflows.metric_proposal_workflow import run_metric_workflow
from src.models.metric_review import MetricBuildBatch, ReviewIssue
from src.services.chat_execution import ChatExecution, execution_context
from src.services.metric_correlation import correlate
from src.services.metric_knowledge import metric_knowledge
from src.services.metric_review_validation import technical_review
from src.services.metric_runtime import MetricCallError, execution_failure
from tests.metric_review_helpers import context, definition, reviewer_mock


def draft(expression="amount", name="Doanh thu trước thuế"):
    return {"name": name, "status": "ready", "definition": definition(expression, name)}


async def test_cancellation_ratio_reaches_reviewer_without_repair():
    evidence = context()
    evidence["question"] = "Định nghĩa chỉ số tỷ lệ đơn hàng bị hủy so với tổng đơn"
    raw = draft("id", "Tỷ lệ đơn hàng bị hủy")
    raw["definition"]["metric"]["formula"] = {
        "function": "COUNT_DISTINCT", "expression": "id",
        "ratio": {
            "numerator": {"function": "COUNT_DISTINCT", "expression": "id", "filters": [
                {"field": "status", "operator": "eq", "value": "cancelled"}
            ]},
            "denominator": {"function": "COUNT_DISTINCT", "expression": "id"},
        },
    }
    with (
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review,
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", new_callable=AsyncMock) as repair,
    ):
        result = await run_metric_workflow(evidence, drafts=[raw])
    assert result[0]["review"]["status"] == "pass"
    assert result[0]["final_definition"]["metric"]["formula"]["ratio"]["denominator"]["expression"] == "id"
    review.assert_awaited_once()
    repair.assert_not_awaited()


async def test_designer_prompt_supports_aov_ratio_and_keeps_avg_conditional():
    batch = MetricBuildBatch(task_id="aov-task", candidates=[draft()])
    with patch("src.agents.roles.metric_designer_agent.invoke_metric_json", AsyncMock(return_value=batch)) as invoke:
        await generate_metric_drafts(context(), "aov-task")
    prompt = invoke.call_args.args[1][0][1]
    assert "AOV dạng tỷ số dùng formula.ratio" in prompt
    assert "COUNT_DISTINCT" in prompt
    assert "AVG chỉ dùng" in prompt
    assert "shopify_order_value" in prompt and "woocommerce_order_value" in prompt
    assert "chỉ dùng AVG" not in prompt


def repair_mock(raw):
    async def repair(_context, items, _task_id):
        return [{**raw, "candidate_id": item["candidate_id"]} for item in items]

    return AsyncMock(side_effect=repair)


@pytest.mark.parametrize("ratio", [False, True])
async def test_coordinator_checks_duplicates_before_review_and_preserves_ratio(ratio):
    evidence = context()
    table = evidence["schema"]["tables"][0]
    table["id"] = 18
    for i, column in enumerate(table["columns"], 136):
        column["id"] = i
    saved, _ = technical_review(legacy_agent_output(False), evidence)
    evidence["existing_metrics"] = [{
        "id": 4, "name": "Tổng đơn hàng", "status": "approved", "definition": saved.model_dump(mode="json"),
    }]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        proposals = await run_metric_workflow(evidence, drafts=[legacy_agent_output(ratio)], allow_repair=False)
    request = review.call_args.args[2][0]
    assert bool(request["duplicate_match"]) is not ratio
    formula = request["definition"]["metric"]["formula"]
    assert formula["expression_ast"]["column_id"] == 136
    if ratio:
        assert formula["ratio"]["numerator"]["filters"][0]["column_id"] == 138
    result = reviewed_state(proposals, {"can_generate_metrics": True})
    assert len(result["suggested_metrics"]) == int(ratio)
    assert len(result["duplicate_notices"]) == int(not ratio)


async def test_duplicate_evidence_does_not_override_reviewer_clarification():
    evidence = context()
    saved, _ = technical_review(definition(), evidence)
    evidence["existing_metrics"] = [{
        "id": 4, "name": "Revenue", "status": "approved", "definition": saved.model_dump(mode="json"),
    }]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock("needs_clarification")):
        proposals = await run_metric_workflow(evidence, drafts=[draft()], allow_repair=False)
    result = reviewed_state(proposals, {})
    assert result["duplicate_notices"] == []
    assert result["suggested_metrics"] == []
    assert result["blocked_candidates"][0]["review"]["status"] == "needs_clarification"


async def test_clarification_options_only_offer_reviewed_sibling_variants():
    evidence = context()
    evidence["question"] = evidence["requirement"] = "Doanh thu trước thuế hay gồm VAT"
    evidence["schema"]["tables"][0]["columns"].append({"column_name": "vat", "data_type": "NUMERIC"})
    evidence["knowledge"] = metric_knowledge("KPI discovery", discovery=True)
    drafts = [
        {**draft("amount", "Doanh thu trước thuế"), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales"},
        {**draft("amount + vat", "Doanh thu gồm VAT"), "knowledge_id": "net_sales", "variant_id": "merchandise_net_including_vat"},
    ]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        proposals = await run_metric_workflow(evidence, drafts=drafts, allow_repair=False)
    proposals[0]["review"].update(status="needs_clarification", clarification="Confirm tax basis")
    result = reviewed_state(proposals, {})
    assert len(result["suggested_metrics"]) == 1
    option = next(
        item for item in result["clarification"]["options"]
        if item["action_payload"]["variant_id"] == "merchandise_net_including_vat"
    )
    assert option["action"] == "generate_metric_variant"
    assert option["action_payload"]["requirement"] == evidence["requirement"]
    assert option["action_payload"]["knowledge_id"] == "net_sales"
    assert option["action_payload"]["variant_id"] == "merchandise_net_including_vat"


async def test_trace_orders_validation_dedupe_review_and_coordinator_conclusion():
    execution = ChatExecution()
    with execution_context(execution), patch(
        "src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()
    ):
        await run_metric_workflow(context(), drafts=[draft()], allow_repair=False)
    starts = [e["node"] for e in execution.snapshot()["events"] if e["kind"] == "step" and e["status"] == "started"]
    assert starts.index("metric_validate") < starts.index("dedupe") < starts.index("metric_review") < starts.index("metric_conclude")


def legacy_agent_output(ratio):
    raw = definition("id", "Tỷ lệ đơn hàng bị hủy" if ratio else "Tổng đơn hàng")
    raw["metric"]["formula"]["function"] = "COUNT_DISTINCT"
    if ratio:
        raw["metric"]["ratio"] = {
            "numerator": {"function": "COUNT_DISTINCT", "expression": "id", "filters": [
                {"field": "status", "operator": "eq", "value": "cancelled"}
            ]},
            "denominator": {"function": "COUNT_DISTINCT", "expression": "id", "filters": []},
            "scale": 1, "offset": 0,
        }
    raw["metric"].pop("excluded_notes")
    raw["excluded_notes"] = "Đếm khóa đơn hàng, cùng phạm vi dữ liệu."
    return raw


@pytest.mark.parametrize("ratio", [False, True])
@pytest.mark.parametrize("repair_output", [False, True])
async def test_legacy_agent_envelope_preserves_definition_in_build_and_repair(ratio, repair_output):
    raw = legacy_agent_output(ratio)
    original = json.dumps(raw, ensure_ascii=False)
    repair = repair_mock(raw)
    with (
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review,
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", repair),
    ):
        drafts = [{"name": raw["metric"]["name"], "definition": None}] if repair_output else [raw]
        result = await run_metric_workflow(context(), drafts=drafts)
    assert result[0]["review"]["status"] == "pass", result[0]["review"]
    final = result[0]["final_definition"]["metric"]
    assert final["name"] == raw["metric"]["name"]
    assert final["excluded_notes"] == raw["excluded_notes"]
    if ratio:
        assert final["formula"]["ratio"]["numerator"]["filters"][0]["value"] == "cancelled"
        assert final["formula"]["ratio"]["denominator"]["expression"] == "id"
        assert final["formula"]["ratio"]["scale"] == 1
    assert json.dumps(raw, ensure_ascii=False) == original
    assert repair.await_count == int(repair_output)
    review.assert_awaited_once()


@pytest.mark.parametrize("kind", ["count", "ratio", "revenue"])
async def test_full_agent_graph_accepts_definition_envelope_from_provider(kind):
    stages = []
    evidence = context()
    evidence["schema"]["tables"][0]["table_name"] = "order_header"
    status = evidence["schema"]["tables"][0]["columns"][2]
    status.update(column_name="latest_status", allowed_values=["Completed", "Canceled"])

    async def response(contract, messages, stage):
        stages.append(stage)
        payload = json.loads(messages[-1][1])
        if stage == "builder":
            raw = legacy_agent_output(kind == "ratio")
            raw["metric"]["base_entity"] = "order_header"
            if kind == "ratio":
                raw["metric"]["ratio"]["numerator"]["filters"][0].update(field="latest_status", value="Canceled")
            if kind == "revenue":
                raw["metric"].update(name="Doanh thu")
                raw["metric"]["formula"] = {"function": "SUM", "expression": "amount"}
            return contract(task_id=payload["task_id"], candidates=[raw])
        assert stage == "reviewer"
        decisions = [{"candidate_id": item["candidate_id"], "status": "pass", "summary": "Đúng yêu cầu"}
                     for item in payload["items"]]
        return contract(task_id=payload["task_id"], decisions=decisions)

    provider = AsyncMock(side_effect=response)
    with (
        patch("src.agents.roles.metric_designer_agent.invoke_metric_json", provider),
        patch("src.agents.roles.metric_reviewer_agent.invoke_metric_json", provider),
    ):
        result = await run_metric_workflow(evidence)
    assert stages == ["builder", "reviewer"]
    assert result[0]["review"]["status"] == "pass"
    assert result[0]["final_definition"]["metric"]["status"] == "pending_approval"


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
    assert result[0]["review"]["execution_error"]["stage"] == "repair"
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


@pytest.mark.parametrize("failure,field,error_type", [
    ({"status": "pass", "summary": "Đạt", "extra": "private-provider-text"}, "extra", "extra_forbidden"),
    ({"status": "pass"}, "summary", "missing"),
    ({"status": "needs_revision", "summary": "Sửa"}, "issues", "revision_without_issues"),
    ({"status": "pass", "summary": "Đạt", "clarification": "Cần hỏi lại"}, "clarification", "contradictory_pass"),
    ({"status": "needs_revision", "summary": "Sửa", "issues": [
        {"code": "FILTER", "message": "Sai", "evidence": "Schema"}
    ]}, "issues.0.action", "missing"),
])
async def test_reviewer_field_errors_are_persisted_and_traced(failure, field, error_type):
    execution = ChatExecution()
    async def review(_context, _task, items):
        return [{"candidate_id": items[0]["candidate_id"], **failure}]
    with execution_context(execution), patch(
        "src.agents.workflows.metric_proposal_workflow.review_metric_batch", side_effect=review
    ):
        result = await run_metric_workflow(context(), drafts=[draft()], allow_repair=False)
    error = result[0]["review"]["execution_error"]
    assert error["validation_errors"][0]["field"] == field
    assert error["validation_errors"][0]["type"] == error_type
    assert error["candidate_id"] == result[0]["context"]["candidate"]["id"]
    assert error["attempt"] == 0
    diagnostics = [event for event in execution.snapshot()["events"] if event.get("validation_errors")]
    assert diagnostics[0]["validation_errors"] == error["validation_errors"]
    assert "private-provider-text" not in json.dumps(error)
    assert "private-provider-text" not in json.dumps(execution.snapshot())


@pytest.mark.parametrize("duplicate", [False, True])
async def test_review_correlation_errors_identify_the_candidate(duplicate):
    async def review(_context, _task, items):
        record = {"candidate_id": items[0]["candidate_id"] if duplicate else "wrong-id", "status": "pass", "summary": "Đạt"}
        return [record, record] if duplicate else [record]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", side_effect=review):
        result = await run_metric_workflow(context(), drafts=[draft()], allow_repair=False)
    error = result[0]["review"]["execution_error"]
    assert error["validation_errors"][0]["field"] == "candidate_id"
    assert error["validation_errors"][0]["type"] == ("duplicate_candidate_id" if duplicate else "missing_candidate_id")


async def test_recovered_review_retains_first_attempt_diagnostics_in_trace():
    execution = ChatExecution()
    attempts = []
    async def review(_context, _task, items):
        attempts.append(1)
        record = {"candidate_id": items[0]["candidate_id"], "status": "pass"}
        if len(attempts) == 2:
            record["summary"] = "Đạt"
        return [record]
    with execution_context(execution), patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", side_effect=review):
        result = await run_metric_workflow(context(), drafts=[draft()])
    assert result[0]["review"]["status"] == "pass"
    error = next(e for e in execution.snapshot()["events"] if e.get("validation_errors"))
    assert error["validation_errors"][0]["field"] == "summary"
    assert error["attempt"] == 0


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
async def test_compound_metrics_without_explicit_ratio_need_revision(name, knowledge):
    evidence = context()
    evidence["knowledge"] = metric_knowledge(name)
    variant_id = (
        "shopify_order_value" if knowledge == "aov" else evidence["knowledge"]["metrics"][0]["variants"][0]["id"]
    )
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", new_callable=AsyncMock) as review:
        result = await run_metric_workflow(
            evidence, drafts=[{**draft(name=name), "knowledge_id": knowledge, "variant_id": variant_id}], allow_repair=False
        )
    assert result[0]["review"]["status"] == "needs_revision"
    assert result[0]["review"]["issues"][0]["code"] == "MISSING_RATIO"
    review.assert_not_awaited()


async def test_assumptions_not_covered_by_variant_criteria_cannot_pass_and_sources_are_server_owned():
    evidence = context()
    evidence["assumptions"] = ["Customer cohort is unclear"]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(
            evidence, drafts=[{**draft(), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales"}]
        )
    assert result[0]["review"]["status"] == "needs_clarification"
    assert {s["id"] for s in result[0]["review"]["sources"]} == {"woocommerce_analytics"}


@pytest.mark.parametrize(
    "assumptions,expected_status,remaining",
    [
        (["Tax basis is unclear"], "pass", ""),
        (["Customer cohort is unclear"], "needs_clarification", "Customer cohort is unclear"),
        (["Tax basis is unclear", "Customer cohort is unclear"], "needs_clarification", "Customer cohort is unclear"),
    ],
)
async def test_variant_criteria_resolve_only_the_assumptions_they_cover(assumptions, expected_status, remaining):
    evidence = context()
    evidence["assumptions"] = assumptions
    draft_item = {
        **draft(), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales",
        "criteria": {"tax_basis": "excludes_tax", "refund_policy": "subtract_returns_and_coupons"},
    }
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=[draft_item], allow_repair=False)
    assert result[0]["review"]["status"] == expected_status
    if remaining:
        assert result[0]["review"]["clarification"] == remaining


@pytest.mark.parametrize(
    "requirement,assumptions",
    [
        ("Revenue after tax", ["Tax basis is unclear"]),
        ("Revenue before tax", ["After tax is required"]),
    ],
)
async def test_tax_criterion_must_match_requested_and_assumed_polarity(requirement, assumptions):
    evidence = context()
    evidence["requirement"] = requirement
    evidence["question"] = requirement
    evidence["assumptions"] = assumptions
    candidate = {
        **draft(), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales",
        "criteria": {"tax_basis": "excludes_tax", "refund_policy": "subtract_returns_and_coupons"},
    }
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=[candidate], allow_repair=False)
    assert result[0]["review"]["status"] == "needs_clarification"


async def test_ambiguous_tax_request_allows_each_validated_basis_as_a_separate_variant():
    evidence = context()
    evidence["requirement"] = "Doanh thu trước thuế hay gồm VAT"
    evidence["question"] = "Doanh thu trước thuế hay gồm VAT"
    evidence["schema"]["tables"][0]["columns"].append({"column_name": "vat", "data_type": "NUMERIC"})
    candidates = [
        {**draft("amount", "Doanh thu trước thuế"), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales"},
        {**draft("amount + vat", "Doanh thu gồm VAT"), "knowledge_id": "net_sales", "variant_id": "merchandise_net_including_vat"},
    ]
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=candidates, allow_repair=False)
    assert [proposal["review"]["status"] for proposal in result] == ["pass", "pass"]


async def test_selected_variant_rerun_is_exact_and_ignores_ambiguous_history():
    evidence = context()
    evidence["requirement"] = "Doanh thu trước thuế? Earlier request: doanh thu gồm VAT? Latest selection: gồm VAT."
    evidence["question"] = "Doanh thu gồm VAT"
    evidence["schema"]["tables"][0]["columns"].append({"column_name": "vat", "data_type": "NUMERIC"})
    evidence["knowledge"] = metric_knowledge("KPI discovery", discovery=True)
    selected = {
        "knowledge_id": "net_sales", "variant_id": "merchandise_net_including_vat",
        "criteria": {"tax_basis": "includes_vat", "refund_policy": "subtract_sales_reversals"},
    }
    evidence["selected_metric_variant"] = selected
    candidate = {**draft("amount + vat", "Doanh thu gồm VAT"), **selected}
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        result = await run_metric_workflow(evidence, drafts=[candidate], allow_repair=False)
    assert result[0]["review"]["status"] == "pass"
    wrong = {**draft("amount", "Doanh thu trước thuế"), "knowledge_id": "net_sales", "variant_id": "merchandise_net_sales"}
    invalid = await run_metric_workflow(evidence, drafts=[wrong], allow_repair=False)
    assert invalid[0]["review"]["execution_error"]["code"] == "INVALID_AGENT_OUTPUT"


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
    assert result[0]["review"]["status"] == "needs_revision"
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
