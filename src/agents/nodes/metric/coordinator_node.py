"""Run the shared metric coordinator with complete request evidence."""

from __future__ import annotations

from typing import Any

from src.agents.nodes.metric.metric_review_node import reviewed_state
from src.agents.state import AgentState
from src.agents.workflows.metric_proposal_workflow import run_metric_workflow
from src.observability import trace_node
from src.services.metric_proposal_context import prepare_proposal_context


@trace_node("metric_coordinator")
async def coordinator_node(state: AgentState) -> dict[str, Any]:
    """Coordinate generation, validation, review and one bounded repair round."""
    if not state.get("enriched_schema"):
        return {"error": "coordinator_node: enriched_schema is empty", "suggested_metrics": []}
    try:
        context = prepare_proposal_context(state)
    except ValueError as exc:
        return {
            "intent": "metric_query",
            "suggested_metrics": [],
            "run_status": "needs_clarification",
            "clarification": {"prompt": str(exc), "options": []},
            "suggestion_action": None,
        }
    proposals = await run_metric_workflow(context)
    return {**reviewed_state(proposals, state), "proposal_context": context}
