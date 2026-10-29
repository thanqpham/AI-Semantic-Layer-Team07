"""Gate metric suggestions before they reach human review or persistence."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.agents.state import AgentState
from src.agents.workflows.metric_proposal_workflow import run_metric_workflow
from src.models.metric_definition import MetricDefinition
from src.models.metric_review import MetricCandidateReport, MetricReview
from src.models.schemas import DuplicateMetricNotice, MetricSuggestionItem
from src.observability import trace_node


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
    for proposal in proposals:
        proposal["group_name"] = _group_name(proposal)
    passing = [p for p in proposals if p["review"]["status"] == "pass"][:5]
    kept = [_suggestion(p) for p in passing if not p.get("duplicate")]
    notices = [DuplicateMetricNotice.model_validate(p["duplicate"]) for p in passing if p.get("duplicate")]
    response: dict[str, Any] = {
        "intent": "metric_query",
        "suggested_metrics": [i.model_dump(mode="json") for i in kept],
        "reviewed_proposals": proposals,
        "blocked_candidates": _blocked_reports(proposals),
        "duplicate_notices": [n.model_dump(mode="json") for n in notices],
        "suggestion_action": ("save_metric" if state.get("can_generate_metrics") else "submit_metric_request")
        if kept
        else None,
    }
    questions = _clarification_questions(proposals)
    if questions:
        response["clarification"] = {
            "prompt": "\n".join(dict.fromkeys(questions)),
            "options": _variant_options(proposals),
        }
    response["run_status"] = _run_status(proposals, kept, notices, questions)
    return response


def _blocked_reports(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return bounded review reports with stable candidate and family identities."""
    return [
        MetricCandidateReport(
            name=p["name"],
            candidate_id=p.get("candidate_id"),
            group_id=p.get("group_id"),
            group_name=p.get("group_name"),
            review=MetricReview.model_validate(p["review"]),
        ).model_dump(mode="json")
        for p in proposals
        if p["review"]["status"] != "pass"
    ][:5]


def _clarification_questions(proposals: list[dict[str, Any]]) -> list[str]:
    return [
        p["review"].get("clarification") or p["review"]["summary"]
        for p in proposals
        if p["review"]["status"] == "needs_clarification"
    ]


def _run_status(
    proposals: list[dict[str, Any]],
    kept: list[MetricSuggestionItem],
    notices: list[DuplicateMetricNotice],
    questions: list[str],
) -> str:
    errors = any(p["review"]["status"] == "error" for p in proposals)
    if errors and (kept or notices):
        return "partial"
    if errors:
        return "error"
    return "needs_clarification" if questions and not kept else "completed"


def _variant_options(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Offer curated family variants; selection reruns schema validation before review."""
    options: dict[tuple[str, str], dict[str, Any]] = {}
    for proposal in proposals:
        if proposal["review"]["status"] != "needs_clarification" or not proposal.get("group_id"):
            continue
        for option in _family_options(proposal, proposals):
            payload = option["action_payload"]
            options[(payload["knowledge_id"], payload["variant_id"])] = option
    return list(options.values())[:5]


def _family_options(proposal: dict[str, Any], proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    context = proposal.get("context", {})
    family_id = proposal["group_id"]
    family = next(
        (item for item in context.get("knowledge", {}).get("metrics", []) if item.get("id") == family_id), None
    )
    if not family:
        return []
    options = []
    for variant in family.get("variants", []):
        if _has_reviewed_sibling(proposals, family_id, variant):
            options.append(_variant_option(proposal, family, variant))
    return options


def _has_reviewed_sibling(proposals: list[dict[str, Any]], family_id: str, variant: dict[str, Any]) -> bool:
    for candidate in proposals:
        identity = candidate.get("context", {}).get("candidate", {})
        review = candidate.get("review", {})
        if (
            candidate.get("group_id") == family_id
            and candidate.get("final_definition")
            and identity.get("id")
            and identity.get("knowledge_id") == family_id
            and identity.get("variant_id") == variant["id"]
            and review.get("status") == "pass"
            and review.get("variant_id") == variant["id"]
            and all(review.get("criteria", {}).get(key) == value for key, value in variant["criteria"].items())
        ):
            return True
    return False


def _variant_option(proposal: dict[str, Any], family: dict[str, Any], variant: dict[str, Any]) -> dict[str, Any]:
    criteria = variant.get("criteria", {})
    return {
        "id": f"metric-variant-{uuid4()}",
        "label": variant.get("name") or variant["id"],
        "description": ", ".join(f"{key}: {value}" for key, value in criteria.items()),
        "action": "generate_metric_variant",
        "action_payload": {
            "requirement": proposal.get("context", {}).get("requirement", ""),
            "knowledge_id": family["id"],
            "variant_id": variant["id"],
            "criteria": criteria,
        },
    }


def _suggestion(proposal: dict[str, Any]) -> MetricSuggestionItem:
    definition = MetricDefinition.model_validate(proposal["final_definition"])
    return MetricSuggestionItem(
        definition=definition,
        yaml_preview=definition.to_yaml(),
        review=MetricReview.model_validate(proposal["review"]),
        candidate_id=proposal.get("candidate_id"),
        group_id=proposal.get("group_id"),
        group_name=proposal.get("group_name"),
        variant_id=proposal["review"].get("variant_id"),
        criteria=proposal["review"].get("criteria", {}),
    )


def _group_name(proposal: dict[str, Any]) -> str | None:
    """Use only the loaded, validated knowledge family for a display group."""
    context = proposal.get("context", {})
    knowledge_id = proposal.get("group_id")
    return next(
        (item["name"] for item in context.get("knowledge", {}).get("metrics", []) if item.get("id") == knowledge_id),
        None,
    )
