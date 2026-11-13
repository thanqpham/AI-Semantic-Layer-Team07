"""Read only complete UNIQUE constraints through Inspector."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.services.relationship_unique_evidence import inspect_unique_keys


@pytest.mark.asyncio
async def test_inspector_reports_full_composite_keys_not_partial_or_nonunique_indexes():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    metadata = [{"schema": None, "name": "payments"}]
    async with engine.begin() as connection:
        await connection.execute(text("CREATE TABLE payments (id INTEGER PRIMARY KEY, a INT, b INT, UNIQUE(a,b))"))
        await connection.execute(text("CREATE INDEX ordinary ON payments(a)"))
        evidence = await connection.run_sync(inspect_unique_keys, metadata)
    assert evidence == [[["a", "b"]]]
    await engine.dispose()
