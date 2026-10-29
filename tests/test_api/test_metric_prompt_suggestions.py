"""API tests for authorized metric prompt suggestions."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import create_access_token
from src.models.db import (
    ImportedSchemaModel,
    LiveTargetDbModel,
    OrganizationMemberModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
    UserModel,
)
from src.services.organization_service import create_organization


def _headers(user: UserModel) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


async def _seed_live_database(db: AsyncSession, owner_id: int = 1) -> SemanticDatabaseModel:
    semantic_db = SemanticDatabaseModel(
        created_by=owner_id,
        display_name="Private database",
        db_type="sqlite",
        conn_url_enc="encrypted-url",
        schema_fingerprint="fingerprint",
        sync_status="synced",
    )
    db.add(semantic_db)
    await db.flush()
    await _seed_live_target(db, semantic_db.id, owner_id)
    await _seed_order_table(db, semantic_db.id, owner_id)
    return semantic_db


async def _seed_live_target(db: AsyncSession, db_id: int, owner_id: int) -> None:
    db.add(
        LiveTargetDbModel(
            created_by=owner_id,
            display_name="Private database",
            dialect="sqlite",
            conn_url_enc="encrypted-url",
            schema_metadata={},
            semantic_db_id=db_id,
        )
    )


async def _seed_order_table(db: AsyncSession, db_id: int, owner_id: int) -> None:
    table = SemanticTableModel(db_id=db_id, table_name="orders", business_name="Orders", created_by=owner_id)
    db.add(table)
    await db.flush()
    db.add_all(
        [
            SemanticColumnModel(
                table_id=table.id,
                column_name="id",
                data_type="INTEGER",
                business_name="ID",
                is_primary_key=True,
            ),
            SemanticColumnModel(
                table_id=table.id,
                column_name="amount",
                data_type="NUMERIC",
                business_name="Amount",
            ),
        ]
    )
    await db.flush()


@pytest.mark.asyncio
async def test_live_owner_gets_only_public_suggestion_fields(client, async_session: AsyncSession):
    user = await async_session.get(UserModel, 1)
    semantic_db = await _seed_live_database(async_session)

    response = await client.get(f"/api/v1/semantic/{semantic_db.id}/metric-prompt-suggestions", headers=_headers(user))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items"}
    assert body["items"]
    assert all({"id", "title", "prompt"} <= set(item) <= {"id", "title", "prompt", "icon"} for item in body["items"])


@pytest.mark.asyncio
async def test_organization_member_can_view_suggestions_and_foreign_database_is_hidden(
    client, async_session: AsyncSession
):
    member = await async_session.get(UserModel, 1)
    owner = UserModel(
        id=2,
        email="owner@example.com",
        username="owner",
        full_name="Owner",
        hashed_password="hash",
        status="active",
    )
    async_session.add(owner)
    await async_session.flush()
    organization = await create_organization(async_session, owner.id, "Shared", "shared")
    async_session.add(OrganizationMemberModel(org_id=organization.id, user_id=member.id, role="member"))
    shared = await _seed_live_database(async_session, owner.id)
    shared.org_id = organization.id

    visible = await client.get(f"/api/v1/semantic/{shared.id}/metric-prompt-suggestions", headers=_headers(member))
    private = await _seed_live_database(async_session, owner.id)
    private.org_id = None
    inaccessible = await client.get(
        f"/api/v1/semantic/{private.id}/metric-prompt-suggestions", headers=_headers(member)
    )

    assert visible.status_code == 200
    assert inaccessible.status_code == 404


@pytest.mark.asyncio
async def test_sql_dump_returns_empty_items(client, async_session: AsyncSession):
    user = await async_session.get(UserModel, 1)
    semantic_db = SemanticDatabaseModel(
        created_by=user.id,
        display_name="Dump",
        db_type="sqlite",
        conn_url_enc="encrypted-url",
        schema_fingerprint="fingerprint",
    )
    async_session.add(semantic_db)
    await async_session.flush()
    async_session.add(
        ImportedSchemaModel(
            created_by=user.id,
            display_name="Dump",
            dialect="sqlite",
            schema_metadata={},
            semantic_db_id=semantic_db.id,
        )
    )
    response = await client.get(f"/api/v1/semantic/{semantic_db.id}/metric-prompt-suggestions", headers=_headers(user))

    assert response.status_code == 200
    assert response.json() == {"items": []}


@pytest.mark.asyncio
async def test_live_target_returns_no_suggestions_when_catalog_says_query_unsupported(
    client, async_session: AsyncSession, monkeypatch
):
    user = await async_session.get(UserModel, 1)
    semantic_db = await _seed_live_database(async_session)

    async def unsupported_catalog_source(_db, _db_id):
        return "sql_dump"

    monkeypatch.setattr("src.api.routes._catalog_source_type", unsupported_catalog_source)
    response = await client.get(f"/api/v1/semantic/{semantic_db.id}/metric-prompt-suggestions", headers=_headers(user))

    assert response.status_code == 200
    assert response.json() == {"items": []}
