"""Bounded observed-value proposals isolated from approved schema metadata."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.models.db import LiveTargetDbModel, SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel
from src.models.db_categorical_proposals import ColumnValueProposalModel
from src.services.categorical_discovery_policy import eligible_column, safe_observed_values
from src.services.categorical_value_discovery import build_probe_statement
from src.services.database import decrypt_conn_url, get_session_factory
from src.services.query_execution import _async_url

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def proposal_fingerprint(database: SemanticDatabaseModel, table: SemanticTableModel, column: SemanticColumnModel) -> str:
    """Bind proposals to their physical identity and current semantic state."""
    data = [database.id, database.schema_fingerprint, table.id, table.physical_schema, table.table_name,
            column.id, column.column_name, column.data_type, column.is_primary_key, column.is_foreign_key,
            column.fk_target_table, column.fk_target_column, column.allowed_values]
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def queue_discovery(db_id: int, *, refresh_dismissed: bool = False) -> bool:
    """Schedule optional scans without blocking user requests."""
    if not get_settings().categorical_discovery_enabled:
        return False
    task = asyncio.create_task(_background_scan(db_id, refresh_dismissed))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return True


async def _background_scan(db_id: int, refresh_dismissed: bool = False) -> None:
    try:
        async with get_session_factory()() as db:
            await discover_values(db, db_id, refresh_dismissed)
    except Exception:
        logger.warning("Categorical discovery failed for database %d", db_id)


async def discover_values(db: AsyncSession, db_id: int, refresh_dismissed: bool = False) -> None:
    """Scan one Live DB while holding its metadata row lock across the batch."""
    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    database = await db.scalar(select(SemanticDatabaseModel).where(SemanticDatabaseModel.id == db_id)
                               .with_for_update(skip_locked=True))
    if database is None:
        return
    live = await db.scalar(select(LiveTargetDbModel).where(LiveTargetDbModel.semantic_db_id == db_id))
    if live is None or not live.categorical_discovery_enabled or live.dialect not in {"postgres", "postgresql"}:
        await db.rollback()
        return
    tables = (await db.scalars(select(SemanticTableModel).options(selectinload(SemanticTableModel.columns))
                               .where(SemanticTableModel.db_id == db_id).order_by(SemanticTableModel.id))).all()
    candidates = [(table, col) for table in tables for col in table.columns
                  if not col.allowed_values and eligible_column(col)]
    candidates = select_batch(candidates, datetime.now(UTC).date().toordinal())
    results = await _probe_candidates(live, candidates)
    await _save_proposals(db, database, results, refresh_dismissed)
    await db.commit()


def select_batch(candidates: list, day: int) -> list:
    """Rotate the bounded daily window so large schemas are not starved."""
    if not candidates:
        return []
    start = (day * 20) % len(candidates)
    return (candidates[start:] + candidates[:start])[:20]


async def _probe_candidates(
    live: LiveTargetDbModel, candidates: list[tuple[Any, Any]]
) -> list[tuple[Any, Any, list | None]]:
    if not candidates:
        return []
    engine = create_async_engine(_async_url(decrypt_conn_url(live.conn_url_enc), "postgresql"), echo=False)
    results = []
    try:
        async with asyncio.timeout(65):
            async with engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                    await connection.execute(text("SET LOCAL statement_timeout = 3000"))
                    for table, col in candidates:
                        rows = await connection.execute(build_probe_statement(table.physical_schema, table.table_name, col.column_name))
                        values = safe_observed_values(list(rows.scalars().all()))
                        results.append((table, col, values))
    finally:
        await engine.dispose()
    return results


async def _save_proposals(db: AsyncSession, database: SemanticDatabaseModel,
                          results: list[tuple[Any, Any, list | None]],
                          refresh_dismissed: bool = False) -> None:
    for table, col, values in results:
        proposal = await db.scalar(select(ColumnValueProposalModel).where(ColumnValueProposalModel.column_id == col.id))
        if values is None:
            if proposal and proposal.status == "pending":
                await db.delete(proposal)
            continue
        if proposal and proposal.status != "pending":
            if proposal.status != "dismissed" or not refresh_dismissed:
                continue
            proposal.status = "pending"
            proposal.reviewed_by = None
        if proposal is None:
            proposal = ColumnValueProposalModel(column_id=col.id, source="observed", status="pending", values=values,
                                                schema_fingerprint=proposal_fingerprint(database, table, col))
            db.add(proposal)
        else:
            proposal.values = values
            proposal.schema_fingerprint = proposal_fingerprint(database, table, col)
            proposal.observed_at = datetime.now(UTC)
