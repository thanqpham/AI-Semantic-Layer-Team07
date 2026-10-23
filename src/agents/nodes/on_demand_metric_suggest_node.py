"""Run the shared metric coordinator with complete request evidence."""

from __future__ import annotations

from typing import Any

from src.agents.nodes.metric_review_node import reviewed_state
from src.agents.state import AgentState
from src.observability import trace_node
from src.services.metric_proposal_generation import prepare_proposal_context
from src.services.metric_workflow import run_metric_workflow


@trace_node("metric_coordinator")
async def on_demand_metric_suggest_node(state: AgentState) -> dict[str, Any]:
    """Coordinate generation, validation, review and one bounded repair round."""
    if not state.get("enriched_schema"):
        return {"error": "on_demand_metric_suggest_node: enriched_schema is empty", "suggested_metrics": []}
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
