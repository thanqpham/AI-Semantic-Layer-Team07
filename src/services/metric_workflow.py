"""Bounded LangGraph coordinator for builders, code validation and batch reviewers."""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from src.models.metric_review import (
    BlockedMetricArtifact,
    MetricBuildArtifact,
    MetricReview,
    MetricReviewDecision,
    ReviewIssue,
)
from src.observability import trace_node
from src.services.metric_correlation import correlate
from src.services.metric_knowledge import find_variant, normalized_text
from src.services.metric_proposal_generation import generate_metric_drafts, repair_metric_drafts
from src.services.metric_review import (
    _complete_report,
    _enforce_review,
    _record_review_result,
    review_metric_batch,
    validate_review_draft,
)
from src.services.metric_review_validation import _parse_definition
from src.services.metric_runtime import MetricCallError, execution_failure


class MetricWorkflowState(TypedDict):
    context: dict[str, Any]
    task_id: str
    items: list[dict[str, Any]]
    repair_ids: list[str]
    preset: bool
    allow_repair: bool


async def run_metric_workflow(
    context: dict[str, Any], drafts: list[dict[str, Any]] | None = None, allow_repair: bool = True
) -> list[dict[str, Any]]:
    """Run the same bounded coordinator for chat, API generation and re-review."""
    context = {key: value for key, value in context.items() if key not in {"task_id", "candidate", "handoffs", "audit"}}
    state: MetricWorkflowState = {
        "context": context,
        "task_id": str(uuid4()),
        "items": [],
        "repair_ids": [],
        "preset": drafts is not None,
        "allow_repair": allow_repair,
    }
    state["items"] = [_item(raw) for raw in drafts or []]
    result = await _graph().ainvoke(state)
    return [_evidence(result, item) for item in result["items"]]


def _graph() -> Any:
    graph = StateGraph(MetricWorkflowState)
    graph.add_node("build", _build)
    graph.add_node("validate", _validate)
    graph.add_node("review", _review)
    graph.add_node("coordinate", _coordinate)
    graph.add_node("repair", _repair)
    graph.set_conditional_entry_point(
        lambda s: "validate" if s["preset"] else "build", {"validate": "validate", "build": "build"}
    )
    graph.add_edge("build", "validate")
    graph.add_edge("validate", "review")
    graph.add_edge("review", "coordinate")
    graph.add_conditional_edges(
        "coordinate", lambda s: "repair" if s["repair_ids"] else END, {"repair": "repair", END: END}
    )
    graph.add_edge("repair", "validate")
    return graph.compile()


def _item(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid4()),
        "raw": raw,
        "original": raw.get("definition"),
        "name": str(raw.get("name") or "Metric theo yêu cầu"),
        "attempt": 0,
        "definition": None,
        "report": None,
        "initial_report": None,
        "phase": "new",
    }


@trace_node("metric_suggest")
async def _build(state: MetricWorkflowState) -> dict[str, Any]:
    if state["items"]:
        return state
    try:
        drafts = await generate_metric_drafts(state["context"], state["task_id"])
        state["items"] = [_item(raw) for raw in drafts]
    except MetricCallError as exc:
        item = _item({})
        _failure(item, exc.error)
        state["items"] = [item]
    except Exception:
        item = _item({})
        _failure(item, execution_failure("PROVIDER_ERROR", "builder"))
        state["items"] = [item]
    return state


@trace_node("metric_validate")
async def _validate(state: MetricWorkflowState) -> dict[str, Any]:
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
        _failure(item, execution_failure("INVALID_AGENT_OUTPUT", "builder").model_copy(update={"message": detail}))
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


def _validate_artifact(state: MetricWorkflowState, item: dict[str, Any], artifact: MetricBuildArtifact) -> None:
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


@trace_node("metric_review")
async def _review(state: MetricWorkflowState) -> dict[str, Any]:
    pending = [item for item in state["items"] if item["phase"] == "awaiting_review"]
    if not pending:
        return state
    payload = [_review_request(state, item) for item in pending]
    try:
        records = await review_metric_batch(state["context"], state["task_id"], payload)
        indexed = correlate(records, {item["id"] for item in pending})
        for item in pending:
            _apply_decision(state, item, indexed[item["id"]])
    except MetricCallError as exc:
        for item in pending:
            _failure(item, exc.error)
    except Exception:
        for item in pending:
            _failure(item, execution_failure("PROVIDER_ERROR", "reviewer"))
    return state


def _review_request(state: MetricWorkflowState, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": item["id"],
        "definition": item["definition"].model_dump(mode="json"),
        "variant_id": item["raw"].get("variant_id"),
        "criteria": item["raw"].get("criteria", {}),
        "output_feedback": item["report"].summary if item["report"] else None,
    }


def _apply_decision(state: MetricWorkflowState, item: dict[str, Any], record: dict[str, Any] | None) -> None:
    try:
        decision = MetricReviewDecision.model_validate(record)
        if decision.status == "needs_revision" and not decision.issues:
            raise ValueError("Revision needs evidence")
        if decision.status == "pass" and (decision.issues or decision.clarification):
            raise ValueError("Contradictory approval")
        report = MetricReview(**decision.model_dump(exclude={"candidate_id"}))
        item["report"] = _enforce_review(report, None, state["context"])
        item["phase"] = "done"
    except (ValueError, TypeError):
        _failure(item, execution_failure("INVALID_AGENT_OUTPUT", "reviewer"))


async def _coordinate(state: MetricWorkflowState) -> dict[str, Any]:
    state["repair_ids"] = [item["id"] for item in state["items"] if state["allow_repair"] and _needs_repair(item)]
    return state


def _needs_repair(item: dict[str, Any]) -> bool:
    report = item["report"]
    return (
        item["attempt"] == 0
        and report is not None
        and (
            report.status == "needs_revision"
            or (report.execution_error is not None and report.execution_error.code == "INVALID_AGENT_OUTPUT")
        )
    )


@trace_node("metric_repair")
async def _repair(state: MetricWorkflowState) -> dict[str, Any]:
    pending = [item for item in state["items"] if item["id"] in state["repair_ids"] and item["attempt"] == 0]
    builders = []
    for item in pending:
        item["initial_report"] = item["report"]
        item["attempt"] = 1
        error = item["report"].execution_error
        if error and error.stage == "reviewer" and item["definition"] is not None:
            item["phase"] = "awaiting_review"
        else:
            builders.append(item)
    if builders:
        await _repair_builders(state, builders)
    return state


async def _repair_builders(state: MetricWorkflowState, items: list[dict[str, Any]]) -> None:
    payload = [_repair_request(state, item) for item in items]
    try:
        records = await repair_metric_drafts(state["context"], payload, state["task_id"])
        indexed = correlate(records, {item["id"] for item in items})
        for item in items:
            if indexed[item["id"]] is None:
                error = execution_failure("INVALID_AGENT_OUTPUT", "repair").model_copy(
                    update={"message": "Bản sửa thiếu, trùng hoặc dùng sai candidate_id."}
                )
                _failure(item, error)
            else:
                item["raw"], item["phase"] = indexed[item["id"]], "new"
    except MetricCallError as exc:
        for item in items:
            _failure(item, exc.error)
    except Exception:
        for item in items:
            _failure(item, execution_failure("PROVIDER_ERROR", "repair"))


def _repair_request(state: MetricWorkflowState, item: dict[str, Any]) -> dict[str, Any]:
    report = item["report"]
    return {
        "candidate_id": item["id"],
        "artifact": item["raw"],
        "feedback": report.model_dump(
            mode="json", exclude={"handoffs", "original_definition", "sources", "requirement"}
        ),
    }


def _failure(item: dict[str, Any], error: Any) -> None:
    item["report"] = MetricReview(status="error", summary=error.message, execution_error=error)
    item["phase"] = "done"


def _evidence(state: MetricWorkflowState, item: dict[str, Any]) -> dict[str, Any]:
    report = item["report"] or MetricReview(
        status="error",
        summary="Chưa nhận được kết quả thẩm định.",
        execution_error=execution_failure("INVALID_AGENT_OUTPUT", "reviewer"),
    )
    report = _complete_report(
        report,
        state["context"],
        item["original"],
        bool(item["attempt"]),
        item["raw"].get("knowledge_id"),
        item["raw"].get("variant_id"),
        item["raw"].get("criteria", {}),
    )
    if item["initial_report"]:
        report.repair_reason = item["initial_report"].summary
        report.repair_feedback = item["initial_report"].issues
    _record_review_result(report)
    context = {
        **state["context"],
        "task_id": state["task_id"],
        "candidate": {
            "id": item["id"],
            "name": item["name"],
            "knowledge_id": item["raw"].get("knowledge_id"),
            "variant_id": item["raw"].get("variant_id"),
            "criteria": item["raw"].get("criteria", {}),
        },
    }
    return {
        "name": item["name"],
        "context": context,
        "original_definition": item["original"],
        "final_definition": item["definition"].model_dump(mode="json")
        if item["definition"] and report.status == "pass"
        else None,
        "review": report.model_dump(mode="json"),
    }
