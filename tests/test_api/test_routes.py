"""Tests cho API routes — Flow 1 endpoints."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.api.auth import create_access_token
from src.models.db import OrganizationMemberModel, OrganizationModel, UserModel


def get_test_headers():
    """Generate auth headers with valid JWT token for test user."""
    dummy_user = UserModel(
        id=1,
        email="test@company.com",
        username="tester",
        full_name="Tester",
        hashed_password="hash",
        status="active",
    )
    token = create_access_token(dummy_user)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_health(client):
    """Health check endpoint phải trả về 200 và status=ok."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_agent_status(client):
    """Status endpoint phải trả về 200 và pipeline đúng."""
    headers = get_test_headers()
    response = await client.get("/api/v1/status", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "pipeline" in data


@pytest.mark.asyncio
async def test_generate_requires_db_id(client):
    """POST /semantic/generate thiếu db_id phải trả về 422 Validation Error."""
    headers = get_test_headers()
    response = await client.post("/api/v1/semantic/generate", json={}, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_export_invalid_format(client):
    """Export với format không hợp lệ phải trả về 400."""
    headers = get_test_headers()
    response = await client.get("/api/v1/semantic/1/export?format=csv", headers=headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_metric_requires_fields(client):
    """POST metric thiếu field phải trả về 422."""
    headers = get_test_headers()
    response = await client.post("/api/v1/semantic/1/metric", json={"name": "test"}, headers=headers)
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_metric_dimensions_not_found(client):
    """GET dimensions cho metric không tồn tại phải trả về 404."""
    headers = get_test_headers()
    response = await client.get("/api/v1/semantic/999/metric/999/dimensions", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_metric_filter_columns_not_found(client):
    """GET filter-columns cho metric không tồn tại phải trả về 404."""
    headers = get_test_headers()
    response = await client.get("/api/v1/semantic/999/metric/999/filter-columns", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_chat_session_requires_query(client):
    """Creating a chat without a first query must not create an empty session."""
    response = await client.post(
        "/api/v1/semantic/1/chat/sessions",
        json={},
        headers=get_test_headers(),
    )

    assert response.status_code == 400
    assert "query" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_restore_metric_not_found(client):
    """Restore metric không tồn tại phải trả về 404."""
    response = await client.post(
        "/api/v1/semantic/999/metric/999/restore",
        headers=get_test_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_metric_db_not_found(client):
    """Delete metric khi database không tồn tại phải trả về 404."""
    response = await client.delete(
        "/api/v1/semantic/999/metric/999",
        headers=get_test_headers(),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_connect_rejects_bad_tls_mode_returns_422(client):
    """POST /semantic/db/connect với tls_mode không hợp lệ phải trả về 422."""
    response = await client.post(
        "/api/v1/semantic/db/connect",
        json={
            "display_name": "TLS DB",
            "dialect": "postgresql",
            "conn_url": "postgresql://u:p@h/db",
            "tls_mode": "bogus",
        },
        headers=get_test_headers(),
    )
    assert response.status_code == 422
    assert "Unsupported TLS mode" in response.json()["detail"]


async def _seed_data_lead_workspace(async_session) -> int:
    """Create a Workspace where user 1 is data_lead (has can_manage_schema)."""
    org = OrganizationModel(name="TLS Workspace", slug="tls-workspace", created_by=1)
    async_session.add(org)
    await async_session.flush()
    async_session.add(OrganizationMemberModel(org_id=org.id, user_id=1, role="data_lead"))
    await async_session.commit()
    return org.id


@pytest.mark.asyncio
@patch("src.api.routes.create_live_target_db", new_callable=AsyncMock)
async def test_connect_tls_handshake_error_returns_prefixed_400(mock_create, client, async_session):
    """Lỗi TLS handshake khi connect phải trả về 400 với tiền tố tls_handshake_failed."""
    org_id = await _seed_data_lead_workspace(async_session)
    mock_create.side_effect = Exception("SSL error: certificate verify failed")
    response = await client.post(
        "/api/v1/semantic/db/connect",
        json={
            "display_name": "TLS DB",
            "dialect": "postgresql",
            "conn_url": "postgresql://u:p@h/db",
        },
        headers={**get_test_headers(), "X-Organization-ID": str(org_id)},
    )
    assert response.status_code == 400
    assert response.json()["detail"].startswith("tls_handshake_failed:")


@pytest.mark.asyncio
@patch("src.api.routes.create_live_target_db", new_callable=AsyncMock)
async def test_connect_strips_sslmode_from_url(mock_create, client, async_session):
    """Tham số TLS trong URL phải bị loại bỏ trước khi xuống service layer."""
    org_id = await _seed_data_lead_workspace(async_session)
    captured: dict[str, str] = {}

    async def _capture(db, user_id, display_name, dialect, conn_url, org_id=None, tls=None):
        captured["conn_url"] = conn_url
        now = datetime.now(UTC)
        return {
            "id": 1,
            "display_name": display_name,
            "dialect": dialect,
            "table_count": 0,
            "created_at": now,
            "updated_at": now,
            "raw_schema": {"dialect": dialect},
        }

    mock_create.side_effect = _capture
    response = await client.post(
        "/api/v1/semantic/db/connect",
        json={
            "display_name": "TLS DB",
            "dialect": "postgresql",
            "conn_url": "postgresql://u:p@h/db?sslmode=require",
        },
        headers={**get_test_headers(), "X-Organization-ID": str(org_id)},
    )
    assert response.status_code == 201
    assert "sslmode" not in captured["conn_url"]


@pytest.mark.asyncio
async def test_connect_malformed_url_returns_400_not_500(client, async_session):
    """conn_url sai định dạng (port không phải số) phải trả về 400, không 500."""
    org_id = await _seed_data_lead_workspace(async_session)
    response = await client.post(
        "/api/v1/semantic/db/connect",
        json={
            "display_name": "TLS DB",
            "dialect": "postgresql",
            "conn_url": "postgresql://u:p@h:notaport/db",
        },
        headers={**get_test_headers(), "X-Organization-ID": str(org_id)},
    )
    assert response.status_code == 400
