import time

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine

from src.services.query_compiler_types import CompiledQuery
from src.services.query_execution import _set_read_only, execute_compiled_query


@pytest.mark.asyncio
async def test_sqlite_read_only_blocks_writes(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'guard.db'}")
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE TABLE example (value INTEGER)"))
        async with engine.connect() as connection:
            await _set_read_only(connection, "sqlite", 15)
            with pytest.raises(OperationalError, match="readonly"):
                await connection.execute(text("INSERT INTO example VALUES (1)"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_timeout_interrupts_and_releases_connection(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'timeout.db'}"
    sql = "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 50000000) SELECT SUM(x) FROM n LIMIT 100"
    start = time.monotonic()
    with pytest.raises(TimeoutError):
        await execute_compiled_query(url, "sqlite", CompiledQuery(sql=sql, parameters={}), timeout_seconds=0.05)
    assert time.monotonic() - start < 3
    result = await execute_compiled_query(url, "sqlite", CompiledQuery(sql="SELECT 1 LIMIT 100", parameters={}))
    assert result.rows == [[1]]
