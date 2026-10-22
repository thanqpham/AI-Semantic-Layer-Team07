"""Generate drafts with the same evidence the independent reviewer will receive."""

from __future__ import annotations

from typing import Any

from src.agents.state import AgentState
from src.models.metric_review import MetricReview
from src.observability import trace_node
from src.services.metric_proposal_generation import generate_metric_drafts, prepare_proposal_context


@trace_node("metric_suggest")
async def on_demand_metric_suggest_node(state: AgentState) -> dict[str, Any]:
    """Prepare complete metadata-only context and generate unapproved drafts."""
    if not state.get("enriched_schema"):
        return {"error": "on_demand_metric_suggest_node: enriched_schema is empty", "suggested_metrics": []}
    try:
        context = prepare_proposal_context(state)
    except ValueError as exc:
        return {"intent": "metric_query", "suggested_metrics": [], "clarification": {"prompt": str(exc), "options": []}}
    try:
        drafts = await generate_metric_drafts(context)
        return {"intent": "metric_query", "proposal_context": context, "metric_drafts": drafts}
    except Exception:
        review = MetricReview(status="error", summary="Không thể sinh định nghĩa hợp lệ để thẩm định. Hãy thử lại.")
        return {
            "intent": "metric_query",
            "suggested_metrics": [],
            "blocked_candidates": [{"name": "Metric đề xuất", "review": review.model_dump(mode="json")}],
            "suggestion_action": None,
        }
