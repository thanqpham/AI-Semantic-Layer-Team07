"""Review every AI draft and allow at most one evidence-grounded repair."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.models.metric_definition import MetricDefinition
from src.models.metric_review import KnowledgeSource, MetricDraft, MetricReview, ReviewIssue
from src.observability import trace_action
from src.observability.langfuse_tracing import observation
from src.services.metric_knowledge import normalized_text
from src.services.metric_proposal_generation import CONTEXT_RULES, invoke_metric_json, repair_metric_draft
from src.services.metric_review_validation import technical_review

logger = logging.getLogger(__name__)

_REVIEW_PROMPT = (
    CONTEXT_RULES
    + """
Bạn là trợ lý Data Lead thẩm định ĐỘC LẬP metric trước HITL. Không viết lại định nghĩa trong bước này.
Đọc câu hỏi, yêu cầu gốc có message ID, lịch sử và schema; không chỉ đọc tên metric.
Đối chiếu grain, aggregation, numerator/denominator, cùng population, NULL, đơn vị, thời gian,
thuế, hoàn tiền, trạng thái hoàn tất, chống đếm trùng và metric đã có trong catalog.
Chỉ pass khi công thức trả lời đầy đủ yêu cầu, không có giả định chưa xác nhận hoặc lỗi kỹ thuật.
MISSING_GRAIN cần needs_clarification. Thiếu dữ liệu cần rejected. Cần ratio aggregate cần unsupported.
Chỉ needs_revision khi bằng chứng hiện có đủ để sửa; không đưa needs_revision cho quyết định nghiệp vụ chưa rõ.
Mọi vấn đề phải có code, message, evidence cụ thể từ context và action cần thực hiện.
Nếu cần hỏi thì điền clarification bằng một câu hỏi cụ thể tiếng Việt.
Trả JSON MetricReview: {"status":"pass|needs_revision|needs_clarification|rejected|unsupported",
"summary":"Nhận xét có căn cứ", "issues":[], "clarification":null}.
"""
)


async def review_metric_draft(
    context: dict[str, Any], raw_draft: dict[str, Any], allow_repair: bool = True
) -> dict[str, Any]:
    """Return an auditable final decision, never a human approval."""
    draft = MetricDraft.model_validate(raw_draft)
    original = draft.definition
    definition, review = await _review_once(context, draft)
    initial_review = review
    repaired = review.status == "needs_revision" and allow_repair
    if repaired:
        try:
            raw = await repair_metric_draft(context, draft.model_dump(mode="json"), review.model_dump(mode="json"))
            draft = MetricDraft.model_validate(raw)
            definition, review = await _review_once(context, draft)
        except Exception as exc:
            review = _error_review(exc)
            definition = None
    review = _complete_report(review, context, original, repaired, draft.knowledge_id)
    if repaired:
        review.repair_reason = initial_review.summary
        review.repair_feedback = initial_review.issues
    _record_review_result(review)
    return {
        "name": draft.name,
        "original_definition": original,
        "final_definition": definition.model_dump(mode="json") if definition and review.status == "pass" else None,
        "context": context,
        "review": review.model_dump(mode="json"),
    }


async def _review_once(context: dict[str, Any], draft: MetricDraft) -> tuple[MetricDefinition | None, MetricReview]:
    try:
        return await _evaluate_draft(context, draft)
    except Exception as exc:
        logger.warning("Metric review failed (%s)", type(exc).__name__)
        return None, _error_review(exc)


async def _evaluate_draft(context: dict[str, Any], draft: MetricDraft) -> tuple[MetricDefinition | None, MetricReview]:
    if draft.status != "candidate" or draft.definition is None:
        status = draft.status if draft.status != "candidate" else "needs_revision"
        return None, MetricReview(
            status=status,
            summary=draft.reason or "Chưa có định nghĩa khả thi.",
            clarification=draft.reason if status == "needs_clarification" else None,
        )
    definition, technical = technical_review(draft.definition, context)
    gate = _definition_gate(definition, technical)
    if gate:
        return None, gate
    if _requires_ratio(draft):
        return None, MetricReview(
            status="unsupported",
            summary="KPI cần tỷ số giữa các tổng hợp mà compiler hiện chưa hỗ trợ.",
            issues=[
                ReviewIssue(
                    code="AGGREGATE_RATIO",
                    message="Không thể biểu diễn KPI này bằng một aggregation.",
                    evidence="Compiler v1 không có primitive ratio giữa các tổng hợp.",
                    action="Giữ KPI trong danh sách chưa hỗ trợ; không lưu công thức gần đúng.",
                )
            ],
        )
    review = await _business_review(context, draft, definition, technical)
    return definition, _enforce_review(review, technical, context)


def _definition_gate(definition: MetricDefinition | None, technical: MetricReview | None) -> MetricReview | None:
    if technical and technical.status == "unsupported":
        return technical
    if technical and any("MISSING_GRAIN" in i.evidence for i in technical.issues):
        return technical.model_copy(
            update={
                "status": "needs_clarification",
                "clarification": "Khóa nào xác định duy nhất mỗi dòng của bảng gốc?",
            }
        )
    if definition and normalized_text(definition.metric.excluded_notes).startswith("gia dinh can xac nhan:"):
        return MetricReview(
            status="needs_clarification",
            summary="Đề xuất còn giả định chưa xác nhận.",
            clarification=definition.metric.excluded_notes,
        )
    return None


async def _business_review(
    context: dict[str, Any], draft: MetricDraft, definition: MetricDefinition | None, technical: MetricReview | None
) -> MetricReview:
    payload = {
        "context": context,
        "candidate": definition.model_dump(mode="json") if definition else draft.definition,
        "technical_findings": technical.model_dump(mode="json") if technical else None,
    }
    return await trace_action(
        "metric_review_decision",
        {},
        invoke_metric_json(
            MetricReview, [("system", _REVIEW_PROMPT), ("user", json.dumps(payload, ensure_ascii=False))]
        ),
    )


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
    review: MetricReview, context: dict[str, Any], original: Any, repaired: bool, knowledge_id: str | None
) -> MetricReview:
    knowledge = context.get("knowledge", {})
    recipes = (
        [m for m in knowledge.get("metrics", []) if m["id"] == knowledge_id]
        if knowledge_id
        else knowledge.get("metrics", [])
    )
    source_ids = {s for m in recipes for v in m["variants"] for s in v["source_ids"]}
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
        }
    )


def _error_review(exc: Exception) -> MetricReview:
    return MetricReview(
        status="error",
        summary="Không thể hoàn tất thẩm định. Hãy thử lại; metric chưa được gửi duyệt.",
        issues=[
            ReviewIssue(
                code=type(exc).__name__,
                message="Thẩm định thất bại.",
                evidence="Dịch vụ thẩm định không trả kết quả hợp lệ.",
                action="Thử lại thẩm định.",
            )
        ],
    )


def _record_review_result(review: MetricReview) -> None:
    with observation("metric_review_result") as span:
        if span is not None:
            span.update(
                status_message=f"{review.status};repair_count={review.repair_count}",
                level="ERROR" if review.status == "error" else "DEFAULT",
            )
