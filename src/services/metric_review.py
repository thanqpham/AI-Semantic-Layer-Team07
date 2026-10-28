"""Business-review batching and deterministic gates for the metric coordinator."""

from __future__ import annotations

from typing import Any

import sqlglot
from sqlglot import exp

from src.models.metric_definition import MetricDefinition
from src.models.metric_review import KnowledgeSource, MetricDraft, MetricReview, ReviewIssue
from src.observability.langfuse_tracing import observation
from src.services.metric_knowledge import find_variant, normalized_text
from src.services.metric_review_validation import schema_tables, technical_review


async def review_metric_draft(
    context: dict[str, Any],
    raw_draft: dict[str, Any],
    allow_repair: bool = True,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """Run the same coordinator for human edits and legacy single-metric callers."""
    from src.agents.workflows.metric_proposal_workflow import run_metric_workflow

    result = await run_metric_workflow(
        context, drafts=[raw_draft], allow_repair=allow_repair, candidate_ids=[candidate_id]
    )
    return result[0]


def validate_review_draft(
    context: dict[str, Any], draft: dict[str, Any]
) -> tuple[MetricDefinition | None, MetricReview | None]:
    """Apply deterministic technical, ambiguity and compiler-capability gates."""
    definition, technical = technical_review(draft["definition"], context)
    if technical:
        if any("MISSING_GRAIN" in issue.evidence for issue in technical.issues):
            technical.status = "needs_clarification"
            technical.clarification = "Khóa nào xác định duy nhất mỗi dòng của bảng gốc?"
            technical.reason_code = "MISSING_GRAIN"
        else:
            technical.reason_code = "TECHNICAL_VALIDATION"
        return definition, technical
    if normalized_text(definition.metric.excluded_notes).startswith("gia dinh can xac nhan:"):
        return None, MetricReview(
            status="needs_clarification",
            summary="Đề xuất còn giả định chưa xác nhận.",
            clarification=definition.metric.excluded_notes,
            reason_code="UNRESOLVED_ASSUMPTION",
        )
    carrier = MetricDraft.model_validate({**draft, "status": "candidate"})
    if definition.metric.query_plan is None and definition.metric.formula.ratio is None and _requires_ratio(carrier, context):
        return None, _missing_ratio_review()
    return definition, None


def _missing_ratio_review() -> MetricReview:
    return MetricReview(
        status="needs_revision",
        summary="KPI này cần tỷ lệ giữa các tổng hợp qua formula.ratio.",
        reason_code="MISSING_RATIO",
        issues=[
            ReviewIssue(
                code="MISSING_RATIO",
                message="Thiếu công thức tỷ lệ tường minh.",
                evidence="KPI tỷ lệ chỉ có một aggregation, chưa có formula.ratio.",
                action="Khai báo formula.ratio với numerator và denominator trên cùng base_entity; không đổi mục tiêu KPI.",
            )
        ],
    )


def _enforce_review(
    review: MetricReview,
    technical: MetricReview | None,
    context: dict[str, Any],
    candidate: dict[str, Any] | None = None,
) -> MetricReview:
    if technical and review.status == "pass":
        return technical
    if review.status == "pass" and (review.issues or review.clarification):
        return review.model_copy(update={"status": "needs_clarification", "reason_code": "REVIEWER_FINDING"})
    unresolved = _unresolved_assumptions(context.get("assumptions", []), candidate or {}, context)
    if review.status == "pass" and unresolved:
        return MetricReview(
            status="needs_clarification",
            summary="Còn giả định nghiệp vụ chưa xác nhận.",
            clarification="; ".join(unresolved),
            reason_code="UNRESOLVED_ASSUMPTION",
        )
    if review.status == "needs_revision" and not review.issues:
        return review.model_copy(
            update={
                "status": "rejected",
                "summary": "Không có bằng chứng và hướng sửa đủ rõ để tự động sửa.",
                "reason_code": "REVIEWER_FINDING",
            }
        )
    return review


def _unresolved_assumptions(assumptions: list[str], candidate: dict[str, Any], context: dict[str, Any]) -> list[str]:
    """Resolve only assumptions named by a validated variant criterion."""
    criteria = candidate.get("criteria", {})
    dimensions = {
        "tax_basis": ("tax", "vat", "thue"),
        "refund_policy": ("refund", "return", "hoan", "tra hang"),
        "order_status": ("status", "trang thai", "completed", "cancelled"),
        "population": ("population", "cohort", "customer group", "tap khach", "doi tuong"),
        "discount_policy": ("discount", "giam gia"),
        "formula_basis": ("formula", "cong thuc"),
    }
    unresolved = []
    variant_direction = _tax_criterion(criteria.get("tax_basis"))
    requirement_direction = _tax_direction(context.get("question", ""))
    if requirement_direction is None:
        requirement_direction = _tax_direction(context.get("requirement", ""))
    selected = context.get("selected_metric_variant") or {}
    selected_candidate = (
        all(candidate.get(key) == selected.get(key) for key in ("knowledge_id", "variant_id", "criteria"))
        if selected
        else False
    )
    if selected_candidate:
        requirement_direction = None
    tax_mismatch = criteria.get("tax_basis") and requirement_direction and variant_direction != requirement_direction
    if tax_mismatch:
        unresolved.append("Biến thể không khớp cơ sở thuế được yêu cầu.")
    for assumption in assumptions:
        text = normalized_text(str(assumption))
        addressed = [key for key, terms in dimensions.items() if any(term in text for term in terms)]
        assumption_direction = _tax_direction(text)
        tax_mismatch = assumption_direction and variant_direction != assumption_direction
        if not addressed or any(not criteria.get(key) for key in addressed) or tax_mismatch:
            unresolved.append(str(assumption))
    return unresolved


def _tax_direction(text: str) -> str | bool | None:
    """Read explicit tax polarity; return False when the text contains both sides."""
    normalized = normalized_text(str(text))
    both = any(term in normalized for term in ("before or after tax", "before/after tax", "truoc hoac sau thue"))
    before = both or any(term in normalized for term in ("truoc thue", "before tax", "pre tax", "excluding tax"))
    after = both or any(
        term in normalized for term in ("sau thue", "after tax", "including vat", "with vat", "gom vat", "co vat")
    )
    if before and after:
        return False
    if before:
        return "excludes_tax"
    if after:
        return "includes_vat"
    return None


def _tax_criterion(value: str | None) -> str | None:
    if value in {"excludes_tax", "includes_vat"}:
        return value
    return None


def _requires_ratio(draft: MetricDraft, context: dict[str, Any]) -> bool:
    if draft.knowledge_id in {"gross_margin", "conversion", "cancellation", "units_per_transaction"}:
        return True
    if draft.knowledge_id == "aov" and draft.variant_id not in {
        "order_average_pre_tax",
        "order_average_after_tax",
        "order_average_after_tax_discount",
    }:
        return True
    spec = (draft.definition or {}).get("metric", draft.definition)
    if draft.knowledge_id == "aov":
        return not _supported_order_average(spec, context)
    metric_name = str(spec.get("name", "")) if isinstance(spec, dict) else ""
    name = normalized_text(draft.name + " " + metric_name)
    average_names = (
        "aov",
        "gia tri don hang trung binh",
        "gia tri trung binh don hang",
        "trung binh moi don",
        "trung binh tren moi don",
        "doanh thu trung binh",
    )
    if any(marker in name for marker in average_names):
        return not _supported_order_average(spec, context)
    return any(
        marker in name
        for marker in (
            "ty le",
            "ti le",
            "ty trong",
            "bien loi nhuan",
            "units per transaction",
            "conversion rate",
            "cancellation rate",
            "gross margin",
            "percentage",
            "ratio",
        )
    )


def _supported_order_average(spec: Any, context: dict[str, Any]) -> bool:
    if not isinstance(spec, dict) or spec.get("formula", {}).get("function") != "AVG":
        return False
    if "/" in str(spec["formula"].get("expression", "")):
        return False
    entity = str(spec.get("base_entity", "")).casefold()
    table = next((item for item in schema_tables(context["schema"]) if item["table_name"].casefold() == entity), None)
    if table is None:
        return False
    label = normalized_text(str(table.get("business_name") or ""))
    if not (
        (entity in {"orders", "order_header", "sales_order"} or "don hang" in label)
        and not any(marker in entity for marker in ("line", "item", "detail", "history"))
    ):
        return False
    parsed = sqlglot.parse_one(spec["formula"]["expression"])
    columns = {column["column_name"].casefold(): column for column in table.get("columns", [])}
    referenced = [columns.get(column.name.casefold()) for column in parsed.find_all(exp.Column)]
    return bool(referenced) and all(
        column is not None
        and not column.get("is_nullable", True)
        and any(
            marker in column.get("data_type", "").upper()
            for marker in ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL")
        )
        for column in referenced
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
