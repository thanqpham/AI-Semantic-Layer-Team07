"""Bounded LangGraph coordinator for builders, code validation and batch reviewers."""

from __future__ import annotations

from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from src.agents.nodes.metric.metric_node_helpers import record_failure
from src.agents.nodes.metric.repair_node import repair_node
from src.agents.nodes.metric.validate_node import validate_node
from src.agents.roles.metric_designer_agent import generate_metric_drafts
from src.agents.roles.metric_reviewer_agent import review_metric_batch
from src.models.metric_definition import MetricDefinition
from src.models.metric_review import (
    MetricReview,
    MetricReviewDecision,
)
from src.observability import trace_node
from src.observability.langfuse_tracing import observation, trace_summary
from src.services.metric_correlation import correlate
from src.services.metric_dedupe import find_catalog_duplicate
from src.services.metric_review import (
    _complete_report,
    _enforce_review,
    _record_review_result,
)
from src.services.metric_runtime import MetricCallError, execution_failure, invalid_output, validation_failure


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
    with observation("metric_workflow", agent=True) as span:
        if span is not None:
            span.update(input=trace_summary(mode=context.get("proposal_mode"), proposal_count=len(state["items"])))
        result = await _graph().ainvoke(state)
        evidence = [_evidence(result, item) for item in result["items"]]
        if span is not None:
            span.update(
                output=trace_summary(
                    proposal_count=len(evidence),
                    pass_count=sum(item["review"]["status"] == "pass" for item in evidence),
                    repair_count=sum(bool(item["review"].get("repair_reason")) for item in evidence),
                )
            )
        return evidence


def _graph() -> Any:
    graph = StateGraph(MetricWorkflowState)
    graph.add_node("build", _build)
    graph.add_node("validate", validate_node)
    graph.add_node("dedupe", _check_duplicates)
    graph.add_node("review", _review)
    graph.add_node("coordinate", _coordinate)
    graph.add_node("repair", repair_node)
    graph.set_conditional_entry_point(
        lambda s: "validate" if s["preset"] else "build", {"validate": "validate", "build": "build"}
    )
    graph.add_edge("build", "validate")
    graph.add_edge("validate", "dedupe")
    graph.add_edge("dedupe", "review")
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
        "duplicate": None,
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


@trace_node("dedupe")
async def _check_duplicates(state: MetricWorkflowState) -> dict[str, Any]:
    for item in state["items"]:
        if item["phase"] == "awaiting_review":
            match = find_catalog_duplicate(item["definition"], state["context"].get("existing_metrics", []))
            item["duplicate"] = match.model_dump(mode="json") if match else None
    return state


@trace_node("metric_review")
async def _review(state: MetricWorkflowState) -> dict[str, Any]:
    pending = [item for item in state["items"] if item["phase"] == "awaiting_review"]
    if not pending:
        return state
    payload = [_review_request(state, item) for item in pending]
    try:
        records = await review_metric_batch(state["context"], state["task_id"], payload)
        _apply_review_records(state, pending, records)
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
        "filter_scope": _filter_scope(item["definition"]),
        "variant_id": item["raw"].get("variant_id"),
        "criteria": item["raw"].get("criteria", {}),
        "output_feedback": item["report"].summary if item["report"] else None,
        "duplicate_match": item["duplicate"],
    }


def _filter_scope(definition: MetricDefinition) -> dict[str, Any]:
    scopes = {"metric": definition.metric.filters}
    if definition.metric.query_plan is not None:
        scopes["query_plan"] = [
            item
            for stage in definition.metric.query_plan.stages
            for item in [*stage.filters, *(filter_item for aggregate in stage.aggregates for filter_item in aggregate.filters)]
        ]
    ratio = definition.metric.formula.ratio
    if ratio is not None:
        scopes.update(numerator=ratio.numerator.filters, denominator=ratio.denominator.filters)
    return {
        scope: [item.model_dump(mode="json", exclude={"column_id"}) for item in filters]
        if filters
        else "Toàn bộ tập chung, không thêm điều kiện lọc ở phạm vi này."
        for scope, filters in scopes.items()
    }


def _apply_review_records(
    state: MetricWorkflowState, pending: list[dict[str, Any]], records: list[dict[str, Any]]
) -> None:
    indexed = correlate(records, {item["id"] for item in pending})
    for item in pending:
        if indexed[item["id"]] is None:
            count = sum(record.get("candidate_id") == item["id"] for record in records)
            error_type = "duplicate_candidate_id" if count > 1 else "missing_candidate_id"
            record_failure(
                item,
                invalid_output(
                    "reviewer",
                    [
                        {
                            "field": "candidate_id",
                            "type": error_type,
                            "message": "Reviewer trả trùng decision cho candidate này."
                            if count > 1
                            else "Không có decision khớp candidate này; có thể thiếu hoặc sai candidate_id.",
                        }
                    ],
                ),
            )
        else:
            _apply_decision(state, item, indexed[item["id"]])


def _apply_decision(state: MetricWorkflowState, item: dict[str, Any], record: dict[str, Any] | None) -> None:
    try:
        decision = MetricReviewDecision.model_validate(record)
        if decision.status == "needs_revision" and not decision.issues:
            raise ValueError("issues:revision_without_issues")
        if decision.status == "pass" and (decision.issues or decision.clarification):
            field = "issues" if decision.issues else "clarification"
            raise ValueError(f"{field}:contradictory_pass")
        report = MetricReview(**decision.model_dump(exclude={"candidate_id"}))
        item["report"] = _enforce_review(report, None, state["context"])
        item["phase"] = "done"
    except ValidationError as exc:
        record_failure(item, validation_failure("reviewer", exc))
    except ValueError as exc:
        field, error_type = str(exc).split(":", 1)
        record_failure(
            item,
            invalid_output(
                "reviewer",
                [
                    {
                        "field": field,
                        "type": error_type,
                        "message": "Trạng thái thẩm định mâu thuẫn với issues/clarification.",
                    }
                ],
            ),
        )


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


@trace_node("metric_conclude")
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
        "duplicate": item["duplicate"] if report.status == "pass" else None,
    }
