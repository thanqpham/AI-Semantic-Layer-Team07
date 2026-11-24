"""API tests for PUT /semantic/{db_id}/schema/review/batch."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_access_token
from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel


def _headers(user: UserModel) -> dict[str, str]:
    """Build a bearer header for *user*."""
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _seed(session: AsyncSession) -> tuple[int, int, int]:
    """Seed a personal DB with one table and one column; return (db_id, table_id, column_id)."""
    sem_db = SemanticDatabaseModel(
        created_by=1, display_name="Batch DB", db_type="postgresql", conn_url_enc="encrypted", status="draft"
    )
    session.add(sem_db)
    await session.flush()
    table = SemanticTableModel(db_id=sem_db.id, table_name="orders", business_name="Đơn hàng", created_by=1)
    session.add(table)
    await session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="total", data_type="NUMERIC", business_name="Tổng")
    session.add(column)
    await session.commit()
    return sem_db.id, table.id, column.id


def _url(db_id: int) -> str:
    return f"/api/v1/semantic/{db_id}/schema/review/batch"


@pytest.mark.asyncio
async def test_batch_save_updates_rows(client: AsyncClient, async_session: AsyncSession):
    """One request saves both table and column edits."""
    user = await async_session.get(UserModel, 1)
    db_id, table_id, column_id = await _seed(async_session)

    response = await client.put(
        _url(db_id),
        json={
            "tables": [{"table_id": table_id, "business_name": "Đơn đặt hàng", "description": "Mô tả"}],
            "columns": [{"column_id": column_id, "business_name": "Tổng tiền"}],
        },
        headers=_headers(user),
    )

    assert response.status_code == 200
    assert response.json() == {"db_id": db_id, "updated_tables": 1, "updated_columns": 1}
    async_session.expire_all()
    column = await async_session.scalar(select(SemanticColumnModel).where(SemanticColumnModel.id == column_id))
    assert column.business_name == "Tổng tiền"


@pytest.mark.asyncio
async def test_batch_unknown_id_is_404_and_writes_nothing(client: AsyncClient, async_session: AsyncSession):
    """An unknown column ID rejects the batch; the valid table edit is not saved."""
    user = await async_session.get(UserModel, 1)
    db_id, table_id, _ = await _seed(async_session)

    response = await client.put(
        _url(db_id),
        json={
            "tables": [{"table_id": table_id, "business_name": "Đổi tên"}],
            "columns": [{"column_id": 99999, "business_name": "Ma"}],
        },
        headers=_headers(user),
    )

    assert response.status_code == 404
    async_session.expire_all()
    table = await async_session.get(SemanticTableModel, table_id)
    assert table.business_name == "Đơn hàng"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"tables": [{"table_id": 1, "business_name": "A"}, {"table_id": 1, "business_name": "B"}]},
        {"columns": [{"column_id": index, "business_name": "X"} for index in range(501)]},
        {"tables": [{"table_id": 1, "business_name": ""}]},
    ],
)
async def test_batch_invalid_body_is_422(client: AsyncClient, async_session: AsyncSession, body: dict):
    """Empty, duplicate, oversized or blank-name batches are rejected by validation."""
    user = await async_session.get(UserModel, 1)
    db_id, _, _ = await _seed(async_session)

    response = await client.put(_url(db_id), json=body, headers=_headers(user))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_batch_hides_other_users_database(client: AsyncClient, async_session: AsyncSession):
    """A different user cannot write to a personal database."""
    db_id, table_id, _ = await _seed(async_session)
    intruder = UserModel(
        id=2, email="intruder@company.com", username="intruder", full_name="I", hashed_password="h", status="active"
    )
    async_session.add(intruder)
    await async_session.commit()

    response = await client.put(
        _url(db_id),
        json={"tables": [{"table_id": table_id, "business_name": "Hack"}]},
        headers=_headers(intruder),
    )

    assert response.status_code == 404
