"""Bounded LangGraph coordinator for builders, code validation and batch reviewers."""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph

from src.agents.roles.metric_designer_agent import generate_metric_drafts
from src.agents.roles.metric_reviewer_agent import review_metric_batch
from src.agents.nodes.metric.metric_node_helpers import record_failure
from src.agents.nodes.metric.repair_node import repair_node
from src.agents.nodes.metric.validate_node import validate_node
from src.models.metric_review import (
    MetricReview,
    MetricReviewDecision,
)
from src.observability import trace_node
from src.services.metric_correlation import correlate
from src.services.metric_review import (
    _complete_report,
    _enforce_review,
    _record_review_result,
    validate_review_draft,
)
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
    graph.add_node("validate", validate_node)
    graph.add_node("review", _review)
    graph.add_node("coordinate", _coordinate)
    graph.add_node("repair", repair_node)
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
        record_failure(item, exc.error)
        state["items"] = [item]
    except Exception:
        item = _item({})
        record_failure(item, execution_failure("PROVIDER_ERROR", "builder"))
        state["items"] = [item]
    return state


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
            record_failure(item, exc.error)
    except Exception:
        for item in pending:
            record_failure(item, execution_failure("PROVIDER_ERROR", "reviewer"))
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
        record_failure(item, execution_failure("INVALID_AGENT_OUTPUT", "reviewer"))


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


async def _coordinate(state: MetricWorkflowState) -> dict[str, Any]:
    state["repair_ids"] = [item["id"] for item in state["items"] if state["allow_repair"] and _needs_repair(item)]
    return state


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
