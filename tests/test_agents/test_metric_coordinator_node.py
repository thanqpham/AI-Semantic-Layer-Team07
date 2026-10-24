"""Draft generation and mandatory post-generation review graph tests."""

from unittest.mock import AsyncMock, patch

import pytest

from src.agents.graphs.chat_graph import build_chat_graph
from src.agents.graphs.semantic_layer_graph import END, _route_after_review
from src.agents.nodes.metric.coordinator_node import coordinator_node
from src.agents.nodes.metric.metric_review_node import metric_review_node, reviewed_state
from src.agents.nodes.schema.save_node import _selected_review_evidence
from src.agents.roles.metric_designer_agent import generate_metric_drafts
from src.agents.workflows.metric_proposal_workflow import _graph
from src.models.metric_review import MetricBuildBatch, MetricReview
from tests.metric_review_helpers import context, definition, reviewer_mock, schema


async def test_empty_state_returns_error():
    assert "error" in await coordinator_node({})


async def test_coordinator_returns_only_reviewed_suggestions():
    draft = {"name": "Doanh thu", "definition": definition()}
    with (
        patch("src.agents.workflows.metric_proposal_workflow.generate_metric_drafts", AsyncMock(return_value=[draft])),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()),
    ):
        result = await coordinator_node({"enriched_schema": schema(), "user_message": "Doanh thu"})
    assert result["suggested_metrics"][0]["review"]["status"] == "pass"
    assert result["run_status"] == "completed"


async def test_generation_does_not_discard_invalid_reference_before_repair():
    batch = MetricBuildBatch(task_id="test-task", candidates=[{"name": "Metric", "definition": definition("missing")}])
    with patch("src.agents.roles.metric_designer_agent.invoke_metric_json", AsyncMock(return_value=batch)):
        drafts = await generate_metric_drafts(context(), "test-task")
    assert drafts[0]["definition"]["metric"]["formula"]["expression"] == "missing"


async def test_generation_error_cannot_bypass_reviewer():
    with patch("src.agents.workflows.metric_proposal_workflow.generate_metric_drafts", AsyncMock(side_effect=RuntimeError)):
        initial = await coordinator_node({"enriched_schema": schema()})
    result = {**initial, **await metric_review_node(initial)}
    assert result["blocked_candidates"][0]["review"]["status"] == "error"
    assert result["suggested_metrics"] == [] and result["suggestion_action"] is None


def test_chat_graph_has_mandatory_review_edge_and_legacy_blocks_unreviewed_state():
    graph = build_chat_graph().get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("orchestrator", "metric_coordinator") in edges
    workflow_edges = {(edge.source, edge.target) for edge in _graph().get_graph().edges}
    assert {("build", "validate"), ("validate", "dedupe"), ("dedupe", "review"), ("repair", "validate")} <= workflow_edges
    assert _route_after_review({}) == END
    assert _route_after_review({"suggested_metrics": [{}], "blocked_candidates": [{}]}) == END
    assert (
        _route_after_review({"suggested_metrics": [{"review": {"status": "pass"}}], "blocked_candidates": [{}]})
        == "save"
    )


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


def test_passing_variant_does_not_pause_for_another_variant_clarification():
    passed = {
        "name": "Giá trị đơn hàng trước thuế",
        "final_definition": definition(),
        "review": MetricReview(status="pass", summary="Đạt").model_dump(mode="json"),
    }
    blocked = {
        "name": "Giá trị đơn hàng sau thuế",
        "final_definition": None,
        "review": MetricReview(
            status="needs_clarification",
            summary="Thiếu ý nghĩa cột thuế",
            clarification="Cần xác nhận ý nghĩa cột thuế",
        ).model_dump(mode="json"),
    }
    result = reviewed_state([passed, blocked], {})
    assert len(result["suggested_metrics"]) == 1
    assert result["blocked_candidates"][0]["review"]["status"] == "needs_clarification"
    assert "clarification" not in result


def test_projection_cannot_replace_a_reviewed_metric_without_duplicate_evidence():
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
    assert len(result["suggested_metrics"]) == 1 and result["duplicate_notices"] == []


def test_legacy_save_preserves_human_selection_and_refuses_unreviewed_edits():
    first = {"final_definition": definition(), "review": {"status": "pass"}}
    second = {"final_definition": definition("amount * 2"), "review": {"status": "pass"}}
    state = {"reviewed_proposals": [first, second], "suggested_metrics": [{"definition": second["final_definition"]}]}
    assert _selected_review_evidence(state) == [second]
    state["suggested_metrics"] = [{"definition": definition("amount * 3")}]
    with pytest.raises(ValueError, match="HITL"):
        _selected_review_evidence(state)
