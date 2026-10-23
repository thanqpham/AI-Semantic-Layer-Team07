"""Gate metric suggestions before they reach human review or persistence."""

from __future__ import annotations

from typing import Any

from src.agents.state import AgentState
from src.models.metric_definition import MetricDefinition
from src.models.metric_review import MetricCandidateReport, MetricReview
from src.models.schemas import MetricSuggestionItem
from src.observability import trace_node
from src.services.metric_dedupe import merge_dedupe
from src.services.metric_workflow import run_metric_workflow


@trace_node("metric_review")
async def metric_review_node(state: AgentState) -> dict[str, Any]:
    """Review drafts, cap discovery output, and expose clarification without write actions."""
    context = state.get("proposal_context")
    if "reviewed_proposals" in state:
        return reviewed_state(state["reviewed_proposals"], state)
    if not context or state.get("error"):
        return {"suggested_metrics": [], "suggestion_action": None}
    proposals = await run_metric_workflow(context, drafts=state.get("metric_drafts", []))
    return reviewed_state(proposals, state)


def reviewed_state(proposals: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    """Keep only passing definitions actionable and retain blocked decisions for the UI."""
    limit = 5
    passing = [p for p in proposals if p["review"]["status"] == "pass"][:limit]
    items = [_suggestion(p) for p in passing]
    kept, notices = merge_dedupe(items, [], [], state.get("existing_metrics") or [])
    blocked = [
        MetricCandidateReport(name=p["name"], review=MetricReview.model_validate(p["review"])).model_dump(mode="json")
        for p in proposals
        if p["review"]["status"] != "pass"
    ][:5]
    questions = [
        p["review"].get("clarification") or p["review"]["summary"]
        for p in proposals
        if p["review"]["status"] == "needs_clarification"
    ]
    response: dict[str, Any] = {
        "intent": "metric_query",
        "suggested_metrics": [i.model_dump(mode="json") for i in kept],
        "reviewed_proposals": proposals,
        "blocked_candidates": blocked,
        "duplicate_notices": [n.model_dump(mode="json") for n in notices],
        "suggestion_action": ("save_metric" if state.get("can_generate_metrics") else "submit_metric_request")
        if kept
        else None,
    }
    if questions and not kept:
        response["clarification"] = {"prompt": "\n".join(dict.fromkeys(questions)), "options": []}
    errors = any(p["review"]["status"] == "error" for p in proposals)
    response["run_status"] = (
        "partial"
        if errors and (kept or notices)
        else "error"
        if errors
        else "needs_clarification"
        if questions and not kept
        else "completed"
    )
    return response


def _suggestion(proposal: dict[str, Any]) -> MetricSuggestionItem:
    definition = MetricDefinition.model_validate(proposal["final_definition"])
    return MetricSuggestionItem(
        definition=definition,
        yaml_preview=definition.to_yaml(),
        review=MetricReview.model_validate(proposal["review"]),
        variant_id=proposal["review"].get("variant_id"),
        criteria=proposal["review"].get("criteria", {}),
    )
