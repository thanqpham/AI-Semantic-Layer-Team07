"""Read UNIQUE constraint metadata for live relationship suggestions."""

from sqlalchemy import inspect, select
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.models.db import LiveTargetDbModel
from src.services.database import decrypt_conn_url
from src.services.introspection import _normalize_url


def inspect_unique_keys(connection: Connection, metadata: list[dict]) -> list[list[list[str]]]:
    """Return full UNIQUE constraint column sets through synchronous Inspector."""
    inspector = inspect(connection)
    return [
        [
            list(key["column_names"])
            for key in inspector.get_unique_constraints(t["name"], schema=t["schema"])
            if key.get("column_names") and all(key["column_names"])
        ]
        for t in metadata
    ]


async def attach_unique_keys(db: AsyncSession, db_id: int, metadata: list[dict]) -> None:
    """Enrich live metadata without reading rows or exposing connection credentials."""
    target = await db.scalar(select(LiveTargetDbModel).where(LiveTargetDbModel.semantic_db_id == db_id))
    if target is None:
        return
    engine = create_async_engine(_normalize_url(decrypt_conn_url(target.conn_url_enc), target.dialect), echo=False)
    try:
        async with engine.connect() as connection:
            keys = await connection.run_sync(inspect_unique_keys, metadata)
        for table, unique_keys in zip(metadata, keys, strict=True):
            ids = {column["column_name"]: column["id"] for column in table["columns"]}
            table["unique_keys"] = [[ids[name] for name in key] for key in unique_keys if set(key) <= ids.keys()]
    finally:
        await engine.dispose()
