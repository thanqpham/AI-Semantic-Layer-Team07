"""Fill-missing policy for AI schema enrichment.

Decides which tables/columns still need the LLM, calls the two-pass enrichment
pipeline, applies proposals without touching human-set fields, and bridges
cluster progress into the per-database registry.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models.db import SemanticTableModel
from src.models.review_mixin import REVIEW_STATUS_APPROVED
from src.models.schema_metadata import RawSchemaMetadata
from src.services import enrichment_progress
from src.services.clustering import cluster_tables
from src.services.enrichment_config import DEFAULT_CONFIG
from src.services.pass1_global_glossary import execute_pass1
from src.services.pass2_cluster_enrichment import enrich_clusters_parallel
from src.services.schema_review_service import apply_ai_proposal


def pydantic_tables_to_typeddict(tables) -> list[dict]:
    """Convert Pydantic TableMetadata to TypedDict for enrichment pipeline."""
    result = []
    for t in tables:
        fk_col_names = {col.raw_name for fk in t.foreign_keys for col in fk.constrained_columns}
        fk_ref_map: dict[str, dict] = {}
        for fk in t.foreign_keys:
            for i, col in enumerate(fk.constrained_columns):
                ref_col = fk.referred_columns[i] if i < len(fk.referred_columns) else fk.referred_columns[0]
                fk_ref_map[col.raw_name] = {
                    "table": fk.referred_table.raw_name,
                    "column": ref_col.raw_name,
                    "schema": fk.referred_schema.raw_name if fk.referred_schema else None,
                }
        result.append(
            {
                "table_name": t.table_name.raw_name,
                "schema_name": t.schema_name.raw_name if t.schema_name else None,
                "table_type": "BASE TABLE",
                "row_count_estimate": None,
                "columns": [
                    {
                        "column_name": c.column_name.raw_name,
                        "data_type": c.data_type,
                        "is_nullable": c.nullable,
                        "is_primary_key": c.primary_key,
                        "is_foreign_key": c.column_name.raw_name in fk_col_names,
                        "default_value": c.default_expression,
                        "sample_values": list(c.sample_values) if c.sample_values else None,
                        "references": fk_ref_map.get(c.column_name.raw_name),
                    }
                    for c in t.columns
                ],
                "primary_keys": [pk.raw_name for pk in (t.primary_key.constrained_columns if t.primary_key else [])],
                "foreign_keys": [
                    {
                        "constraint_name": fk.constraint_name.raw_name if fk.constraint_name else None,
                        "constrained_columns": [c.raw_name for c in fk.constrained_columns],
                        "referred_schema": fk.referred_schema.raw_name if fk.referred_schema else None,
                        "referred_table": fk.referred_table.raw_name,
                        "referred_columns": [c.raw_name for c in fk.referred_columns],
                    }
                    for fk in t.foreign_keys
                ],
                "indexes": [],
            }
        )
    return result


def row_is_complete(business_name: str | None, physical_name: str, description: str | None, review_status: str) -> bool:
    """A row is complete when approved, or filled with a business name and description."""
    if review_status == REVIEW_STATUS_APPROVED:
        return True
    return bool(business_name and business_name != physical_name and description and description.strip())


async def load_existing_state(db: AsyncSession, connection_id: int) -> dict[tuple[str, str], dict[str, Any]]:
    """Map each existing table's (normalized) identity to its row/column completeness."""
    stmt = (
        select(SemanticTableModel)
        .where(SemanticTableModel.db_id == connection_id)
        .options(selectinload(SemanticTableModel.columns))
    )
    tables = (await db.execute(stmt)).scalars().all()
    state: dict[tuple[str, str], dict[str, Any]] = {}
    for row in tables:
        key = (row.physical_schema_key or row.physical_schema or "", row.table_name_key or row.table_name)
        state[key] = {
            "complete": row_is_complete(row.business_name, row.table_name, row.description, row.review_status),
            "columns": {
                col.column_name: row_is_complete(col.business_name, col.column_name, col.description, col.review_status)
                for col in row.columns
            },
        }
    return state


def table_needs_llm(existing_state: dict[tuple[str, str], dict[str, Any]], table_meta: Any) -> bool:
    """A table needs the LLM when its row or any of its columns is incomplete or new."""
    key = (table_meta.schema_name.normalized_name or "", table_meta.table_name.normalized_name or "")
    table_state = existing_state.get(key)
    if table_state is None or not table_state["complete"]:
        return True
    known_columns = table_state["columns"]
    return any(
        col.column_name.raw_name not in known_columns or not known_columns[col.column_name.raw_name]
        for col in table_meta.columns
    )


def apply_proposal_values(
    row: Any, physical_name: str, prop_business_name: str, prop_description: str, fill_missing: bool
) -> None:
    """Record a proposal: fill-missing keeps human-set fields, HITL applies wholesale."""
    if not fill_missing or row.review_status == REVIEW_STATUS_APPROVED:
        apply_ai_proposal(row, prop_business_name, prop_description)
        return
    row.ai_business_name = prop_business_name
    row.ai_description = prop_description
    if not row.business_name or not row.business_name.strip() or row.business_name == physical_name:
        row.business_name = prop_business_name
    if not row.description or not row.description.strip():
        row.description = prop_description


def progress_publisher(connection_id: int) -> Callable[[int, int, str | None], None]:
    """Bridge pass2 cluster progress into the per-database enrichment registry."""

    def publish(completed: int, total: int, current_table: str | None) -> None:
        enrichment_progress.mark_generating(connection_id, completed, total, current_table)

    return publish


async def call_llm_enrichment(
    raw_schema: RawSchemaMetadata,
    dialect: str,
    on_progress: Callable[[int, int, str | None], None] | None = None,
) -> list[dict[str, Any]]:
    """Two-Pass enrichment: Pass 1 global glossary + Pass 2 cluster enrichment."""
    tables_typeddict = pydantic_tables_to_typeddict(raw_schema.tables)
    sem = asyncio.Semaphore(DEFAULT_CONFIG.max_concurrency)

    global_glossary = await execute_pass1(tables_typeddict, dialect, sem)
    clusters = cluster_tables(tables_typeddict)
    enriched_dict = await enrich_clusters_parallel(clusters, global_glossary, dialect, sem, on_progress=on_progress)

    enriched_tables: list[dict[str, Any]] = []
    for t_meta in raw_schema.tables:
        schema_name = t_meta.schema_name.raw_name if t_meta.schema_name else None
        t_key = f"{schema_name}.{t_meta.table_name.raw_name}" if schema_name else t_meta.table_name.raw_name
        if t_key in enriched_dict:
            # pass2 entries carry no identity: attach it or the (schema, table) lookup downstream misses
            enriched_tables.append(
                {**enriched_dict[t_key], "table_name": t_meta.table_name.raw_name, "physical_schema": schema_name}
            )
        else:
            enriched_tables.append(
                {
                    "table_name": t_meta.table_name.raw_name,
                    "physical_schema": schema_name,
                    "business_name": t_meta.table_name.raw_name,
                    "description": "",
                    "columns": [
                        {
                            "column_name": c.column_name.raw_name,
                            "business_name": c.column_name.raw_name,
                            "description": "",
                        }
                        for c in t_meta.columns
                    ],
                }
            )
    return enriched_tables
