"""Validate Metric Designer output before it reaches the Reviewer Agent."""

from __future__ import annotations

from typing import Any

from src.agents.nodes.metric.metric_node_helpers import record_failure
from src.models.metric_review import BlockedMetricArtifact, MetricBuildArtifact, MetricReview, ReviewIssue
from src.observability import trace_node
from src.services.metric_knowledge import find_variant, normalized_text
from src.services.metric_review import validate_review_draft
from src.services.metric_review_validation import _parse_definition
from src.services.metric_runtime import execution_failure


@trace_node("metric_validate")
async def validate_node(state: dict[str, Any]) -> dict[str, Any]:
    for item in state["items"]:
        if item["phase"] != "new":
            continue
        artifact = _parse_artifact(item, state["context"])
        if artifact is None:
            continue
        if isinstance(artifact, BlockedMetricArtifact):
            item["report"] = MetricReview(
                status=artifact.status,
                summary=artifact.reason,
                clarification=artifact.reason if artifact.status == "needs_clarification" else None,
            )
            item["phase"] = "done"
            continue
        _validate_artifact(state, item, artifact)
    return state


def _parse_artifact(
    item: dict[str, Any], context: dict[str, Any]
) -> MetricBuildArtifact | BlockedMetricArtifact | None:
    raw = {key: value for key, value in item["raw"].items() if key != "candidate_id"}
    if raw.get("status") == "candidate":
        raw["status"] = "ready"
    try:
        if not isinstance(raw.get("criteria", {}), dict):
            raise ValueError("Invalid variant criteria")
        _resolve_aov_identity(raw, context)
        if raw.get("knowledge_id"):
            variants = next(
                (
                    m["variants"]
                    for m in context.get("knowledge", {}).get("metrics", [])
                    if m["id"] == raw["knowledge_id"]
                ),
                [],
            )
            if not raw.get("variant_id") and len(variants) == 1:
                raw["variant_id"] = variants[0]["id"]
            variant = find_variant(context.get("knowledge", {}), raw["knowledge_id"], raw.get("variant_id"))
            if variant is None or any(
                raw.get("criteria", {}).get(key, value) != value for key, value in variant["criteria"].items()
            ):
                raise ValueError("Unverified knowledge variant")
            raw["criteria"] = {**variant["criteria"], **raw.get("criteria", {})}
        elif raw.get("variant_id"):
            raise ValueError("Variant without knowledge family")
        item["raw"] = {**item["raw"], **raw}
        if raw.get("status") in {"needs_clarification", "unsupported", "rejected"}:
            return BlockedMetricArtifact.model_validate(raw)
        _parse_definition(raw.get("definition") or {})
        return MetricBuildArtifact.model_validate(raw)
    except (ValueError, TypeError):
        detail = _invalid_artifact_message(raw, context)
        record_failure(item, execution_failure("INVALID_AGENT_OUTPUT", "builder").model_copy(update={"message": detail}))
        return None


def _resolve_aov_identity(raw: dict[str, Any], context: dict[str, Any]) -> None:
    aov_ids = {"order_average_pre_tax", "order_average_after_tax", "order_average_after_tax_discount"}
    if raw.get("knowledge_id") and raw["knowledge_id"] != "aov":
        return
    if raw.get("variant_id"):
        if raw["variant_id"] in aov_ids:
            raw["knowledge_id"] = "aov"
        return
    knowledge_has_aov = any(m["id"] == "aov" for m in context.get("knowledge", {}).get("metrics", []))
    if not knowledge_has_aov:
        return
    name = normalized_text(str(raw.get("name", "")))
    formula = raw.get("definition") or {}
    spec = formula.get("metric", formula) if isinstance(formula, dict) else {}
    expression = normalized_text(str(spec.get("formula", {}).get("expression", ""))) if isinstance(spec, dict) else ""
    if "truoc thue" in name or "price before tax" in expression or "price_before_tax" in expression:
        raw.update(knowledge_id="aov", variant_id="order_average_pre_tax")
    elif "sau thue" in name and "giam gia" in name:
        raw.update(knowledge_id="aov", variant_id="order_average_after_tax_discount")
    elif "sau thue" in name or "price_after_tax" in expression:
        raw.update(knowledge_id="aov", variant_id="order_average_after_tax")


def _invalid_artifact_message(raw: dict[str, Any], context: dict[str, Any]) -> str:
    definition = raw.get("definition")
    if not isinstance(definition, dict):
        return "Bản sửa thiếu definition dạng MetricDefinition."
    if not str(raw.get("name", "")).strip():
        return "Bản sửa thiếu tên metric."
    if raw.get("knowledge_id") == "aov" and not raw.get("variant_id"):
        return "Bản sửa thiếu variant_id cho công thức AOV."
    knowledge = context.get("knowledge", {})
    if raw.get("knowledge_id") and find_variant(knowledge, raw["knowledge_id"], raw.get("variant_id")) is None:
        return "Bản sửa có knowledge_id hoặc variant_id không tồn tại trong knowledge đã giao."
    return "Bản sửa không khớp contract MetricBuildArtifact hoặc công thức không hợp lệ."


def _validate_artifact(state: dict[str, Any], item: dict[str, Any], artifact: MetricBuildArtifact) -> None:
    item["name"] = artifact.definition.metric.name
    item["definition"] = artifact.definition
    conflict = _tax_conflict(state["context"]["question"], artifact.criteria, artifact.definition.metric.name)
    if conflict:
        item["report"] = MetricReview(
            status="needs_revision",
            summary=conflict,
            issues=[
                ReviewIssue(
                    code="VARIANT_CONFLICT",
                    message=conflict,
                    evidence=state["context"]["question"],
                    action="Chỉ tạo biến thể phù hợp với yêu cầu đã nêu.",
                )
            ],
        )
        item["phase"] = "done"
        return
    definition, report = validate_review_draft(state["context"], artifact.model_dump(mode="json"))
    item["definition"], item["report"] = definition, report
    item["phase"] = "done" if report else "awaiting_review"


def _tax_conflict(question: str, criteria: dict[str, str], name: str) -> str | None:
    asked = normalized_text(question)
    named = normalized_text(name)
    basis = criteria.get("tax_basis")
    if basis in {"includes_vat", "includes_tax"} and any(
        term in asked for term in ("truoc thue", "chua thue", "khong gom vat", "khong gom thue")
    ):
        return "Biến thể sau thuế trái với yêu cầu trước thuế."
    if basis == "excludes_tax" and any(term in asked for term in ("gom vat", "bao gom vat", "da gom vat")):
        return "Biến thể trước thuế trái với yêu cầu gồm VAT."
    if basis == "includes_vat" and "vat" not in named:
        return "Tên metric phải nêu rõ biến thể gồm VAT."
    if basis == "includes_tax" and not any(term in named for term in ("sau thue", "gom thue")):
        return "Tên metric phải nêu rõ biến thể sau thuế."
    if basis == "excludes_tax" and not any(term in named for term in ("truoc thue", "chua thue", "khong gom thue")):
        return "Tên metric phải nêu rõ biến thể trước thuế."
    return None


