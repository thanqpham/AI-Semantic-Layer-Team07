"""Categorical proposal refresh behavior."""

import pytest

from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel
from src.models.db_categorical_proposals import ColumnValueProposalModel
from src.services.categorical_proposals import _save_proposals


@pytest.mark.asyncio
async def test_explicit_rescan_reopens_dismissed_proposal(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders")
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", business_name="Status", data_type="TEXT")
    async_session.add(column)
    await async_session.flush()
    proposal = ColumnValueProposalModel(column_id=column.id, source="observed", status="dismissed",
                                        values=["old"], schema_fingerprint="old", reviewed_by=1)
    async_session.add(proposal)
    await async_session.flush()

    await _save_proposals(async_session, database, [(table, column, ["completed"])], refresh_dismissed=True)

    assert proposal.status == "pending"
    assert proposal.values == ["completed"]
    assert proposal.reviewed_by is None


@pytest.mark.asyncio
async def test_unsafe_rescan_removes_old_pending_proposal(async_session):
    database = SemanticDatabaseModel(created_by=1, display_name="DB", db_type="sqlite", conn_url_enc="encrypted")
    async_session.add(database)
    await async_session.flush()
    table = SemanticTableModel(db_id=database.id, table_name="orders", business_name="Orders")
    async_session.add(table)
    await async_session.flush()
    column = SemanticColumnModel(table_id=table.id, column_name="status", business_name="Status", data_type="TEXT")
    async_session.add(column)
    await async_session.flush()
    proposal = ColumnValueProposalModel(column_id=column.id, source="observed", status="pending",
                                        values=["completed"], schema_fingerprint="old")
    async_session.add(proposal)
    await async_session.flush()

    await _save_proposals(async_session, database, [(table, column, None)])
    await async_session.flush()

    assert await async_session.get(ColumnValueProposalModel, proposal.id) is None
