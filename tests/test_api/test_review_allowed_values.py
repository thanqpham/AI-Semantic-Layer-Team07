"""Regression tests for explicitly reviewed column values."""

from types import SimpleNamespace

import pytest

from src.api.auth import create_access_token
from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel
from src.services.export_service import _dimension_to_dict
from src.services.metric_review_validation import _validate_filter_value
from src.services.schema_review_service import _approve_row, apply_ai_proposal
from src.services.semantic_service import _upsert_semantic_column


def test_approving_column_does_not_approve_legacy_values():
    column = SemanticColumnModel(
        column_name="status",
        data_type="TEXT",
        business_name="Status",
        review_status="pending_review",
        allowed_values=["old"],
        allowed_values_complete=True,
    )
    assert _dimension_to_dict(column)["allowed_values"] is None
    _validate_filter_value(column, "other")
    assert _approve_row(column, 1)
    assert column.allowed_values is None
    assert column.allowed_values_complete is False
    assert column.allowed_value_mappings == [
        {"db_value": "old", "business_value": "", "source": "legacy", "status": "pending"}
    ]


def test_ai_proposal_preserves_approved_legacy_values():
    column = SemanticColumnModel(
        column_name="status",
        data_type="TEXT",
        business_name="Status",
        description="Old",
        review_status="approved",
        allowed_values=["paid"],
        allowed_values_complete=True,
    )
    apply_ai_proposal(column, "Status", "New")
    assert column.review_status == "pending_review"
    assert column.allowed_value_mappings[0]["status"] == "approved"
    _approve_row(column, 1)
    assert column.allowed_values == ["paid"] and column.allowed_values_complete is True


@pytest.mark.asyncio
async def test_edit_and_reapprove_column_preserves_approved_legacy_values(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Legacy", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(
        table_id=table.id,
        column_name="status",
        data_type="TEXT",
        business_name="Status",
        review_status="approved",
        allowed_values=["paid"],
        allowed_values_complete=True,
    )
    async_session.add(column)
    await async_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    response = await client.put(
        f"/api/v1/semantic/{database.id}/column/orders/status",
        headers=headers,
        json={"business_name": "Trạng thái", "description": ""},
    )
    assert response.status_code == 200
    response = await client.post(
        f"/api/v1/semantic/{database.id}/schema/approve", headers=headers, json={"table_ids": [table.id]}
    )
    assert response.status_code == 200
    await async_session.refresh(column)
    assert column.allowed_values == ["paid"] and column.allowed_values_complete is True
    assert column.allowed_value_mappings[0]["status"] == "approved"


@pytest.mark.asyncio
async def test_legacy_column_update_rejects_value_changes(client, async_session):
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
    response = await client.put(url, headers=headers, json={**body, "allowed_values": ["completed"]})
    assert response.status_code == 409
    response = await client.put(url, headers=headers, json={**body, "allowed_values": None})
    assert response.status_code == 200
    await async_session.refresh(column)
    assert column.allowed_values is None
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
    column = SemanticColumnModel(
        table_id=table.id,
        column_name="status",
        data_type="TEXT",
        business_name="Trạng thái",
        allowed_values=["completed"],
    )
    async_session.add(column)
    await async_session.flush()
    metadata = SimpleNamespace(
        column_name=SimpleNamespace(raw_name="status"),
        data_type="TEXT",
        primary_key=False,
        nullable=True,
        sample_values=("other",),
    )
    await _upsert_semantic_column(async_session, table.id, metadata, {}, None)
    assert column.allowed_values == ["completed"]


@pytest.mark.asyncio
async def test_value_mappings_require_review_before_legacy_use(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Mappings", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", data_type="TEXT", business_name="Status")
    async_session.add(column)
    await async_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    url = f"/api/v1/semantic/{database.id}/columns/{column.id}/value-mappings"
    initial = (await client.get(url, headers=headers)).json()

    response = await client.put(
        url,
        headers=headers,
        json={
            "items": [{"db_value": "paid", "business_value": "Đã thanh toán"}],
            "complete": False,
            "version": initial["version"],
        },
    )

    assert response.status_code == 200, response.text
    await async_session.refresh(column)
    assert column.allowed_values is None
    assert column.allowed_value_mappings[0]["status"] == "pending"
    saved_version = response.json()["version"]
    stale = await client.post(
        f"{url}/review",
        headers=headers,
        json={"db_values": ["paid"], "action": "approve", "version": initial["version"]},
    )
    assert stale.status_code == 409
    response = await client.post(
        f"{url}/review", headers=headers, json={"db_values": ["paid"], "action": "approve", "version": saved_version}
    )
    assert response.status_code == 200, response.text
    await async_session.refresh(column)
    assert column.allowed_values == ["paid"]
    assert column.allowed_value_mappings[0]["reviewed_by"] == user.id


@pytest.mark.asyncio
async def test_legacy_values_survive_mapping_save_and_pending_disables_completeness(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Legacy", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(
        table_id=table.id,
        column_name="status",
        data_type="TEXT",
        business_name="Status",
        allowed_values=["old"],
        allowed_values_complete=True,
        review_status="approved",
    )
    async_session.add(column)
    await async_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    url = f"/api/v1/semantic/{database.id}/columns/{column.id}/value-mappings"
    response = await client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.json()["items"] == [
        {"db_value": "old", "business_value": "", "source": "legacy", "status": "approved"}
    ]
    initial_version = response.json()["version"]
    column.review_status = "pending_review"
    await async_session.commit()
    stale = await client.put(url, headers=headers, json={"items": [], "complete": False, "version": initial_version})
    assert stale.status_code == 409
    column.review_status = "approved"
    await async_session.commit()
    initial_version = (await client.get(url, headers=headers)).json()["version"]
    response = await client.put(
        url,
        headers=headers,
        json={
            "items": [
                {"db_value": "old", "business_value": ""},
                {"db_value": "new", "business_value": "Mới"},
            ],
            "complete": True,
            "version": initial_version,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["complete"] is False
    await async_session.refresh(column)
    assert column.allowed_values == ["old"]
    assert column.allowed_values_complete is False
    stale = await client.put(url, headers=headers, json={"items": [], "complete": False, "version": initial_version})
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_approve_values_and_scope_atomically(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="Mappings", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders", created_by=1)
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", data_type="TEXT", business_name="Status")
    async_session.add(column)
    await async_session.commit()
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    url = f"/api/v1/semantic/{database.id}/columns/{column.id}/value-mappings"
    version = (await client.get(url, headers=headers)).json()["version"]
    payload = {"db_values": [], "action": "approve", "version": version,
               "items": [{"db_value": "paid", "business_value": "Paid"}], "complete": True}
    invalid = await client.post(f"{url}/review", headers=headers, json={**payload, "complete": None})
    assert invalid.status_code == 422
    response = await client.post(f"{url}/review", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    await async_session.refresh(column)
    assert column.allowed_values == ["paid"]
    assert column.allowed_values_complete is True
    assert column.allowed_value_mappings[0]["status"] == "approved"
    stale = await client.post(f"{url}/review", headers=headers, json=payload)
    assert stale.status_code == 409
