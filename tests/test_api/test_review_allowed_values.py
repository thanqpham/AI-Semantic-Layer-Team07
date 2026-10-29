"""Regression tests for explicitly reviewed column values."""

from types import SimpleNamespace

import pytest

from src.api.auth import create_access_token
from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel
from src.services.semantic_service import _upsert_semantic_column


@pytest.mark.asyncio
async def test_edit_allowed_values_preserves_omitted_and_clears_null(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Review", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Đơn hàng", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", data_type="TEXT", business_name="Trạng thái")
    async_session.add(column)
    await async_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    url = f"/api/v1/semantic/{database.id}/column/orders/status"
    body = {"business_name": "Trạng thái", "description": ""}
    for payload, expected in [({"allowed_values": ["completed", "cancelled"]}, ["completed", "cancelled"]),
                              ({}, ["completed", "cancelled"]), ({"allowed_values": None}, None)]:
        response = await client.put(url, headers=headers, json={**body, **payload})
        assert response.status_code == 200, response.text
        await async_session.refresh(column)
        assert column.allowed_values == expected
    review = await client.get(f"/api/v1/semantic/{database.id}/schema/review", headers=headers)
    assert review.status_code == 200
    assert review.json()["tables"][0]["columns"][0]["allowed_values"] is None


@pytest.mark.asyncio
async def test_refresh_without_enum_preserves_reviewed_values(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="Review", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Đơn hàng", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", data_type="TEXT", business_name="Trạng thái",
                                 allowed_values=["completed"])
    async_session.add(column)
    await async_session.flush()
    metadata = SimpleNamespace(column_name=SimpleNamespace(raw_name="status"), data_type="TEXT", primary_key=False,
                               nullable=True, sample_values=None)
    await _upsert_semantic_column(async_session, table.id, metadata, {}, None)
    assert column.allowed_values == ["completed"]
