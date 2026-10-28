"""Authorization, provenance and stale review of categorical suggestions."""

from unittest.mock import Mock

import pytest

from src.api.auth import create_access_token
from src.models.db import LiveTargetDbModel, SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel, UserModel
from src.models.db_categorical_proposals import ColumnValueProposalModel
from src.services.categorical_proposals import proposal_fingerprint


@pytest.mark.asyncio
async def test_review_promotes_observed_values_as_incomplete(client, async_session):
    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders")
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", business_name="Status", data_type="TEXT")
    async_session.add(column)
    await async_session.flush()
    proposal = ColumnValueProposalModel(column_id=column.id, source="observed", status="pending", values=["completed"],
                                        schema_fingerprint=proposal_fingerprint(database, table, column))
    async_session.add(proposal)
    await async_session.commit()
    url = f"/api/v1/semantic/{database.id}/column-value-proposals"
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}
    response = await client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.json()["items"][0]["values"] == ["completed"]
    response = await client.post(url + "/review", headers=headers, json={"proposal_ids": [proposal.id], "action": "approve"})
    assert response.status_code == 200
    await async_session.refresh(column)
    assert column.allowed_values == ["completed"] and column.allowed_values_complete is False
    response = await client.post(url + "/review", headers=headers, json={"proposal_ids": [proposal.id], "action": "approve"})
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_manual_scan_reopens_dismissed_proposals(client, async_session, monkeypatch):
    from src.api import categorical_routes

    user = await async_session.get(UserModel, 1)
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="postgresql", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    live = LiveTargetDbModel(created_by=1, display_name="DB", dialect="postgresql", conn_url_enc="encrypted",
                             schema_metadata={}, semantic_db_id=database.id, categorical_discovery_enabled=True)
    async_session.add(live)
    await async_session.commit()
    queue = Mock(return_value=True)
    monkeypatch.setattr(categorical_routes, "queue_discovery", queue)
    headers = {"Authorization": f"Bearer {create_access_token(user)}"}

    response = await client.post(f"/api/v1/semantic/{database.id}/column-value-proposals/scan", headers=headers)

    assert response.status_code == 200
    queue.assert_called_once_with(database.id, refresh_dismissed=True)
