"""Durable AI-review gates, freshness and append-only re-review tests."""

from unittest.mock import patch

import pytest
from sqlalchemy import select

from src.config import get_settings
from src.models.db import MetricProposalModel, SemanticColumnModel, SemanticDatabaseModel, SemanticMetricModel
from src.models.metric_definition import MetricDefinition
from src.services.metric_context import load_review_schema
from src.services.metric_knowledge import metric_knowledge
from src.services.metric_proposals import (
    link_saved_proposal,
    persist_reviewed_state,
    re_review_proposal,
    require_passing_proposal,
    review_schema_fingerprint,
)
from src.services.metric_service import create_metric
from tests.metric_review_helpers import definition, reviewer_mock, schema, seed_proposal


@pytest.fixture
async def proposal(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Review DB", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    return await seed_proposal(async_session, database.id, 1)


async def test_ai_create_requires_server_owned_passing_proof(async_session, proposal):
    with pytest.raises(ValueError, match="proposal"):
        await create_metric(async_session, proposal.db_id, {"source": "ai", "definition": definition()}, 1)
    metric = await create_metric(
        async_session, proposal.db_id, {"source": "ai", "definition": definition(), "proposal_id": proposal.id}, 1
    )
    assert metric.status == "pending_approval"
    assert proposal.metric_id == metric.id and proposal.metric_version == 1
    assert metric.definition["metric"]["status"] != "approved"


@pytest.mark.parametrize(
    "case", ["foreign_db", "foreign_user", "forged", "changed", "failed", "consumed", "deleted_metric"]
)
async def test_submission_rejects_invalid_proof(async_session, proposal, case):
    db_id, user_id, proposal_id = proposal.db_id, 1, proposal.id
    raw = MetricDefinition.model_validate(proposal.final_definition)
    if case == "foreign_db":
        db_id += 1
    elif case == "foreign_user":
        user_id = 2
    elif case == "forged":
        proposal_id = "nonexistent"
    elif case == "changed":
        raw.metric.formula.expression = "amount * 2"
    elif case == "failed":
        proposal.status = "error"
    elif case == "consumed":
        proposal.metric_id = 100
    elif case == "deleted_metric":
        proposal.metric_version = 1
    with pytest.raises(ValueError):
        await require_passing_proposal(async_session, db_id, proposal_id, user_id, raw)


@pytest.mark.parametrize(
    "attribute,value",
    [("description", "Now tax-inclusive"), ("data_type", "TEXT"), ("is_nullable", True), ("allowed_values", [1, 2])],
)
async def test_metadata_semantics_and_constraints_invalidate_review(async_session, proposal, attribute, value):
    column = await async_session.scalar(select(SemanticColumnModel).where(SemanticColumnModel.column_name == "amount"))
    if attribute == "is_nullable":
        column.is_nullable = False
        proposal.context = {**proposal.context, "schema": await load_review_schema(async_session, proposal.db_id)}
        proposal.schema_fingerprint = review_schema_fingerprint(proposal.context["schema"])
    elif attribute == "allowed_values":
        column.review_status = "approved"
        proposal.context = {**proposal.context, "schema": await load_review_schema(async_session, proposal.db_id)}
        proposal.schema_fingerprint = review_schema_fingerprint(proposal.context["schema"])
    setattr(column, attribute, value)
    await async_session.flush()
    with pytest.raises(ValueError, match="Metadata"):
        await require_passing_proposal(
            async_session, proposal.db_id, proposal.id, 1, MetricDefinition.model_validate(proposal.final_definition)
        )


async def test_re_review_creates_new_snapshot_and_keeps_original_requirements(async_session, proposal):
    original_context = proposal.context
    original_definition = proposal.final_definition
    edited = MetricDefinition.model_validate(definition("amount * 2"))
    with patch(
        "src.agents.workflows.metric_proposal_workflow.review_metric_batch",
        reviewer_mock(),
    ):
        updated = await re_review_proposal(async_session, proposal, 1, edited)
    assert updated.id != proposal.id and updated.parent_id == proposal.id
    assert updated.context["requirement"] == original_context["requirement"]
    assert updated.final_definition["metric"]["formula"]["expression"] == "amount * 2"
    assert proposal.final_definition == original_definition
    assert len(list((await async_session.scalars(select(MetricProposalModel))).all())) == 2


@pytest.mark.parametrize("mode", ["requested", "discovery"])
async def test_re_review_refreshes_knowledge_without_rewriting_original_evidence(async_session, proposal, mode):
    stale = {"metrics": [], "sources": [], "outdated": True}
    proposal.context = {
        **proposal.context,
        "knowledge": stale,
        "proposal_mode": mode,
        "candidate": {"knowledge_id": "net_sales", "variant_id": "merchandise_net_sales"},
    }
    expected = metric_knowledge(proposal.context["requirement"], mode == "discovery")
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review:
        updated = await re_review_proposal(async_session, proposal, 1, MetricDefinition.model_validate(definition()))
    assert review.call_args.args[0]["knowledge"] == expected
    assert updated.context["knowledge"] == expected
    assert updated.context["requirement"] == proposal.context["requirement"]
    assert proposal.context["knowledge"] == stale


async def test_save_rechecks_duplicate_created_after_review(async_session, proposal):
    await create_metric(async_session, proposal.db_id, {"source": "manual", "definition": definition()}, 1)
    with pytest.raises(ValueError, match="đã tồn tại"):
        await require_passing_proposal(
            async_session, proposal.db_id, proposal.id, 1, MetricDefinition.model_validate(proposal.final_definition)
        )


async def test_re_review_preserves_variant_identity_and_its_source(async_session, proposal):
    proposal.context = {
        **proposal.context,
        "candidate": {
            "id": "original",
            "name": "Doanh thu trước thuế",
            "knowledge_id": "net_sales",
            "variant_id": "merchandise_net_sales",
            "criteria": {"order_status": "all_statuses"},
            "group_id": "net_sales",
        },
    }
    with patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()):
        updated = await re_review_proposal(async_session, proposal, 1, MetricDefinition.model_validate(definition()))
    assert updated.parent_id == proposal.id
    assert updated.review["variant_id"] == "merchandise_net_sales"
    assert updated.review["criteria"]["order_status"] == "all_statuses"
    assert updated.context["candidate"]["id"] == "original"
    assert updated.context["candidate"]["group_id"] == "net_sales"
    assert updated.context["candidate"]["id"] != updated.id
    assert [source["id"] for source in updated.review["sources"]] == ["woocommerce_analytics"]


async def test_persist_reviewed_state_matches_duplicate_names_by_candidate_id(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Review DB", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    base = await seed_proposal(async_session, database.id, 1)
    evidence = []
    for key, expression in (("candidate-a", "amount"), ("candidate-b", "amount * 2")):
        evidence.append({
            "name": "Same", "context": {**base.context, "candidate": {"id": key}},
            "original_definition": base.original_definition,
            "final_definition": definition(expression, "Same"), "review": base.review,
        })
    state = {
        "reviewed_proposals": evidence,
        "suggested_metrics": [
            {"candidate_id": "candidate-b", "definition": evidence[1]["final_definition"]},
            {"candidate_id": "candidate-a", "definition": evidence[0]["final_definition"]},
        ],
        "blocked_candidates": [],
    }
    await persist_reviewed_state(async_session, database.id, 1, state)
    assert state["suggested_metrics"][0]["proposal_id"] != state["suggested_metrics"][1]["proposal_id"]
    by_id = {item["candidate_id"]: item["proposal_id"] for item in state["suggested_metrics"]}
    proposals = (await async_session.scalars(select(MetricProposalModel))).all()
    assert {row.id: row.context["candidate"].get("id") for row in proposals if row.id in by_id.values()} == {
        by_id["candidate-a"]: "candidate-a", by_id["candidate-b"]: "candidate-b"
    }


async def test_re_review_with_knowledge_disabled_keeps_the_original_snapshot(async_session, proposal):
    proposal.context = {
        **proposal.context,
        "candidate": {
            "knowledge_id": "net_sales",
            "variant_id": "merchandise_net_sales",
            "criteria": {"tax_basis": "excludes_tax"},
        },
    }
    original = proposal.context
    with (
        patch.object(get_settings(), "metric_knowledge_enabled", False),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()),
    ):
        updated = await re_review_proposal(async_session, proposal, 1, MetricDefinition.model_validate(definition()))
    assert updated.status == "pass"
    assert updated.context["knowledge"] == {"metrics": [], "sources": []}
    assert updated.context["candidate"]["knowledge_id"] is None
    assert updated.review["sources"] == []
    assert updated.review["criteria"]["tax_basis"] == "excludes_tax"
    assert proposal.context == original


def test_fingerprint_is_order_independent_but_tracks_relationships():
    first = schema()
    second = {
        "tables": [{**first["tables"][0], "columns": list(reversed(first["tables"][0]["columns"]))}],
        "relationships": [],
    }
    assert review_schema_fingerprint(first) == review_schema_fingerprint(second)
    second["relationships"] = [{"join_condition": "a.id=b.id", "relationship_type": "one_to_many"}]
    assert review_schema_fingerprint(first) != review_schema_fingerprint(second)


async def test_concurrent_consumption_cannot_overwrite_saved_metric(async_session, proposal):
    metric = await create_metric(async_session, proposal.db_id, {"source": "manual", "definition": definition()}, 1)
    await link_saved_proposal(async_session, proposal, metric.id, 1)
    with pytest.raises(ValueError, match="yêu cầu khác"):
        await link_saved_proposal(async_session, proposal, metric.id, 2)
    assert proposal.metric_version == 1


async def test_manual_create_remains_available_without_ai_review(async_session, proposal):
    metric = await create_metric(async_session, proposal.db_id, {"source": "manual", "definition": definition()}, 1)
    assert metric.source == "manual"
    assert await async_session.get(SemanticMetricModel, metric.id) is metric
