"""Validate Metric Designer output before it reaches the Reviewer Agent."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from src.agents.nodes.metric.metric_node_helpers import record_failure
from src.config import get_settings
from src.models.metric_definition import MetricDefinition
from src.models.metric_review import BlockedMetricArtifact, MetricBuildArtifact, MetricReview, ReviewIssue
from src.observability import trace_node
from src.services.metric_knowledge import find_variant, normalized_text
from src.services.metric_review import validate_review_draft
from src.services.metric_review_validation import _parse_definition, schema_tables
from src.services.metric_runtime import invalid_output, validation_failure


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
                reason_code=_blocked_reason_code(artifact.status),
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
        raw = _normalize_artifact(raw)
        if not isinstance(raw.get("criteria", {}), dict):
            raise ValueError("Invalid variant criteria")
        _resolve_aov_identity(raw, context)
        _resolve_knowledge_variant(raw, context)
        _enforce_selected_variant(raw, context)
        item["raw"] = raw
        if raw.get("status") in {"needs_clarification", "unsupported", "rejected"}:
            return BlockedMetricArtifact.model_validate(raw)
        raw["definition"] = _parse_definition(raw.get("definition") or {}).model_dump(mode="json")
        return MetricBuildArtifact.model_validate(raw)
    except (ValueError, TypeError) as exc:
        _record_artifact_error(item, raw, context, exc)
        return None


def _record_artifact_error(item: dict[str, Any], raw: dict[str, Any], context: dict[str, Any], exc: Exception) -> None:
    stage = "repair" if item["attempt"] else "builder"
    error = (
        validation_failure(stage, exc)
        if isinstance(exc, ValidationError)
        else invalid_output(
            stage,
            [
                {
                    "field": "$",
                    "type": "invalid_artifact",
                    "message": _invalid_artifact_message(raw, context, exc),
                }
            ],
        )
    )
    record_failure(item, error)


def _normalize_artifact(raw: dict[str, Any]) -> dict[str, Any]:
    """Wrap a legacy metric payload while preserving the strict artifact contract."""
    raw = dict(raw)
    if isinstance(raw.get("metric"), dict):
        if raw.get("definition") is not None:
            raise ValueError("Đầu ra AI chứa cả metric và definition; chỉ cung cấp definition.")
        raw["definition"] = {key: raw.pop(key) for key in ("metric", "schema_version", "diagnostics") if key in raw}
    definition = raw.get("definition")
    if isinstance(definition, dict):
        if "excluded_notes" in raw:
            if "excluded_notes" in definition and definition["excluded_notes"] != raw["excluded_notes"]:
                raise ValueError("excluded_notes trong và ngoài definition mâu thuẫn.")
            definition = {**definition, "excluded_notes": raw.pop("excluded_notes")}
            raw["definition"] = definition
        spec = definition.get("metric", definition)
        if isinstance(spec, dict):
            raw.setdefault("name", spec.get("name"))
    return raw


def _blocked_reason_code(status: str) -> str:
    return {
        "needs_clarification": "BUILDER_CLARIFICATION",
        "unsupported": "BUILDER_UNSUPPORTED",
        "rejected": "BUILDER_REJECTED",
    }[status]


def _resolve_knowledge_variant(raw: dict[str, Any], context: dict[str, Any]) -> None:
    if not get_settings().metric_knowledge_enabled:
        raw.update(knowledge_id=None, variant_id=None)
        return
    _canonicalize_knowledge_identity(raw, context.get("knowledge", {}))
    if raw.get("knowledge_id"):
        variants = next(
            (m["variants"] for m in context.get("knowledge", {}).get("metrics", []) if m["id"] == raw["knowledge_id"]),
            [],
        )
        if not raw.get("variant_id") and len(variants) == 1:
            raw["variant_id"] = variants[0]["id"]
        if (
            not raw.get("variant_id")
            and variants
            and raw.get("status") in {"unsupported", "rejected", "needs_clarification"}
        ):
            return
        variant = find_variant(context.get("knowledge", {}), raw["knowledge_id"], raw.get("variant_id"))
        if variant is None or any(
            raw.get("criteria", {}).get(key, value) != value for key, value in variant["criteria"].items()
        ):
            raise ValueError("Unverified knowledge variant")
        raw["criteria"] = {**variant["criteria"], **raw.get("criteria", {})}
    elif raw.get("variant_id"):
        raise ValueError("Variant without knowledge family")


def _enforce_selected_variant(raw: dict[str, Any], context: dict[str, Any]) -> None:
    """Reject builder output that does not match the user's server-stored choice."""
    selection = context.get("selected_metric_variant")
    if not selection:
        return
    if any(raw.get(key) != selection.get(key) for key in ("knowledge_id", "variant_id", "criteria")):
        raise ValueError("Generated candidate does not match the selected metric variant")


def _canonicalize_knowledge_identity(raw: dict[str, Any], knowledge: dict[str, Any]) -> None:
    families = {metric["id"] for metric in knowledge.get("metrics", [])}
    identity = raw.get("knowledge_id")
    variant_id = raw.get("variant_id") or identity
    if identity in families or (identity is not None and identity != variant_id):
        return
    matches = [
        metric["id"]
        for metric in knowledge.get("metrics", [])
        if any(variant["id"] == variant_id for variant in metric["variants"])
    ]
    if len(matches) == 1:
        raw.update(knowledge_id=matches[0], variant_id=variant_id)


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
    if not isinstance(spec, dict) or spec.get("formula", {}).get("function") != "AVG":
        return
    expression = normalized_text(str(spec.get("formula", {}).get("expression", ""))) if isinstance(spec, dict) else ""
    if "truoc thue" in name or "price before tax" in expression or "price_before_tax" in expression:
        raw.update(knowledge_id="aov", variant_id="order_average_pre_tax")
    elif "sau thue" in name and "giam gia" in name:
        raw.update(knowledge_id="aov", variant_id="order_average_after_tax_discount")
    elif "sau thue" in name or "price_after_tax" in expression:
        raw.update(knowledge_id="aov", variant_id="order_average_after_tax")


def _invalid_artifact_message(raw: dict[str, Any], context: dict[str, Any], error: Exception) -> str:
    knowledge = context.get("knowledge", {})
    if raw.get("knowledge_id") and find_variant(knowledge, raw["knowledge_id"], raw.get("variant_id")) is None:
        variants = next(
            (
                [variant["id"] for variant in metric["variants"]]
                for metric in knowledge.get("metrics", [])
                if metric["id"] == raw["knowledge_id"]
            ),
            [],
        )
        return f"knowledge_id={raw['knowledge_id']}, variant_id={raw.get('variant_id')}; variant_id hợp lệ: {variants}. Không dùng formula_basis làm variant_id."
    definition = raw.get("definition")
    if not isinstance(definition, dict):
        return "Đầu ra AI thiếu definition dạng MetricDefinition."
    if not str(raw.get("name", "")).strip():
        return "Bản sửa thiếu tên metric."
    if raw.get("knowledge_id") == "aov" and not raw.get("variant_id"):
        return "Bản sửa thiếu variant_id cho công thức AOV."
    if isinstance(error, ValidationError):
        errors = error.errors(include_input=False, include_url=False)
        return "Đầu ra AI chưa hợp lệ: " + "; ".join(
            f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in errors[:3]
        )
    return str(error)


def _validate_artifact(state: dict[str, Any], item: dict[str, Any], artifact: MetricBuildArtifact) -> None:
    item["name"] = artifact.definition.metric.name
    item["definition"] = artifact.definition
    conflict = _tax_conflict(
        state["context"]["question"], artifact.criteria, artifact.definition.metric.name
    ) or _average_tax_conflict(artifact.criteria, artifact.definition, state["context"]["schema"])
    if conflict:
        item["report"] = MetricReview(
            status="needs_revision",
            summary=conflict,
            reason_code="VARIANT_CONFLICT",
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


def _average_tax_conflict(criteria: dict[str, str], definition: MetricDefinition, schema: dict[str, Any]) -> str | None:
    formula = definition.metric.formula
    expression = formula.expression.strip().casefold()
    if formula.function != "AVG" or formula.ratio is not None or not expression.isidentifier():
        return None
    column = next(
        (
            column
            for table in schema_tables(schema)
            if table["table_name"].casefold() == definition.metric.base_entity.casefold()
            for column in table.get("columns", [])
            if column["column_name"].casefold() == expression
        ),
        {},
    )
    meaning = normalized_text(str(column.get("description") or "") + " " + str(column.get("business_name") or ""))
    before_tax = "before_tax" in expression or "truoc thue" in meaning
    after_tax = "after_tax" in expression or "sau thue" in meaning
    basis = criteria.get("tax_basis")
    if basis in {"includes_tax", "includes_vat"} and before_tax and not after_tax:
        return "Biến thể sau thuế không được dùng trực tiếp cột giá trước thuế."
    if basis == "excludes_tax" and after_tax and not before_tax:
        return "Biến thể trước thuế không được dùng trực tiếp cột giá sau thuế."
    return None


def _tax_conflict(question: str, criteria: dict[str, str], name: str) -> str | None:
    asked = normalized_text(question)
    named = normalized_text(name)
    basis = criteria.get("tax_basis")
    before_terms = ("truoc thue", "chua thue", "khong gom vat", "khong gom thue")
    after_terms = ("sau thue", "gom vat", "bao gom vat", "da gom vat")
    before = any(term in asked for term in before_terms)
    after = any(term in asked for term in after_terms)
    if before and after:
        before = after = False
    if basis in {"includes_vat", "includes_tax"} and before:
        return "Biến thể sau thuế trái với yêu cầu trước thuế."
    if basis == "excludes_tax" and after:
        return "Biến thể trước thuế trái với yêu cầu gồm VAT."
    if basis == "includes_vat" and "vat" not in named:
        return "Tên metric phải nêu rõ biến thể gồm VAT."
    if basis == "includes_tax" and not any(term in named for term in ("sau thue", "gom thue")):
        return "Tên metric phải nêu rõ biến thể sau thuế."
    if basis == "excludes_tax" and not any(term in named for term in ("truoc thue", "chua thue", "khong gom thue")):
        return "Tên metric phải nêu rõ biến thể trước thuế."
    return None
