"""Fill-missing semantics, per-table commit and progress publishing tests."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db import (
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.schema_metadata import (
    ColumnMetadata,
    Identifier,
    PrimaryKeyMetadata,
    RawSchemaMetadata,
    SchemaDialect,
    SchemaMetadata,
    TableMetadata,
)
from src.services import enrichment_progress, semantic_service
from src.services.pass2_cluster_enrichment import enrich_clusters_parallel

DIALECT = SchemaDialect.POSTGRESQL


def _col(name: str, ordinal: int, pk: bool = False) -> ColumnMetadata:
    return ColumnMetadata(
        column_name=Identifier.from_raw(name, DIALECT),
        ordinal_position=ordinal,
        raw_data_type="TEXT",
        data_type="TEXT",
        nullable=not pk,
        primary_key=pk,
    )


def _table(name: str, cols: tuple[str, ...]) -> TableMetadata:
    return TableMetadata(
        schema_name=Identifier.from_raw("public", DIALECT),
        table_name=Identifier.from_raw(name, DIALECT),
        columns=tuple(_col(c, ordinal=i + 1, pk=(c == "id")) for i, c in enumerate(cols)),
        primary_key=PrimaryKeyMetadata(constrained_columns=(Identifier.from_raw("id", DIALECT),)),
    )


def _raw_schema(*tables: TableMetadata) -> RawSchemaMetadata:
    schema_meta = SchemaMetadata(schema_name=Identifier.from_raw("public", DIALECT))
    return RawSchemaMetadata(dialect=DIALECT, schemas=(schema_meta,), tables=tables)


def _enrichment(name: str, business_name: str, description: str) -> dict[str, Any]:
    return {
        "table_name": name,
        "physical_schema": "public",
        "business_name": business_name,
        "description": description,
        "columns": [{"column_name": "id", "business_name": "ID", "description": "Khóa chính"}],
    }


async def _seed_db(async_session: AsyncSession, db_id: int) -> None:
    async_session.add(
        SemanticDatabaseModel(
            id=db_id,
            created_by=1,
            display_name="Test",
            db_type="postgresql",
            conn_url_enc="dummy",
            status="draft",
        )
    )
    await async_session.commit()


async def _add_table(
    async_session: AsyncSession,
    db_id: int,
    name: str,
    business_name: str,
    description: str,
    review_status: str,
    columns: dict[str, tuple[str, str, str]] | None = None,
) -> None:
    table = SemanticTableModel(
        db_id=db_id,
        table_name=name,
        business_name=business_name,
        description=description,
        review_status=review_status,
        physical_schema="public",
        physical_schema_key="public",
        table_name_key=name,
    )
    async_session.add(table)
    await async_session.flush()
    for col_name, (bn, desc, status) in (columns or {}).items():
        async_session.add(
            SemanticColumnModel(
                table_id=table.id,
                column_name=col_name,
                data_type="TEXT",
                business_name=bn,
                description=desc,
                review_status=status,
            )
        )
    await async_session.commit()


async def _get_table(async_session: AsyncSession, db_id: int, name: str) -> SemanticTableModel:
    stmt = (
        select(SemanticTableModel)
        .where(SemanticTableModel.db_id == db_id, SemanticTableModel.table_name == name)
        .options(selectinload(SemanticTableModel.columns))
    )
    return (await async_session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_approved_table_skipped_and_empty_table_enriched(async_session: AsyncSession) -> None:
    """Approved rows are untouched; only missing tables are sent to the LLM."""
    db_id = 600
    await _seed_db(async_session, db_id)
    await _add_table(
        async_session,
        db_id,
        "orders",
        "Đơn hàng",
        "Bảng đơn hàng",
        "approved",
        columns={"id": ("Mã đơn", "Khóa chính", "approved")},
    )
    await _add_table(
        async_session,
        db_id,
        "customers",
        "customers",
        "",
        "pending_review",
        columns={"id": ("id", "", "pending_review")},
    )

    with patch.object(
        semantic_service,
        "_call_llm_enrichment",
        AsyncMock(return_value=[_enrichment("customers", "Khách hàng", "Bảng khách hàng")]),
    ) as mock_llm:
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("orders", ("id",)), _table("customers", ("id",))),
            dialect="postgresql",
        )

    assert mock_llm.await_count == 1
    llm_tables = mock_llm.call_args[0][0].tables
    assert [t.table_name.raw_name for t in llm_tables] == ["customers"]

    orders = await _get_table(async_session, db_id, "orders")
    assert orders.business_name == "Đơn hàng"
    assert orders.review_status == "approved"
    customers = await _get_table(async_session, db_id, "customers")
    assert customers.business_name == "Khách hàng"
    assert customers.description == "Bảng khách hàng"
    assert customers.review_status == "pending_review"
    assert enrichment_progress.get(db_id)["status"] == "succeeded"
    assert enrichment_progress.get(db_id)["total_tables"] == 1


@pytest.mark.asyncio
async def test_pending_physical_name_table_is_re_enriched(async_session: AsyncSession) -> None:
    """A pending row left with the physical-name fallback counts as missing."""
    db_id = 601
    await _seed_db(async_session, db_id)
    await _add_table(async_session, db_id, "products", "products", "", "pending_review")

    with patch.object(
        semantic_service,
        "_call_llm_enrichment",
        AsyncMock(return_value=[_enrichment("products", "Sản phẩm", "Bảng sản phẩm")]),
    ):
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("products", ("id",))),
            dialect="postgresql",
        )

    products = await _get_table(async_session, db_id, "products")
    assert products.business_name == "Sản phẩm"
    assert products.description == "Bảng sản phẩm"


@pytest.mark.asyncio
async def test_complete_rows_skipped_while_missing_column_filled(async_session: AsyncSession) -> None:
    """Table row and complete columns keep their values; only missing cells are filled."""
    db_id = 602
    await _seed_db(async_session, db_id)
    await _add_table(
        async_session,
        db_id,
        "invoices",
        "Hóa đơn",
        "Bảng hóa đơn",
        "pending_review",
        columns={
            "id": ("Mã HĐ", "Khóa chính", "pending_review"),
            "amount": ("amount", "", "pending_review"),
        },
    )

    rich = _enrichment("invoices", "Hóa đơn MỚI", "Mô tả mới")
    rich["columns"] = [
        {"column_name": "id", "business_name": "Mã MỚI", "description": "Mô tả MỚI"},
        {"column_name": "amount", "business_name": "Thành tiền", "description": "Tổng tiền hóa đơn"},
    ]
    with patch.object(semantic_service, "_call_llm_enrichment", AsyncMock(return_value=[rich])):
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("invoices", ("id", "amount"))),
            dialect="postgresql",
        )

    invoices = await _get_table(async_session, db_id, "invoices")
    assert invoices.business_name == "Hóa đơn"
    assert invoices.description == "Bảng hóa đơn"
    cols = {c.column_name: c for c in invoices.columns}
    assert cols["id"].business_name == "Mã HĐ"
    assert cols["id"].description == "Khóa chính"
    assert cols["amount"].business_name == "Thành tiền"
    assert cols["amount"].description == "Tổng tiền hóa đơn"


@pytest.mark.asyncio
async def test_hitl_path_applies_all_and_publishes_nothing(async_session: AsyncSession) -> None:
    """Explicit HITL enrichment bypasses fill-missing and publishes no progress."""
    db_id = 603
    await _seed_db(async_session, db_id)
    await _add_table(
        async_session,
        db_id,
        "orders",
        "Đơn hàng",
        "Bảng đơn hàng",
        "approved",
        columns={"id": ("Mã đơn", "Khóa chính", "approved")},
    )

    with patch.object(semantic_service, "_call_llm_enrichment", AsyncMock()) as mock_llm:
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("orders", ("id",))),
            dialect="postgresql",
            enrichment={"tables": [_enrichment("orders", "Tên mới", "Mô tả mới")]},
        )

    assert mock_llm.await_count == 0
    orders = await _get_table(async_session, db_id, "orders")
    # Approved values are never clobbered: the proposal lands in ai_* and re-pends the row.
    assert orders.business_name == "Đơn hàng"
    assert orders.ai_business_name == "Tên mới"
    assert orders.review_status == "pending_review"
    assert enrichment_progress.get(db_id) == {"status": "idle"}


@pytest.mark.asyncio
async def test_partial_commit_keeps_completed_tables(async_session: AsyncSession) -> None:
    """A failure on the second table leaves the first table committed."""
    db_id = 604
    await _seed_db(async_session, db_id)
    original = semantic_service._upsert_semantic_table

    async def flaky(db, connection_id, table_name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if table_name == "beta":
            raise RuntimeError("boom")
        return await original(db, connection_id, table_name, *args, **kwargs)

    with (
        patch.object(
            semantic_service,
            "_call_llm_enrichment",
            AsyncMock(
                return_value=[
                    _enrichment("alpha", "Bảng A", "Mô tả A"),
                    _enrichment("beta", "Bảng B", "Mô tả B"),
                ]
            ),
        ),
        patch.object(semantic_service, "_upsert_semantic_table", flaky),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await semantic_service.enrich_and_save_canonical_schema(
                db=async_session,
                user_id=1,
                connection_id=db_id,
                raw_schema=_raw_schema(_table("alpha", ("id",)), _table("beta", ("id",))),
                dialect="postgresql",
            )

    await async_session.rollback()
    stmt = select(SemanticTableModel).where(SemanticTableModel.db_id == db_id)
    names = sorted(t.table_name for t in (await async_session.execute(stmt)).scalars().all())
    assert names == ["alpha"]
    assert enrichment_progress.get(db_id)["status"] == "running"


@pytest.mark.asyncio
async def test_half_filled_row_keeps_human_field_and_fills_only_empty(async_session: AsyncSession) -> None:
    """A pending row with a human business name but empty description keeps the name."""
    db_id = 605
    await _seed_db(async_session, db_id)
    await _add_table(
        async_session,
        db_id,
        "orders",
        "Đơn hàng",
        "",
        "pending_review",
        columns={"id": ("Mã đơn", "", "pending_review")},
    )

    rich = _enrichment("orders", "Hóa đơn MỚI", "Mô tả AI")
    rich["columns"] = [
        {"column_name": "id", "business_name": "ID MỚI", "description": "Khóa chính bảng đơn"},
    ]
    with patch.object(semantic_service, "_call_llm_enrichment", AsyncMock(return_value=[rich])):
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("orders", ("id",))),
            dialect="postgresql",
        )

    orders = await _get_table(async_session, db_id, "orders")
    assert orders.business_name == "Đơn hàng"  # human value kept
    assert orders.description == "Mô tả AI"  # empty cell filled
    assert orders.ai_business_name == "Hóa đơn MỚI"  # raw proposal still visible
    cols = {c.column_name: c for c in orders.columns}
    assert cols["id"].business_name == "Mã đơn"  # human value kept
    assert cols["id"].description == "Khóa chính bảng đơn"  # empty cell filled
    assert cols["id"].ai_business_name == "ID MỚI"


@pytest.mark.asyncio
async def test_fallback_empty_proposal_does_not_wipe_human_description(async_session: AsyncSession) -> None:
    """When the LLM fails, fallback empty proposals must not clear human fields."""
    db_id = 606
    await _seed_db(async_session, db_id)
    await _add_table(async_session, db_id, "orders", "orders", "Mô tả do người viết", "pending_review")

    fallback = _enrichment("orders", "orders", "")  # pass2 fallback shape on cluster failure
    with patch.object(semantic_service, "_call_llm_enrichment", AsyncMock(return_value=[fallback])):
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("orders", ("id",))),
            dialect="postgresql",
        )

    orders = await _get_table(async_session, db_id, "orders")
    assert orders.description == "Mô tả do người viết"


@pytest.mark.asyncio
async def test_pass2_proposal_without_table_name_still_applies(async_session: AsyncSession) -> None:
    """Regression: pass2 returns entries without a table_name field.

    The save loop keys proposals by (physical_schema, table_name); the entry
    must carry the table identity or every proposal misses and nothing fills.
    """
    db_id = 607
    await _seed_db(async_session, db_id)

    pass2_shape = {  # exactly what _merge_cluster_result returns
        "public.orders": {
            "business_name": "Đơn hàng",
            "description": "Bảng đơn hàng",
            "columns": [{"column_name": "id", "business_name": "Mã đơn", "description": "Khóa chính"}],
        }
    }
    with (
        patch("src.services.semantic_fill.execute_pass1", AsyncMock(return_value={})),
        patch("src.services.semantic_fill.enrich_clusters_parallel", AsyncMock(return_value=pass2_shape)),
    ):
        await semantic_service.enrich_and_save_canonical_schema(
            db=async_session,
            user_id=1,
            connection_id=db_id,
            raw_schema=_raw_schema(_table("orders", ("id",))),
            dialect="postgresql",
        )

    orders = await _get_table(async_session, db_id, "orders")
    assert orders.business_name == "Đơn hàng"
    assert orders.description == "Bảng đơn hàng"
    cols = {c.column_name: c for c in orders.columns}
    assert cols["id"].business_name == "Mã đơn"
    assert cols["id"].description == "Khóa chính"


@pytest.mark.asyncio
async def test_pass2_reports_progress_callback() -> None:
    """enrich_clusters_parallel reports table counts as clusters start and finish."""
    clusters = [
        [{"table_name": "orders", "columns": [{"column_name": "id"}]}],
        [{"table_name": "customers", "columns": [{"column_name": "id"}]}],
    ]
    calls: list[tuple[int, int, str | None]] = []

    with patch(
        "src.services.pass2_cluster_enrichment.enrich_cluster_with_retry",
        AsyncMock(return_value={}),
    ):
        await enrich_clusters_parallel(
            clusters,
            {},
            "postgresql",
            asyncio.Semaphore(2),
            on_progress=lambda done, total, cur: calls.append((done, total, cur)),
        )

    assert calls, "on_progress was never called"
    assert calls[-1] == (2, 2, None)
    assert (0, 2, "orders") in calls or (0, 2, "customers") in calls
    assert all(total == 2 for _, total, _ in calls)
