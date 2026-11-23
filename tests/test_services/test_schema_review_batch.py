"""Tests for the atomic batch save of schema-review inline edits."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel
from src.models.review_mixin import REVIEW_STATUS_APPROVED, REVIEW_STATUS_PENDING
from src.models.review_schemas import ReviewBatchColumnEdit, ReviewBatchTableEdit
from src.services.schema_review_service import SchemaRowNotFoundError, update_review_batch


async def _seed_db(db: AsyncSession, name: str) -> tuple[int, SemanticTableModel, SemanticColumnModel]:
    """Seed one approved table with one approved column in a fresh semantic DB."""
    sem_db = SemanticDatabaseModel(
        created_by=1, display_name=name, db_type="postgresql", conn_url_enc="encrypted", status="draft"
    )
    db.add(sem_db)
    await db.flush()
    table = SemanticTableModel(
        db_id=sem_db.id, table_name="orders", business_name="Đơn hàng", review_status=REVIEW_STATUS_APPROVED
    )
    db.add(table)
    await db.flush()
    column = SemanticColumnModel(
        table_id=table.id,
        column_name="total",
        data_type="NUMERIC",
        business_name="Tổng",
        review_status=REVIEW_STATUS_APPROVED,
    )
    db.add(column)
    await db.flush()
    return sem_db.id, table, column


@pytest.mark.asyncio
async def test_batch_saves_tables_and_columns_as_pending(async_session: AsyncSession):
    """Every edited row is stored, stripped and returned to review."""
    db_id, table, column = await _seed_db(async_session, "A")

    result = await update_review_batch(
        async_session,
        db_id,
        [ReviewBatchTableEdit(table_id=table.id, business_name=" Đơn đặt hàng ", description="Mô tả")],
        [ReviewBatchColumnEdit(column_id=column.id, business_name="Tổng tiền")],
        actor_id=1,
    )

    assert result == {"updated_tables": 1, "updated_columns": 1}
    assert table.business_name == "Đơn đặt hàng"
    assert table.review_status == REVIEW_STATUS_PENDING
    assert column.business_name == "Tổng tiền"
    assert column.updated_by == 1
    assert column.review_status == REVIEW_STATUS_PENDING


@pytest.mark.asyncio
async def test_batch_rejects_foreign_ids_without_writing(async_session: AsyncSession):
    """A column from another database aborts the whole batch before any row changes."""
    db_id, table, _ = await _seed_db(async_session, "A")
    _, _, foreign_column = await _seed_db(async_session, "B")

    with pytest.raises(SchemaRowNotFoundError):
        await update_review_batch(
            async_session,
            db_id,
            [ReviewBatchTableEdit(table_id=table.id, business_name="Đổi tên")],
            [ReviewBatchColumnEdit(column_id=foreign_column.id, business_name="Lạ")],
            actor_id=1,
        )

    assert table.business_name == "Đơn hàng"
    assert table.review_status == REVIEW_STATUS_APPROVED
    assert foreign_column.business_name == "Tổng"
