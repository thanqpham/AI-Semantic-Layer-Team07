"""Exercise the actual review pipeline behind generate, save and re-review APIs."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from src.api.auth import create_access_token
from src.models.db import MetricProposalModel, SemanticDatabaseModel, SemanticMetricModel, UserModel
from src.models.metric_review import MetricDraft, MetricDraftBatch, MetricReview
from src.services.metric_context import MetricContextResult, load_review_schema
from tests.metric_review_helpers import definition, seed_proposal


@pytest.fixture
async def setup_review(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Retail", db_type="sqlite", conn_url_enc="enc")
    async_session.add(database)
    await async_session.flush()
    proposal = await seed_proposal(async_session, database.id, 1)
    headers = {"Authorization": "Bearer " + create_access_token(await async_session.get(UserModel, 1))}
    await async_session.commit()
    return database.id, proposal, headers


async def test_generate_persists_report_not_catalog_and_save_is_still_pending(client, async_session, setup_review):
    db_id, _, headers = setup_review
    context = MetricContextResult(schema=await load_review_schema(async_session, db_id), diagnostic={"status": "ready"})
    batch = MetricDraftBatch(candidates=[MetricDraft(name="Doanh thu trước thuế", definition=definition())])
    with (
        patch("src.api.routes.build_metric_context", AsyncMock(return_value=context)),
        patch("src.services.metric_proposal_generation.invoke_metric_json", AsyncMock(return_value=batch)),
        patch(
            "src.services.metric_review.invoke_metric_json",
            AsyncMock(return_value=MetricReview(status="pass", summary="Khớp yêu cầu")),
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
        patch("src.services.metric_proposal_generation.invoke_metric_json", AsyncMock(return_value=batch)),
        patch(
            "src.services.metric_review.invoke_metric_json",
            AsyncMock(return_value=MetricReview(status="pass", summary="Có khóa đơn")),
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
    with patch(
        "src.services.metric_review.invoke_metric_json",
        AsyncMock(return_value=MetricReview(status="pass", summary="Bản sửa đạt")),
    ):
        response = await client.post(
            f"/api/v1/semantic/{db_id}/metric-proposals/{original.id}/review",
            headers=headers,
            json={"definition": definition("amount * 2")},
        )
    assert response.status_code == 200, response.text
    assert response.json()["proposal_id"] != original.id
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
            "src.agents.nodes.orchestrator_node.orchestrator_node", AsyncMock(return_value={"intent": "metric_query"})
        ),
        patch("src.services.metric_proposal_generation.invoke_metric_json", AsyncMock(return_value=batch)) as generate,
        patch(
            "src.services.metric_review.invoke_metric_json",
            AsyncMock(return_value=MetricReview(status="pass", summary="Đúng yêu cầu")),
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
