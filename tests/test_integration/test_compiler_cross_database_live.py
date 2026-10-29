"""Live execution checks for isolated PostgreSQL, MySQL, and SQLite test databases."""

from __future__ import annotations

import os
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from src.models.schemas import DimensionSelection, SemanticQuerySpec
from src.services.query_compiler import SemanticQueryCompiler
from src.services.query_compiler_types import CompiledQuery
from src.services.query_execution import _set_read_only, execute_compiled_query
from src.services.semantic_compile_error import SemanticCompileError
from tests.test_integration.test_compiler_cross_database import (
    _add_metric,
    _ratio_body,
    _seed_commerce_catalog,
    _simple_body,
)

_BACKENDS = (
    ("postgresql", "COMPILER_TEST_POSTGRES_URL"),
    ("mysql", "COMPILER_TEST_MYSQL_URL"),
    ("sqlite", "COMPILER_TEST_SQLITE_URL"),
)


def _database_url(variable: str) -> str:
    value = os.environ.get(variable)
    if not value:
        pytest.fail(f"Required isolated compiler test database is missing: {variable}")
    return value


def _setup_url(dialect: str, url: str) -> str:
    if dialect == "sqlite":
        return url
    variable = "COMPILER_TEST_POSTGRES_SETUP_URL" if dialect == "postgresql" else "COMPILER_TEST_MYSQL_SETUP_URL"
    setup = _database_url(variable)
    creator, reader = make_url(setup), make_url(url)
    if creator.username == reader.username:
        pytest.fail("Fixture creator and read-only query users must be different")
    if (creator.host, creator.port, creator.database) != (reader.host, reader.port, reader.database):
        pytest.fail("Fixture creator and read-only query users must target the same isolated database")
    return setup


def _fixture_sql(dialect: str) -> tuple[str, ...]:
    quote = "`" if dialect == "mysql" else '"'
    return (
        f"CREATE TABLE {quote}customers{quote} ({quote}id{quote} INTEGER PRIMARY KEY, {quote}region{quote} VARCHAR(32))",
        f"CREATE TABLE {quote}orders{quote} ({quote}id{quote} INTEGER PRIMARY KEY, {quote}customer_id{quote} INTEGER, {quote}amount{quote} DECIMAL(12,2), {quote}status{quote} VARCHAR(32), {quote}order_code{quote} VARCHAR(32), {quote}created_at{quote} DATE)",
        f"CREATE TABLE {quote}order_items{quote} ({quote}id{quote} INTEGER PRIMARY KEY, {quote}order_id{quote} INTEGER, {quote}product_name{quote} VARCHAR(32), {quote}line_amount{quote} DECIMAL(12,2))",
        f"CREATE TABLE {quote}payments{quote} ({quote}id{quote} INTEGER PRIMARY KEY, {quote}order_id{quote} INTEGER, {quote}method{quote} VARCHAR(32), {quote}paid_amount{quote} DECIMAL(12,2))",
        f"CREATE TABLE {quote}returns{quote} ({quote}id{quote} INTEGER PRIMARY KEY, {quote}customer_id{quote} INTEGER, {quote}refund_amount{quote} DECIMAL(12,2))",
        "INSERT INTO customers VALUES (1, 'north'), (2, 'south'), (3, NULL)",
        "INSERT INTO orders VALUES (1, 1, 100, 'completed', 'ORD-1', '2026-01-01')",
        "INSERT INTO order_items VALUES (1, 1, 'Widget', 40), (2, 1, 'Widget', 60)",
        "INSERT INTO payments VALUES (1, 1, 'card', 30), (2, 1, 'card', 30), (3, 1, 'wallet', 40)",
        "INSERT INTO returns VALUES (1, 1, 25), (2, 3, 10)",
    )


@pytest_asyncio.fixture
async def isolated_fixture(dialect: str, url_variable: str):
    url = _database_url(url_variable)
    setup_url = _setup_url(dialect, url)
    engine = create_async_engine(setup_url)
    tables = ("customers", "orders", "order_items", "payments", "returns")
    created: list[str] = []
    quote = "`" if dialect == "mysql" else '"'
    try:
        async with engine.connect() as connection:
            existing = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            if set(tables).intersection(existing):
                pytest.fail("Compiler test database must be empty; refusing to overwrite existing tables")
        for index, statement in enumerate(_fixture_sql(dialect)):
            async with engine.begin() as connection:
                await connection.execute(text(statement))
            if index < len(tables):
                created.append(tables[index])
        yield setup_url
    finally:
        if created:
            async with engine.begin() as connection:
                for table in reversed(created):
                    await connection.execute(text(f"DROP TABLE {quote}{table}{quote}"))
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("dialect", "url_variable"), _BACKENDS[:2])
async def test_timeout_releases_live_database_connection(dialect: str, url_variable: str) -> None:
    url = _database_url(url_variable)
    delay = "pg_sleep(3)" if dialect == "postgresql" else "SLEEP(3)"
    with pytest.raises((TimeoutError, DBAPIError)):
        await execute_compiled_query(url, dialect, CompiledQuery(sql=f"SELECT {delay} LIMIT 100", parameters={}), 1)
    result = await execute_compiled_query(url, dialect, CompiledQuery(sql="SELECT 1 LIMIT 100", parameters={}), 3)
    assert result.rows == [[1]]


@pytest.mark.asyncio
@pytest.mark.parametrize(("dialect", "url_variable"), _BACKENDS)
async def test_compile_and_execute_live_database(
    dialect: str, url_variable: str, async_session: Any, isolated_fixture: str
) -> None:
    """Compile via approved metadata, execute on a fixture DB, and enforce read-only behavior."""
    url = _database_url(url_variable)
    setup_url = isolated_fixture
    engine = create_async_engine(setup_url)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await _set_read_only(connection, dialect, 15)
        with pytest.raises(DBAPIError):
            await connection.execute(text("INSERT INTO customers VALUES (999, 'blocked')"))
        await transaction.rollback()
    await engine.dispose()
    if dialect != "sqlite":
        reader = create_async_engine(url)
        async with reader.connect() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(text("INSERT INTO customers VALUES (999, 'blocked')"))
        await reader.dispose()

    catalog = await _seed_commerce_catalog(async_session)
    db, metric = catalog["db"], catalog["metrics"]["revenue"]
    db.db_type = dialect
    await async_session.flush()
    compiled = await SemanticQueryCompiler(async_session).compile(
        db.id,
        SemanticQuerySpec(
            metric_ids=[metric.id],
            filters=[{"column_id": catalog["cols"]["ord_status"].id, "operator": "eq", "value": "completed"}],
            limit=1000,
        ),
    )
    assert "LIMIT 1000" in compiled.sql.upper()
    assert "completed" not in compiled.sql
    assert all(value != "completed" for value in compiled.metadata.values())
    assert "completed" in repr(compiled.parameters)
    assert compiled.parameters
    result = await execute_compiled_query(url, dialect, compiled)
    assert result.row_count == 1
    assert result.rows[0][0] == 100

    with pytest.raises(SemanticCompileError):
        await execute_compiled_query(url, dialect, CompiledQuery(sql="DELETE FROM orders", parameters={}))

    cols, metrics = catalog["cols"], catalog["metrics"]
    fanout = SemanticQuerySpec(
        metric_ids=[metrics["revenue"].id],
        filters=[{"column_id": cols["item_product"].id, "operator": "eq", "value": "Widget"}],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, fanout)
    assert (await execute_compiled_query(url, dialect, compiled)).rows[0][0] == 100

    bundle = SemanticQuerySpec(
        metric_ids=[metrics["revenue"].id, metrics["refunds_plan"].id],
        dimensions=[DimensionSelection(column_id=cols["cust_region"].id)],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, bundle)
    result = await execute_compiled_query(url, dialect, compiled)
    rows = [dict(zip(result.columns, row, strict=True)) for row in result.rows]
    by_region = {row[f"dimension_{cols['cust_region'].id}"]: row for row in rows}
    assert by_region["north"][f"metric_{metrics['revenue'].id}"] == 100
    assert by_region["north"][f"metric_{metrics['refunds_plan'].id}"] == 25
    assert by_region[None][f"metric_{metrics['revenue'].id}"] is None
    assert by_region[None][f"metric_{metrics['refunds_plan'].id}"] == 10

    ratio = SemanticQuerySpec(metric_ids=[metrics["zero_denom_ratio"].id])
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, ratio)
    assert (await execute_compiled_query(url, dialect, compiled)).rows[0][0] is None

    empty = SemanticQuerySpec(
        metric_ids=[metrics["revenue"].id, metrics["cancelled"].id],
        filters=[{"column_id": cols["ord_id"].id, "operator": "eq", "value": 999}],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, empty)
    assert (await execute_compiled_query(url, dialect, compiled)).rows[0] == [None, 0]

    week = SemanticQuerySpec(
        metric_ids=[metrics["revenue"].id],
        dimensions=[DimensionSelection(column_id=cols["ord_created"].id, time_grain="week")],
    )
    compiled = await SemanticQueryCompiler(async_session).compile(db.id, week)
    result = await execute_compiled_query(url, dialect, compiled)
    row = dict(zip(result.columns, result.rows[0], strict=True))
    expected_week = "2025-12-29" if dialect == "postgresql" else "2026-W01"
    assert str(row[f"dimension_{cols['ord_created'].id}"]).startswith(expected_week)

    engine = create_async_engine(setup_url)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM orders"))
        await connection.execute(
            text(
                "INSERT INTO orders VALUES (1, 1, 10, 'completed', '1', '2026-01-01'), (2, 1, 20, 'completed', '2', '2026-01-01'), (3, 2, 90, 'completed', '3', '2026-01-01')"
            )
        )
    await engine.dispose()
    average = await _add_metric(
        async_session,
        db.id,
        catalog["tables"]["orders"],
        cols["ord_id"].id,
        "Average",
        "AVG",
        _simple_body("orders", "AVG", "amount", cols["ord_amount"], []),
    )
    compiled = await SemanticQueryCompiler(async_session).compile(
        db.id, SemanticQuerySpec(metric_ids=[average.id, metrics["refunds_simple"].id])
    )
    assert (await execute_compiled_query(url, dialect, compiled)).rows[0][0] == 40

    engine = create_async_engine(setup_url)
    async with engine.begin() as connection:
        await connection.execute(text("DELETE FROM orders"))
        await connection.execute(
            text(
                "INSERT INTO orders VALUES (1, 1, 1.5, 'completed', '1', '2026-01-01'), (2, 1, 0, 'completed', '2', '2026-01-01'), (3, 2, 0, 'completed', '3', '2026-01-01')"
            )
        )
    await engine.dispose()
    ratio_metric = await _add_metric(
        async_session,
        db.id,
        catalog["tables"]["orders"],
        cols["ord_id"].id,
        "Fractional Ratio",
        "SUM",
        _ratio_body(cols["ord_amount"], cols["ord_id"], []),
    )
    compiled = await SemanticQueryCompiler(async_session).compile(
        db.id, SemanticQuerySpec(metric_ids=[ratio_metric.id, metrics["refunds_simple"].id])
    )
    assert (await execute_compiled_query(url, dialect, compiled)).rows[0][0] == 0.5
