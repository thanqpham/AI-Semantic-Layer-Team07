"""Business-review batching and deterministic gates for the metric coordinator."""

from __future__ import annotations

import json
from typing import Any

from src.models.metric_definition import MetricDefinition
from src.models.metric_review import KnowledgeSource, MetricDraft, MetricReview, MetricReviewBatch
from src.observability import trace_action
from src.observability.langfuse_tracing import observation
from src.services.metric_knowledge import find_variant, normalized_text
from src.services.metric_proposal_generation import CONTEXT_RULES
from src.services.metric_review_validation import technical_review
from src.services.metric_runtime import MetricCallError, execution_failure, invoke_metric_json

_REVIEW_PROMPT = (
    CONTEXT_RULES
    + """
Bạn là Data Lead Reviewer. Thẩm định riêng từng definition đã qua kiểm tra kỹ thuật.
Đọc câu hỏi gốc, lịch sử xác nhận, schema, nguồn KPI và catalog trong context.
Đối chiếu grain, aggregation, đơn vị, population, thuế, hoàn tiền và điều kiện thời gian.
Không tự sửa definition, không ghi audit hoặc tự phê duyệt. Chỉ trả judgment.
Giữ chính xác task_id và candidate_id được giao, không thêm KPI, không bỏ sót KPI.
pass chỉ khi đầy đủ yêu cầu và không còn vấn đề. needs_revision phải có issues gồm
code, message, evidence cụ thể, action; chỉ dùng khi context đủ để sửa.
Thiếu quyết định nghiệp vụ dùng needs_clarification và clarification là câu hỏi cụ thể.
Nếu yêu cầu chung có nhiều biến thể được schema chứng minh, đánh giá riêng từng biến thể; không yêu cầu chọn một biến thể trước.
Kiểm tra tên và công thức thể hiện đúng criteria và variant_id, không gán nguồn của biến thể khác.
FORMAT DUY NHẤT:
{"task_id":"đúng task_id đã nhận", "decisions":[{"candidate_id":"đúng ID được giao",
"status":"pass", "summary":"Lý do dựa trên yêu cầu và metadata", "issues":[], "clarification":null}]}
Các status khác: needs_revision, needs_clarification, rejected, unsupported.
"""
)


async def review_metric_draft(
    context: dict[str, Any], raw_draft: dict[str, Any], allow_repair: bool = True
) -> dict[str, Any]:
    """Run the same coordinator for human edits and legacy single-metric callers."""
    from src.services.metric_workflow import run_metric_workflow

    result = await run_metric_workflow(context, drafts=[raw_draft], allow_repair=allow_repair)
    return result[0]


async def review_metric_batch(
    context: dict[str, Any], task_id: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Make one model call for all ready definitions, excluding the audit ledger."""
    payload = {"task_id": task_id, "context": context, "items": items}
    batch = await trace_action(
        "metric_review_decision",
        {},
        invoke_metric_json(
            MetricReviewBatch,
            [("system", _REVIEW_PROMPT), ("user", json.dumps(payload, ensure_ascii=False))],
            "reviewer",
        ),
    )
    if batch.task_id != task_id:
        raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", "reviewer"))
    return batch.decisions


def validate_review_draft(
    context: dict[str, Any], draft: dict[str, Any]
) -> tuple[MetricDefinition | None, MetricReview | None]:
    """Apply deterministic technical, ambiguity and compiler-capability gates."""
    definition, technical = technical_review(draft["definition"], context)
    if technical:
        if any("MISSING_GRAIN" in issue.evidence for issue in technical.issues):
            technical.status = "needs_clarification"
            technical.clarification = "Khóa nào xác định duy nhất mỗi dòng của bảng gốc?"
        return definition, technical
    if normalized_text(definition.metric.excluded_notes).startswith("gia dinh can xac nhan:"):
        return None, MetricReview(
            status="needs_clarification",
            summary="Đề xuất còn giả định chưa xác nhận.",
            clarification=definition.metric.excluded_notes,
        )
    carrier = MetricDraft.model_validate({**draft, "status": "candidate"})
    if _requires_ratio(carrier):
        return None, MetricReview(
            status="unsupported", summary="Compiler chưa hỗ trợ ratio giữa các tổng hợp của KPI này."
        )
    return definition, None


def _enforce_review(review: MetricReview, technical: MetricReview | None, context: dict[str, Any]) -> MetricReview:
    if technical and review.status == "pass":
        return technical
    if review.status == "pass" and (review.issues or review.clarification):
        return review.model_copy(update={"status": "needs_clarification"})
    if review.status == "pass" and context.get("assumptions"):
        return MetricReview(
            status="needs_clarification",
            summary="Còn giả định nghiệp vụ chưa xác nhận.",
            clarification="; ".join(context["assumptions"]),
        )
    if review.status == "needs_revision" and not review.issues:
        return review.model_copy(
            update={"status": "rejected", "summary": "Không có bằng chứng và hướng sửa đủ rõ để tự động sửa."}
        )
    return review


def _requires_ratio(draft: MetricDraft) -> bool:
    if draft.knowledge_id in {"aov", "gross_margin", "conversion", "cancellation", "units_per_transaction"}:
        return True
    spec = (draft.definition or {}).get("metric", draft.definition)
    metric_name = str(spec.get("name", "")) if isinstance(spec, dict) else ""
    name = normalized_text(draft.name + " " + metric_name)
    return any(
        marker in name
        for marker in (
            "ty le",
            "ti le",
            "ty trong",
            "aov",
            "bien loi nhuan",
            "gia tri don hang trung binh",
            "units per transaction",
            "conversion rate",
            "cancellation rate",
            "gross margin",
            "percentage",
            "ratio",
        )
    )


def _complete_report(
    review: MetricReview,
    context: dict[str, Any],
    original: Any,
    repaired: bool,
    knowledge_id: str | None,
    variant_id: str | None = None,
    criteria: dict[str, str] | None = None,
) -> MetricReview:
    knowledge = context.get("knowledge", {})
    variant = find_variant(knowledge, knowledge_id, variant_id)
    source_ids = set(variant["source_ids"]) if variant else set()
    return review.model_copy(
        update={
            "requirement": context["requirement"],
            "original_definition": original,
            "revised": repaired,
            "repair_count": int(repaired),
            "repair_reason": None,
            "repair_feedback": [],
            "sources": [
                KnowledgeSource.model_validate(s) for s in knowledge.get("sources", []) if s["id"] in source_ids
            ],
            "variant_id": variant_id if variant else None,
            "criteria": {**(variant["criteria"] if variant else {}), **(criteria or {})},
        }
    )


def _record_review_result(review: MetricReview) -> None:
    with observation("metric_review_result") as span:
        if span is not None:
            span.update(
                status_message=f"{review.status};repair_count={review.repair_count}",
                level="ERROR" if review.status == "error" else "DEFAULT",
            )
