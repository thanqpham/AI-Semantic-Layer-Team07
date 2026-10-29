"""Structured metric outcome reasons and bounded aggregate trace summaries."""

from unittest.mock import patch

import pytest

from src.agents.workflows.metric_proposal_workflow import _candidate_trace_summary, run_metric_workflow
from src.models.metric_review import MetricReview
from src.services.metric_review import _enforce_review, _missing_ratio_review
from tests.metric_review_helpers import context, definition, reviewer_mock


def test_unresolved_assumption_has_a_structured_reason_code():
    review = MetricReview(status="pass", summary="Valid")
    result = _enforce_review(
        review,
        None,
        {"assumptions": ["Customer cohort is unclear"]},
        {"criteria": {"tax_basis": "excludes_tax"}},
    )
    assert result.reason_code == "UNRESOLVED_ASSUMPTION"


def test_deterministic_ratio_gate_has_a_structured_reason_code():
    assert _missing_ratio_review().reason_code == "MISSING_RATIO"


@pytest.mark.asyncio
async def test_reviewer_issue_code_keeps_reviewer_provenance():
    reviewer = reviewer_mock(
        "needs_revision",
        issues=[{
            "code": "INVALID_DEFINITION", "message": "Revise it", "evidence": "Definition",
            "action": "Update it",
        }],
    )
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer):
        result = await run_metric_workflow(context(), drafts=[{
            "name": "Metric", "status": "ready", "definition": definition(),
        }], allow_repair=False)
    assert result[0]["review"]["reason_code"] == "REVIEWER_FINDING"


def test_candidate_trace_summary_counts_status_and_reason_without_text():
    evidence = [
        {"candidate_id": "a", "review": {"status": "pass", "reason_code": None}},
        {"candidate_id": "b", "review": {"status": "needs_clarification", "reason_code": "UNRESOLVED_ASSUMPTION"}},
        {"candidate_id": "c", "review": {"status": "error", "reason_code": "INVALID_AGENT_OUTPUT"}},
    ]
    summary = _candidate_trace_summary(evidence)
    assert summary["candidate_count"] == 3
    assert summary["pass_count"] == 1
    assert summary["needs_clarification_count"] == 1
    assert summary["error_count"] == 1
    assert summary["reason_unresolved_assumption_count"] == 1
    assert summary["reason_invalid_agent_output_count"] == 1
