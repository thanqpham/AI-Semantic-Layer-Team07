"""Draft generation and mandatory post-generation review graph tests."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.chat_graph import build_chat_graph
from src.agents.graph import END, _route_after_review
from src.agents.nodes.metric_review_node import metric_review_node, reviewed_state
from src.agents.nodes.on_demand_metric_suggest_node import on_demand_metric_suggest_node
from src.agents.nodes.save_node import _selected_review_evidence
from src.models.metric_review import MetricDraft, MetricDraftBatch, MetricReview
from src.services.metric_proposal_generation import generate_metric_drafts
from tests.metric_review_helpers import context, definition, schema


async def test_empty_state_returns_error():
    assert "error" in await on_demand_metric_suggest_node({})


async def test_generator_returns_untrusted_drafts_not_actionable_suggestions():
    draft = {"name": "Doanh thu", "definition": definition()}
    with patch(
        "src.agents.nodes.on_demand_metric_suggest_node.generate_metric_drafts", AsyncMock(return_value=[draft])
    ):
        result = await on_demand_metric_suggest_node({"enriched_schema": schema(), "user_message": "Doanh thu"})
    assert result["metric_drafts"] == [draft]
    assert not result.get("suggested_metrics") and not result.get("suggestion_action")


async def test_generation_does_not_discard_invalid_reference_before_repair():
    batch = MetricDraftBatch(candidates=[MetricDraft(name="Metric", definition=definition("missing"))])
    with patch("src.services.metric_proposal_generation.invoke_metric_json", AsyncMock(return_value=batch)):
        drafts = await generate_metric_drafts(context())
    assert drafts[0]["definition"]["metric"]["formula"]["expression"] == "missing"


async def test_generation_error_cannot_bypass_reviewer():
    with patch(
        "src.agents.nodes.on_demand_metric_suggest_node.generate_metric_drafts", AsyncMock(side_effect=RuntimeError)
    ):
        initial = await on_demand_metric_suggest_node({"enriched_schema": schema()})
    result = {**initial, **await metric_review_node(initial)}
    assert result["blocked_candidates"][0]["review"]["status"] == "error"
    assert result["suggested_metrics"] == [] and result["suggestion_action"] is None


def test_chat_graph_has_mandatory_review_edge_and_legacy_blocks_unreviewed_state():
    graph = build_chat_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("metric_suggest", "metric_review") in edges
    assert ("metric_suggest", "__end__") not in edges
    assert _route_after_review({}) == END
    assert _route_after_review({"suggested_metrics": [{}], "blocked_candidates": [{}]}) == END


def test_discovery_caps_results_and_preserves_blocked_reports():
    proposals = [
        {
            "name": f"Metric {i}",
            "final_definition": definition(name=f"Metric {i}"),
            "review": MetricReview(status="pass", summary="Valid").model_dump(mode="json"),
        }
        for i in range(7)
    ]
    proposals += [
        {
            "name": "Gross margin",
            "final_definition": None,
            "review": MetricReview(status="rejected", summary="Thiếu giá vốn").model_dump(mode="json"),
        }
    ]
    result = reviewed_state(proposals, {"proposal_mode": "discovery"})
    assert len(result["suggested_metrics"]) == 5
    assert result["blocked_candidates"][0]["name"] == "Gross margin"
    assert all(i["review"]["status"] == "pass" for i in result["suggested_metrics"])


def test_dedupe_still_removes_existing_reviewed_metric():
    raw = definition()
    proposal = {
        "name": "Metric",
        "final_definition": raw,
        "review": MetricReview(status="pass", summary="Valid").model_dump(mode="json"),
    }
    result = reviewed_state(
        [proposal],
        {
            "existing_metrics": [
                {
                    "id": 5,
                    "name": raw["metric"]["name"],
                    "base_entity": "orders",
                    "function": "SUM",
                    "expression": "amount",
                    "filters": [],
                    "status": "approved",
                }
            ]
        },
    )
    assert result["suggested_metrics"] == [] and len(result["duplicate_notices"]) == 1


def test_legacy_save_preserves_human_selection_and_refuses_unreviewed_edits():
    first = {"final_definition": definition(), "review": {"status": "pass"}}
    second = {"final_definition": definition("amount * 2"), "review": {"status": "pass"}}
    state = {"reviewed_proposals": [first, second], "suggested_metrics": [{"definition": second["final_definition"]}]}
    assert _selected_review_evidence(state) == [second]
    state["suggested_metrics"] = [{"definition": definition("amount * 3")}]
    with pytest.raises(ValueError, match="HITL"):
        _selected_review_evidence(state)
