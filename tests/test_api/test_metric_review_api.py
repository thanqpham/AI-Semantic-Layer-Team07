"""Exercise the actual review pipeline behind generate, save and re-review APIs."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from src.api.auth import create_access_token
from src.models.db import (
    MetricProposalModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
    UserModel,
)
from src.models.metric_review import MetricDraft, MetricDraftBatch
from src.services.metric_context import MetricContextResult, load_review_schema
from tests.metric_review_helpers import definition, reviewer_mock, scope_mock, seed_proposal


@pytest.fixture
async def setup_review(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Retail", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    proposal = await seed_proposal(async_session, database.id, 1)
    headers = {"Authorization": "Bearer " + create_access_token(await async_session.get(UserModel, 1))}
    await async_session.commit()
    return database.id, proposal, headers


@pytest.mark.parametrize("legacy_envelope", [False, True])
async def test_generate_persists_report_not_catalog_and_save_is_still_pending(
    client, async_session, setup_review, legacy_envelope
):
    db_id, _, headers = setup_review
    context = MetricContextResult(schema=await load_review_schema(async_session, db_id), diagnostic={"status": "ready"})
    batch = MetricDraftBatch(candidates=[MetricDraft(name="Doanh thu trước thuế", definition=definition())])
    candidates = [definition()] if legacy_envelope else [item.model_dump(mode="json") for item in batch.candidates]
    with (
        patch("src.api.routes.build_metric_context", AsyncMock(return_value=context)),
        patch(
            "src.agents.workflows.metric_proposal_workflow.generate_metric_drafts",
            AsyncMock(return_value=candidates),
        ),
        patch(
            "src.agents.workflows.metric_proposal_workflow.review_metric_batch",
            reviewer_mock(),
        ),
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/metrics/generate", headers=headers, json={"prompt": "Doanh thu trước thuế"}
        )
    assert response.status_code == 200, response.text
    item = response.json()["suggestions"][0]
    assert item["proposal_id"] and item["review"]["status"] == "pass" and "metric:" in item["yaml_preview"]
    assert await async_session.scalar(select(func.count()).select_from(SemanticMetricModel)) == 0
    saved = await client.post(
        f"/api/v1/semantic/{db_id}/metric",
        headers=headers,
        json={"source": "ai", "definition": item["definition"], "proposal_id": item["proposal_id"]},
    )
    assert saved.status_code == 201, saved.text
    assert saved.json()["status"] == "pending_approval"
    history = await client.get(f"/api/v1/semantic/{db_id}/metric/{saved.json()['metric_id']}/history", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["versions"][0]["review"]["status"] == "pass"


async def test_generate_average_variants_without_scope_column_clarification(client, async_session, setup_review):
    db_id, _, headers = setup_review
    table = await async_session.scalar(select(SemanticTableModel).where(SemanticTableModel.db_id == db_id))
    async_session.add_all(
        [
            SemanticColumnModel(
                table_id=table.id,
                column_name=name,
                data_type="NUMERIC",
                business_name=name,
                is_nullable=False,
                review_status="approved",
            )
            for name in ("price_before_tax", "price_after_tax", "total_discount_value")
        ]
    )
    await async_session.commit()
    variants = []
    for name, expression, variant_id in [
        ("Giá trị đơn hàng trung bình trước thuế", "price_before_tax", "order_average_pre_tax"),
        ("Giá trị đơn hàng trung bình sau thuế", "price_after_tax", "order_average_after_tax"),
        (
            "Giá trị đơn hàng trung bình sau thuế và giảm giá",
            "price_after_tax - total_discount_value",
            "order_average_after_tax_discount",
        ),
    ]:
        raw = definition(expression, name)
        raw["metric"]["formula"]["function"] = "AVG"
        variants.append(
            {"name": name, "status": "ready", "definition": raw, "knowledge_id": "aov", "variant_id": variant_id}
        )
    with (
        patch(
            "src.services.metric_context.invoke_metric_json",
            new=scope_mock({"table_names": ["orders"], "needs_clarification": True, "question": "Chọn cột giá nào?"}),
        ),
        patch("src.agents.workflows.metric_proposal_workflow.generate_metric_drafts", AsyncMock(return_value=variants)),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()) as review,
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/metrics/generate",
            headers=headers,
            json={"prompt": "Đề xuất giá trị trung bình trên mỗi đơn hàng"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["clarification"] is None
    assert len(response.json()["suggestions"]) == 3
    assert review.await_count == 1


async def test_generate_discovery_returns_supported_and_blocked_without_inventing_five(client, setup_review):
    db_id, _, headers = setup_review
    batch = MetricDraftBatch(
        candidates=[
            MetricDraft(
                name="Số đơn",
                definition={
                    "metric": {
                        "name": "Số đơn",
                        "base_entity": "orders",
                        "formula": {"function": "COUNT_DISTINCT", "expression": "id"},
                    }
                },
            ),
            MetricDraft(
                name="Biên lợi nhuận", knowledge_id="gross_margin", status="rejected", reason="Schema thiếu giá vốn"
            ),
        ]
    )
    with (
        patch(
            "src.agents.workflows.metric_proposal_workflow.generate_metric_drafts",
            AsyncMock(return_value=[item.model_dump(mode="json") for item in batch.candidates]),
        ),
        patch(
            "src.agents.workflows.metric_proposal_workflow.review_metric_batch",
            reviewer_mock(),
        ),
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/metrics/generate",
            headers=headers,
            json={"prompt": "Khám phá KPI", "proposal_mode": "discovery"},
        )
    assert response.status_code == 200, response.text
    assert len(response.json()["suggestions"]) == 1
    assert response.json()["blocked_candidates"][0]["review"]["status"] == "rejected"
    assert response.json()["blocked_candidates"][0]["proposal_id"]


async def test_re_review_endpoint_rejects_forged_scope_and_leaves_original_intact(client, async_session, setup_review):
    db_id, original, headers = setup_review
    original.context = {
        **original.context,
        "candidate": {"id": "candidate-stable", "knowledge_id": "net_sales", "group_id": "net_sales"},
    }
    with patch(
        "src.agents.workflows.metric_proposal_workflow.review_metric_batch",
        reviewer_mock(),
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/metric-proposals/{original.id}/review",
            headers=headers,
            json={"definition": definition("amount * 2")},
        )
    assert response.status_code == 200, response.text
    assert response.json()["proposal_id"] != original.id
    assert response.json()["candidate_id"] == "candidate-stable"
    assert response.json()["group_id"] == "net_sales"
    assert original.final_definition["metric"]["formula"]["expression"] == "amount"
    missing = await client.post(
        f"/api/v1/semantic/{db_id}/metric-proposals/nonexistent/review",
        headers=headers,
        json={"definition": definition()},
    )
    assert missing.status_code == 422
    assert await async_session.scalar(select(func.count()).select_from(MetricProposalModel)) == 2


async def test_ai_cannot_save_without_report_or_after_edit(client, setup_review):
    db_id, proposal, headers = setup_review
    for payload in [
        {"definition": definition(), "source": "ai"},
        {"definition": definition("amount * 2"), "source": "ai", "proposal_id": proposal.id},
    ]:
        response = await client.post(f"/api/v1/semantic/{db_id}/metric", headers=headers, json=payload)
        assert response.status_code == 422, response.text


async def test_partial_generate_returns_valid_sibling_and_typed_execution_error(client, setup_review):
    db_id, _, headers = setup_review
    build = AsyncMock(
        return_value=[{"name": "Doanh thu", "definition": definition()}, {"name": "Broken", "definition": None}]
    )

    async def repair(_context, items, _task_id):
        return [{"candidate_id": i["candidate_id"], "name": "Broken", "definition": None} for i in items]

    with (
        patch("src.agents.workflows.metric_proposal_workflow.generate_metric_drafts", build),
        patch("src.agents.workflows.metric_proposal_workflow.review_metric_batch", reviewer_mock()),
        patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", AsyncMock(side_effect=repair)),
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/metrics/generate",
            headers=headers,
            json={"prompt": "Khám phá KPI", "proposal_mode": "discovery"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["run_status"] == "partial"
    assert response.json()["suggestions"][0]["proposal_id"]
    blocked = response.json()["blocked_candidates"][0]
    assert blocked["review"]["execution_error"]["code"] == "INVALID_AGENT_OUTPUT"
    assert blocked["review"]["repair_count"] == 1


@pytest.fixture
async def mocked_review_pipeline(async_session, setup_review):
    db_id, _, _ = setup_review
    metadata = MetricContextResult(
        schema=await load_review_schema(async_session, db_id), diagnostic={"status": "ready"}
    )
    batch = MetricDraftBatch(candidates=[MetricDraft(name="Doanh thu trước thuế", definition=definition())])
    with (
        patch("src.api.routes.build_metric_context", AsyncMock(return_value=metadata)),
        patch(
            "src.agents.nodes.chat.orchestrator_node.orchestrator_node", AsyncMock(return_value={"intent": "metric_query"})
        ),
        patch(
            "src.agents.workflows.metric_proposal_workflow.generate_metric_drafts",
            AsyncMock(return_value=[item.model_dump(mode="json") for item in batch.candidates]),
        ) as generate,
        patch(
            "src.agents.workflows.metric_proposal_workflow.review_metric_batch",
            reviewer_mock(),
        ) as review,
    ):
        yield generate, review


async def test_chat_persists_report_context_and_replays_without_re_review(client, setup_review, mocked_review_pipeline):
    db_id, _, headers = setup_review
    generate, review = mocked_review_pipeline
    body = {"message": "Tạo metric doanh thu trước thuế", "client_message_id": "review-turn-1"}
    first = await client.post(f"/api/v1/semantic/{db_id}/chat", headers=headers, json=body)
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert first_data["suggestions"][0]["proposal_id"]
    replay = await client.post(f"/api/v1/semantic/{db_id}/chat", headers=headers, json=body)
    assert replay.json()["suggestions"] == first_data["suggestions"]
    assert generate.await_count == 1 and review.await_count == 1
    history = await client.get(f"/api/v1/semantic/{db_id}/chat/sessions/{first_data['session_id']}", headers=headers)
    report = history.json()["messages"][-1]["metadata_json"]["suggestions"][0]["review"]
    assert first_data["user_message_id"] in report["requirement"]
    assert "trước thuế" in report["requirement"]


async def test_partial_chat_status_survives_replay_and_history(client, setup_review, mocked_review_pipeline):
    db_id, _, headers = setup_review
    generate, _ = mocked_review_pipeline
    generate.return_value = [{"name": "Doanh thu", "definition": definition()}, {"name": "Broken", "definition": None}]

    async def repair(_context, items, _task_id):
        return [{"candidate_id": i["candidate_id"], "name": "Broken", "definition": None} for i in items]

    body = {"message": "Khám phá KPI", "proposal_mode": "discovery", "client_message_id": "partial-replay"}
    with patch("src.agents.nodes.metric.repair_node.repair_metric_drafts", AsyncMock(side_effect=repair)):
        response = await client.post(f"/api/v1/semantic/{db_id}/chat", headers=headers, json=body)
        assert response.status_code == 200, response.text
        replay = await client.post(f"/api/v1/semantic/{db_id}/chat", headers=headers, json=body)
    assert response.json()["run_status"] == replay.json()["run_status"] == "partial"
    assert replay.json()["execution_trace"]["status"] == "partial"
    assert generate.await_count == 1
    history = await client.get(
        f"/api/v1/semantic/{db_id}/chat/sessions/{response.json()['session_id']}", headers=headers
    )
    assert history.json()["messages"][-1]["metadata_json"]["run_status"] == "partial"
