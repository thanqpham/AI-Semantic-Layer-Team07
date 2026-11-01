"""File preview uses schema permissions and never saves mappings."""

import pytest

from src.api.auth import create_access_token
from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel


@pytest.mark.asyncio
async def test_preview_requires_auth_and_does_not_write(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Import", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", data_type="TEXT", business_name="Status")
    async_session.add(column)
    await async_session.commit()
    url = f"/api/v1/semantic/{database.id}/columns/{column.id}/value-mappings/preview?file_type=csv"
    data = b"db_value,business_value\npaid,Paid\n"
    assert (await client.post(url, content=data)).status_code == 401
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    result = await client.post(url, content=data, headers=headers)
    assert result.status_code == 200
    assert result.json()["items"] == [{"db_value": "paid", "business_value": "Paid"}]
    await async_session.refresh(column)
    assert column.allowed_value_mappings is None
    result = await client.post(url, content=b"x" * 2_000_001, headers=headers)
    assert result.status_code == 413
    batch_url = f"/api/v1/semantic/{database.id}/value-mappings/preview?file_type=csv"
    batch = f"column_id,db_value,business_value\n{column.id},paid,Paid\n".encode()
    result = await client.post(batch_url, content=batch, headers=headers)
    assert result.status_code == 200
    assert result.json()["columns"][0]["column_id"] == column.id
    result = await client.post(
        batch_url, content=b"column_id,db_value,business_value\n999999,paid,Paid\n", headers=headers
    )
    assert result.status_code == 422
    await async_session.refresh(column)
    assert column.allowed_value_mappings is None
