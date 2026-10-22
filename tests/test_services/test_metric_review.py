"""Metadata-only review, bounded repair and context-preservation regressions."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.metric_review import KnowledgeSource, MetricDraftBatch, MetricReview, ReviewIssue
from src.services.metric_knowledge import load_metric_knowledge
from src.services.metric_proposal_generation import invoke_metric_json, prepare_proposal_context
from src.services.metric_review import review_metric_draft
from src.services.metric_review_validation import technical_review
from tests.metric_review_helpers import context, definition, schema


def _draft(raw=None):
    return {"name": "Doanh thu trước thuế", "definition": raw or definition()}


def _pass():
    return MetricReview(status="pass", summary="Đúng yêu cầu doanh thu trước thuế, đơn hoàn tất.")


async def test_review_receives_original_question_and_hygiene():
    invoke = AsyncMock(return_value=_pass())
    with patch("src.services.metric_review.invoke_metric_json", invoke):
        result = await review_metric_draft(context(), _draft())
    assert result["review"]["status"] == "pass"
    assert result["final_definition"]["metric"]["status"] == "pending_approval"
    assert result["final_definition"]["metric"]["filters"][-1]["value"] is False
    prompt = invoke.call_args.args[1][1][1]
    assert "original-message" in prompt and "current-message" in prompt
    assert "trước thuế" in prompt and "hoàn tất" in prompt and "is_test_order" in prompt


async def test_repairs_once_and_preserves_full_business_context():
    feedback = MetricReview(
        status="needs_revision",
        summary="Sai cột",
        issues=[
            ReviewIssue(
                code="COLUMN",
                message="Cột không tồn tại",
                evidence="missing không thuộc orders",
                action="Dùng amount trước thuế",
            )
        ],
    )
    invoke = AsyncMock(side_effect=[feedback, _pass()])
    repair = AsyncMock(return_value=_draft())
    evidence = context()
    with (
        patch("src.services.metric_review.invoke_metric_json", invoke),
        patch("src.services.metric_review.repair_metric_draft", repair),
    ):
        result = await review_metric_draft(evidence, _draft(definition("missing")))
    assert result["review"]["revised"] and result["review"]["repair_count"] == 1
    assert result["review"]["repair_reason"] == "Sai cột"
    assert result["review"]["repair_feedback"][0]["code"] == "COLUMN"
    assert result["review"]["original_definition"]["metric"]["formula"]["expression"] == "missing"
    assert repair.call_args.args[0] is evidence
    assert result["final_definition"]["metric"]["formula"]["expression"] == "amount"
    assert invoke.await_count == 2


async def test_second_invalid_draft_cannot_be_sent_for_hitl():
    invoke = AsyncMock(return_value=_pass())
    repair = AsyncMock(return_value=_draft(definition("missing")))
    with (
        patch("src.services.metric_review.invoke_metric_json", invoke),
        patch("src.services.metric_review.repair_metric_draft", repair),
    ):
        result = await review_metric_draft(context(), _draft(definition("missing")))
    assert result["final_definition"] is None
    assert result["review"]["status"] == "needs_revision"
    assert repair.await_count == 1 and invoke.await_count == 2


@pytest.mark.parametrize("status", ["needs_clarification", "rejected", "unsupported", "error"])
async def test_nonpassing_review_never_repairs_or_publishes(status):
    review = MetricReview(status=status, summary="Cần quyết định nghiệp vụ", clarification="Trước hay sau thuế?")
    with (
        patch("src.services.metric_review.invoke_metric_json", AsyncMock(return_value=review)),
        patch("src.services.metric_review.repair_metric_draft", new_callable=AsyncMock) as repair,
    ):
        result = await review_metric_draft(context(), _draft())
    repair.assert_not_awaited()
    assert result["final_definition"] is None


async def test_provider_error_fails_closed_without_exposing_secret():
    with patch("src.services.metric_review.invoke_metric_json", AsyncMock(side_effect=RuntimeError("secret-key"))):
        result = await review_metric_draft(context(), _draft())
    assert result["review"]["status"] == "error" and result["final_definition"] is None
    assert "secret-key" not in str(result["review"])


async def test_unconfirmed_assumption_overrides_model_pass():
    evidence = context()
    evidence["assumptions"] = ["Cách tính hoàn tiền chưa rõ"]
    with patch("src.services.metric_review.invoke_metric_json", AsyncMock(return_value=_pass())):
        result = await review_metric_draft(evidence, _draft())
    assert result["review"]["status"] == "needs_clarification"


@pytest.mark.parametrize(
    "knowledge_id,name", [("aov", "AOV"), ("cancellation", "Tỷ lệ hủy đơn"), ("gross_margin", "Biên lợi nhuận")]
)
async def test_compound_kpi_is_unsupported_even_if_model_attempts_simple_formula(knowledge_id, name):
    with patch("src.services.metric_review.invoke_metric_json", new_callable=AsyncMock) as invoke:
        result = await review_metric_draft(
            context(), {"name": name, "knowledge_id": knowledge_id, "definition": definition()}
        )
    invoke.assert_not_awaited()
    assert result["review"]["status"] == "unsupported"


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


async def test_model_cannot_invent_citations():
    review = _pass()
    review.sources = [
        KnowledgeSource(id="invented", title="Untrusted", url="https://untrusted.invalid/", reviewed_at="never")
    ]
    evidence = copy.deepcopy(context())
    with patch("src.services.metric_review.invoke_metric_json", AsyncMock(return_value=review)):
        result = await review_metric_draft(evidence, {**_draft(), "knowledge_id": "net_sales"})
    assert {s["id"] for s in result["review"]["sources"]} == {"shopify_sales", "woocommerce_analytics"}


async def test_structured_call_uses_metric_role_and_zero_temperature():
    llm = MagicMock()
    structured = llm.with_structured_output.return_value
    structured.ainvoke = AsyncMock(return_value={"candidates": []})
    with patch("src.services.metric_proposal_generation.get_llm", return_value=llm) as get_llm:
        result = await invoke_metric_json(MetricDraftBatch, [("user", "schema")])
    get_llm.assert_called_once_with(role="metric")
    structured.ainvoke.assert_awaited_once_with([("user", "schema")], temperature=0.0)
    assert isinstance(result, MetricDraftBatch)


async def test_format_fallback_is_bounded_and_does_not_add_business_repairs():
    llm = MagicMock()
    llm.with_structured_output.side_effect = NotImplementedError
    llm.ainvoke = AsyncMock(return_value=SimpleNamespace(content='{"candidates": []}'))
    with patch("src.services.metric_proposal_generation.get_llm", return_value=llm):
        await invoke_metric_json(MetricDraftBatch, [("user", "schema")])
    llm.ainvoke.assert_awaited_once()
    assert llm.ainvoke.call_args.kwargs["temperature"] == 0.0


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


async def test_explicit_unresolved_notes_cannot_be_promoted_by_model_pass():
    raw = definition()
    raw["metric"]["excluded_notes"] = "Giả định cần xác nhận: Cách ghi nhận hoàn tiền"
    with patch("src.services.metric_review.invoke_metric_json", new_callable=AsyncMock) as invoke:
        result = await review_metric_draft(context(), _draft(raw))
    invoke.assert_not_awaited()
    assert result["review"]["status"] == "needs_clarification" and result["final_definition"] is None
