"""Database overview review workflow."""

from unittest.mock import AsyncMock, patch

import pytest

from src.models.db import SemanticDatabaseModel
from tests.test_api.test_enrich_status_routes import auth_headers  # noqa: F401, F811
from tests.test_api.test_rbac_export_metric_request import _seed_workspace, _workspace_headers


@pytest.mark.asyncio
async def test_overview_review_preserves_published_value(async_session, client, auth_headers):  # noqa: F811
    """A new draft cannot replace the published text until approval."""
    async_session.add(
        SemanticDatabaseModel(id=741, created_by=1, display_name="Shop", db_type="sqlite", conn_url_enc="x")
    )
    await async_session.commit()
    url = "/api/v1/semantic/741/overview"
    with patch("src.api.overview_routes.generate_overview", new_callable=AsyncMock, return_value="Bán hàng"):
        result = await client.post(url + "/generate", json={"revision": 0}, headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["draft_description"] == "Bán hàng"
    result = await client.post(url + "/approve", json={"revision": 1}, headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["description"] == "Bán hàng"
    result = await client.put(url, json={"revision": 2, "draft_description": "Kho hàng"}, headers=auth_headers)
    assert result.json()["description"] == "Bán hàng"
    assert result.json()["draft_description"] == "Kho hàng"
    result = await client.post(url + "/approve", json={"revision": 2}, headers=auth_headers)
    assert result.status_code == 409


@pytest.mark.asyncio
async def test_member_sees_only_approved_overview(async_session, client):
    """Readers may view approved text but never another user's draft."""
    actor, org_id, db_id = await _seed_workspace(async_session, "member")
    database = await async_session.get(SemanticDatabaseModel, db_id)
    database.description = "Publié"
    database.draft_description = "Draft"
    database.ai_description = "AI draft"
    await async_session.commit()
    result = await client.get(f"/api/v1/semantic/{db_id}/overview", headers=_workspace_headers(actor, org_id))
    assert result.status_code == 200
    assert result.json()["description"] == "Publié"
    assert result.json()["draft_description"] is None
    assert result.json()["ai_description"] is None

@pytest.mark.asyncio
async def test_publish_overview_directly_checks_revision(async_session, client, auth_headers):  # noqa: F811
    async_session.add(SemanticDatabaseModel(id=743, created_by=1, display_name="Shop", db_type="sqlite", conn_url_enc="x", description="Before"))
    await async_session.commit()
    url = "/api/v1/semantic/743/overview/published"
    result = await client.put(url, json={"revision": 0, "draft_description": "After"}, headers=auth_headers)
    assert result.status_code == 200
    assert result.json()["description"] == "After"
    assert result.json()["draft_description"] is None
    assert (await client.put(url, json={"revision": 0, "draft_description": "Stale"}, headers=auth_headers)).status_code == 409
