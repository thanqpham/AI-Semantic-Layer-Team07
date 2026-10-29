"""Tests for schema-aware metric prompt eligibility."""

from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    CanonicalRelationshipModel,
    ImportedSchemaModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.schemas import MetricPromptSuggestionItem
from src.services.metric_prompt_suggestions import _eligible_suggestions


def _service() -> Callable[[AsyncSession, int, bool], Awaitable[list[MetricPromptSuggestionItem]]]:
    try:
        from src.services.metric_prompt_suggestions import get_metric_prompt_suggestions
    except ImportError as exc:
        pytest.fail(f"metric prompt suggestion service is missing: {exc}")
    return get_metric_prompt_suggestions


async def _seed_schema(
    db: AsyncSession,
    *,
    source: str = "live",
    fingerprint: str | None = "fingerprint",
    sync_status: str = "synced",
    category_status: str = "approved",
    relationship_status: str = "approved",
    relationship_type: str = "many_to_one",
    include_amount: bool = True,
    include_relationship: bool = True,
) -> int:
    semantic_db = await _seed_database(db, source, fingerprint, sync_status)
    orders, customers = await _seed_tables(db, semantic_db.id)
    await _seed_columns(db, orders, customers, category_status, include_amount)
    if include_relationship:
        _seed_relationship(db, semantic_db.id, orders.id, customers.id, relationship_status, relationship_type)
    await db.flush()
    return semantic_db.id


async def _seed_database(
    db: AsyncSession, source: str, fingerprint: str | None, sync_status: str
) -> SemanticDatabaseModel:
    semantic_db = SemanticDatabaseModel(
        created_by=1,
        display_name="Test DB",
        db_type="sqlite",
        conn_url_enc="encrypted",
        schema_fingerprint=fingerprint,
        sync_status=sync_status,
    )
    db.add(semantic_db)
    await db.flush()
    await _seed_source(db, semantic_db.id, source)
    return semantic_db


async def _seed_source(db: AsyncSession, db_id: int, source: str) -> None:
    if source == "live":
        db.add(
            LiveTargetDbModel(
                created_by=1,
                display_name="Test DB",
                dialect="sqlite",
                conn_url_enc="encrypted",
                schema_metadata={},
                semantic_db_id=db_id,
            )
        )
        return
    if source == "dump":
        db.add(
            ImportedSchemaModel(
                created_by=1,
                display_name="Test dump",
                dialect="sqlite",
                schema_metadata={},
                semantic_db_id=db_id,
            )
        )


async def _seed_tables(db: AsyncSession, db_id: int) -> tuple[SemanticTableModel, SemanticTableModel]:
    orders = SemanticTableModel(db_id=db_id, table_name="orders", business_name="Đơn hàng", created_by=1)
    customers = SemanticTableModel(db_id=db_id, table_name="customers", business_name="Khách hàng", created_by=1)
    db.add_all([orders, customers])
    await db.flush()
    return orders, customers


async def _seed_columns(
    db: AsyncSession,
    orders: SemanticTableModel,
    customers: SemanticTableModel,
    category_status: str,
    include_amount: bool,
) -> None:
    db.add_all(_order_columns(orders.id, category_status, include_amount))
    db.add_all(_customer_columns(customers.id))


def _order_columns(table_id: int, category_status: str, include_amount: bool) -> list[SemanticColumnModel]:
    columns = [
        _column(table_id, "id", "INTEGER", "Mã đơn", is_primary_key=True),
        _column(table_id, "customer_id", "INTEGER", "Mã khách"),
        _column(table_id, "status", "TEXT", "Trạng thái", ["completed", "cancelled"], category_status),
    ]
    if include_amount:
        columns.append(_column(table_id, "amount", "NUMERIC", "Giá trị"))
    return columns


def _customer_columns(table_id: int) -> list[SemanticColumnModel]:
    return [
        _column(table_id, "id", "INTEGER", "Mã khách", is_primary_key=True),
        _column(table_id, "region", "TEXT", "Khu vực"),
    ]


def _column(
    table_id: int,
    name: str,
    data_type: str,
    business_name: str,
    allowed_values: list[str] | None = None,
    review_status: str = "pending_review",
    is_primary_key: bool = False,
) -> SemanticColumnModel:
    return SemanticColumnModel(
        table_id=table_id,
        column_name=name,
        data_type=data_type,
        business_name=business_name,
        allowed_values=allowed_values,
        review_status=review_status,
        is_primary_key=is_primary_key,
    )


def _seed_relationship(
    db: AsyncSession, db_id: int, from_id: int, to_id: int, review_status: str, relationship_type: str
) -> None:
    db.add(
        CanonicalRelationshipModel(
            connection_id=db_id,
            from_entity_id=from_id,
            to_entity_id=to_id,
            relationship_type=relationship_type,
            join_condition="orders.customer_id = customers.id",
            validation_status="valid",
            review_status=review_status,
        )
    )


@pytest.mark.asyncio
async def test_returns_supported_aggregate_ratio_filter_and_plan_suggestions(async_session: AsyncSession):
    db_id = await _seed_schema(async_session)

    suggestions = await _service()(async_session, db_id, query_supported=True)

    ids = {item.id for item in suggestions}
    assert {"total_revenue", "average_order_value", "completed_orders", "revenue_by_region"} <= ids
    assert not {"repeat_customers", "column_comparison"} & ids
    assert all(item.title and item.prompt for item in suggestions)


@pytest.mark.asyncio
async def test_required_columns_and_active_relationship_gate_plan_suggestions(async_session: AsyncSession):
    db_id = await _seed_schema(async_session, include_amount=False, include_relationship=False)

    suggestions = await _service()(async_session, db_id, query_supported=True)

    ids = {item.id for item in suggestions}
    assert "total_revenue" not in ids
    assert "average_order_value" not in ids
    assert "revenue_by_region" not in ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("relationship_status", "relationship_type"),
    [("disabled", "many_to_one"), ("approved", "one_to_many")],
)
async def test_plan_requires_an_active_many_to_one_relationship(
    async_session: AsyncSession, relationship_status: str, relationship_type: str
):
    db_id = await _seed_schema(
        async_session, relationship_status=relationship_status, relationship_type=relationship_type
    )

    suggestions = await _service()(async_session, db_id, query_supported=True)

    assert "revenue_by_region" not in {item.id for item in suggestions}


@pytest.mark.asyncio
async def test_filtered_suggestion_requires_approved_allowed_values(async_session: AsyncSession):
    db_id = await _seed_schema(async_session, category_status="pending_review")

    service = _service()
    pending = await service(async_session, db_id, query_supported=True)
    assert "completed_orders" not in {item.id for item in pending}

    column = await async_session.scalar(select(SemanticColumnModel).where(SemanticColumnModel.column_name == "status"))
    column.review_status = "approved"
    await async_session.flush()
    approved = await service(async_session, db_id, query_supported=True)
    assert "completed_orders" in {item.id for item in approved}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "fingerprint", "sync_status"),
    [
        ("dump", "fingerprint", "synced"),
        ("live", None, "synced"),
        ("live", "fingerprint", "stale"),
        ("live", "fingerprint", "unsynced"),
    ],
)
async def test_unqueryable_or_stale_sources_return_no_suggestions(
    async_session: AsyncSession, source: str, fingerprint: str | None, sync_status: str
):
    db_id = await _seed_schema(async_session, source=source, fingerprint=fingerprint, sync_status=sync_status)

    assert await _service()(async_session, db_id, query_supported=source == "live") == []


@pytest.mark.asyncio
async def test_query_unsupported_database_returns_no_suggestions(async_session: AsyncSession):
    db_id = await _seed_schema(async_session)

    assert await _service()(async_session, db_id, query_supported=False) == []


def test_query_unsupported_schema_is_ineligible_even_when_metric_columns_exist():
    schema = {
        "tables": [
            {
                "table_name": "orders",
                "columns": [
                    {"id": 1, "column_name": "id", "data_type": "INTEGER", "is_primary_key": True},
                    {"id": 2, "column_name": "amount", "data_type": "NUMERIC"},
                ],
            }
        ],
        "relationships": [],
    }

    assert _eligible_suggestions(schema, query_supported=False) == []


@pytest.mark.asyncio
async def test_missing_canonical_schema_returns_no_suggestions(async_session: AsyncSession):
    semantic_db = await _seed_database(async_session, "live", "fingerprint", "synced")

    assert await _service()(async_session, semantic_db.id, query_supported=True) == []
