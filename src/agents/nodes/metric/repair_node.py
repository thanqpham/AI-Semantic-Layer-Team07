"""Repair only candidates selected by the metric workflow coordinator."""

from __future__ import annotations

from typing import Any

from src.agents.nodes.metric.metric_node_helpers import record_failure
from src.agents.roles.metric_designer_agent import repair_metric_drafts
from src.observability import trace_node
from src.services.metric_correlation import correlate
from src.services.metric_runtime import MetricCallError, execution_failure


@trace_node("metric_repair")
async def repair_node(state: dict[str, Any]) -> dict[str, Any]:
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


async def _repair_builders(state: dict[str, Any], items: list[dict[str, Any]]) -> None:
    payload = [_repair_request(state, item) for item in items]
    try:
        records = await repair_metric_drafts(state["context"], payload, state["task_id"])
        indexed = correlate(records, {item["id"] for item in items})
        for item in items:
            if indexed[item["id"]] is None:
                error = execution_failure("INVALID_AGENT_OUTPUT", "repair").model_copy(
                    update={"message": "Bản sửa thiếu, trùng hoặc dùng sai candidate_id."}
                )
                record_failure(item, error)
            else:
                item["raw"], item["phase"] = indexed[item["id"]], "new"
    except MetricCallError as exc:
        for item in items:
            record_failure(item, exc.error)
    except Exception:
        for item in items:
            record_failure(item, execution_failure("PROVIDER_ERROR", "repair"))


def _repair_request(state: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    report = item["report"]
    return {
        "candidate_id": item["id"],
        "artifact": item["raw"],
        "feedback": report.model_dump(
            mode="json", exclude={"handoffs", "original_definition", "sources", "requirement"}
        ),
    }
