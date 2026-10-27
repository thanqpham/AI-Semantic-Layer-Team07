"""Semantic Service — Canonical schema enrichment and HITL compliance.

Provides:
  - ensure_semantic_database: Create or find SemanticDatabaseModel for a source.
  - enrich_and_save_canonical_schema: LLM-enrich raw schema → draft semantic tables/columns/FKs.

The metric lifecycle lives in :mod:`src.services.metric_service` and is re-exported
here so existing call sites keep working.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    ImportedSchemaModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.review_mixin import REVIEW_STATUS_PENDING
from src.models.schema_metadata import RawSchemaMetadata
from src.services.clustering import cluster_tables
from src.services.database import lock_semantic_database
from src.services.enrichment_config import DEFAULT_CONFIG
from src.services.metric_service import (
    DuplicateMetricError,
    MetricRequiresReviewError,
    approve_metric,
    coerce_metric_definition,
    create_metric,
    get_metric_with_history,
    reject_metric_update,
    restore_metric,
    soft_delete_metric,
    update_metric,
)
from src.services.pass1_global_glossary import execute_pass1
from src.services.pass2_cluster_enrichment import enrich_clusters_parallel
from src.services.relationship_sync import invalidate_relationship_columns, reconcile_relationships
from src.services.schema_review_service import apply_ai_proposal, pending_review_counts

logger = logging.getLogger(__name__)

_TIME_DIMENSION_TYPES = {"TIMESTAMP", "TIMESTAMP WITHOUT TIME ZONE", "TIMESTAMP WITH TIME ZONE", "DATE", "DATETIME"}

# Backward-compatible alias for the private name used by the API layer.
_coerce_metric_definition = coerce_metric_definition

__all__ = [
    "DuplicateMetricError",
    "MetricRequiresReviewError",
    "approve_metric",
    "coerce_metric_definition",
    "create_metric",
    "delete_semantic_database",
    "enrich_and_save_canonical_schema",
    "ensure_semantic_database",
    "get_metric_with_history",
    "reject_metric_update",
    "restore_metric",
    "soft_delete_metric",
    "update_metric",
]


def _pydantic_tables_to_typeddict(tables) -> list[dict]:
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


async def ensure_semantic_database(
    db: AsyncSession,
    source_type: str,
    source_id: int,
    user_id: int,
    display_name: str,
    dialect: str,
    org_id: int | None = None,
) -> int:
    """Create or retrieve a SemanticDatabaseModel for a given source.

    Uses a deterministic conn_url_enc key to deduplicate: ``semantic:{source_type}:{source_id}``.
    Returns the semantic_databases.id.
    """
    conn_key = f"semantic:{source_type}:{source_id}"
    stmt = select(SemanticDatabaseModel).where(SemanticDatabaseModel.conn_url_enc == conn_key)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        if org_id is not None and existing.org_id is None:
            existing.org_id = org_id
            await db.flush()
        return existing.id

    record = SemanticDatabaseModel(
        org_id=org_id,
        created_by=user_id,
        display_name=display_name,
        db_type=dialect,
        conn_url_enc=conn_key,
        status="draft",
    )
    db.add(record)
    await db.flush()
    return record.id


async def enrich_and_save_canonical_schema(
    db: AsyncSession,
    user_id: int,
    connection_id: int,
    raw_schema: RawSchemaMetadata,
    dialect: str,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Enrich raw schema metadata with LLM-generated business names and save as draft.

    Steps:
      1. Build LLM prompt from raw schema tables/columns.
      2. Call LLM for Vietnamese business names and descriptions.
      3. Upsert into semantic_tables and semantic_columns (status implicit via model defaults).
      4. Extract foreign keys into canonical_relationships.
      5. Return summary dict with status='draft'.

    When *enrichment* is provided (HITL path), it is used directly and no LLM call is made.
    The dict must have a ``"tables"`` key whose value is a list of enrichment dicts (one per
    table, in the same order as ``raw_schema.tables``).
    """
    logger.info(
        "[AI Semantic Agent] Starting canonical schema enrichment for connection_id=%d (%d tables)...",
        connection_id,
        len(raw_schema.tables),
    )

    if enrichment is not None:
        enrichment_tables: list[dict[str, Any]] = enrichment.get("tables", [])
        logger.info("[AI Semantic Agent] Using provided enrichment (%d tables, HITL path)", len(enrichment_tables))
    else:
        enrichment_tables = await _call_llm_enrichment(raw_schema, dialect)
    logger.info("[AI Semantic Agent] Enrichment ready for %d tables", len(enrichment_tables))

    enrichment_by_key = {
        ((e.get("physical_schema") or e.get("schema_name") or "").lower(), e.get("table_name", "").lower()): e
        for e in enrichment_tables
    }
    name_counts = {
        t.table_name.raw_name.lower(): sum(
            other.table_name.raw_name.lower() == t.table_name.raw_name.lower() for other in raw_schema.tables
        )
        for t in raw_schema.tables
    }

    await lock_semantic_database(db, connection_id)
    table_id_map: dict[tuple[str, str], int] = {}

    for idx, table_meta in enumerate(raw_schema.tables):
        table_name = table_meta.table_name.raw_name
        identity = (table_meta.schema_name.raw_name.lower(), table_name.lower())
        table_enrichment = enrichment_by_key.get(identity)
        if table_enrichment is None:
            table_enrichment = (
                enrichment_by_key.get(("", table_name.lower()), {})
                if name_counts[table_name.lower()] == 1
                else (
                    enrichment_tables[idx]
                    if idx < len(enrichment_tables) and enrichment_tables[idx].get("table_name") == table_name
                    else {}
                )
            )
        pk_cols = table_meta.primary_key.constrained_columns if table_meta.primary_key else ()
        pk_col_name = pk_cols[0].raw_name if pk_cols else None

        table_id = await _upsert_semantic_table(
            db=db,
            connection_id=connection_id,
            table_name=table_name,
            enrichment=table_enrichment,
            schema_name=table_meta.schema_name.raw_name,
            pk_col=pk_col_name,
            user_id=user_id,
        )
        table_id_map[identity] = table_id
        bname = table_enrichment.get("business_name", table_name)
        logger.info(
            "[AI Semantic Agent] Processed table '%s' (ID=%d, business_name='%s', columns=%d)",
            table_name,
            table_id,
            bname,
            len(table_meta.columns),
        )

        col_enrichments = {c["column_name"]: c for c in table_enrichment.get("columns", [])}
        fk_references = _foreign_key_references(table_meta)
        for col_meta in table_meta.columns:
            col_enrich = col_enrichments.get(col_meta.column_name.raw_name, {})
            await _upsert_semantic_column(
                db=db,
                table_id=table_id,
                col_meta=col_meta,
                enrichment=col_enrich,
                fk_reference=fk_references.get(col_meta.column_name.raw_name),
            )

    relationships = await _extract_and_save_relationships(db, connection_id, raw_schema, table_id_map)
    logger.info(
        "[AI Semantic Agent] Extracted %d foreign key relationships for connection_id=%d",
        len(relationships),
        connection_id,
    )

    await db.commit()
    logger.info("[AI Semantic Agent] Canonical schema enrichment completed for connection_id=%d", connection_id)

    review = await pending_review_counts(db, connection_id)
    return {
        "tables": [
            {
                "table_name": t.table_name.raw_name,
                "physical_schema": t.schema_name.raw_name,
                "table_id": table_id_map[(t.schema_name.raw_name.lower(), t.table_name.raw_name.lower())],
            }
            for t in raw_schema.tables
        ],
        "relationships": relationships,
        "status": "pending_review" if review["pending_tables"] or review["pending_columns"] else "draft",
        **review,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _call_llm_enrichment(raw_schema: RawSchemaMetadata, dialect: str) -> list[dict[str, Any]]:
    """Two-Pass enrichment: Pass 1 global glossary + Pass 2 cluster enrichment."""
    tables_typeddict = _pydantic_tables_to_typeddict(raw_schema.tables)
    sem = asyncio.Semaphore(DEFAULT_CONFIG.max_concurrency)

    global_glossary = await execute_pass1(tables_typeddict, dialect, sem)
    clusters = cluster_tables(tables_typeddict)
    enriched_dict = await enrich_clusters_parallel(clusters, global_glossary, dialect, sem)

    enriched_tables: list[dict[str, Any]] = []
    for t_meta in raw_schema.tables:
        schema_name = t_meta.schema_name.raw_name if t_meta.schema_name else None
        t_key = f"{schema_name}.{t_meta.table_name.raw_name}" if schema_name else t_meta.table_name.raw_name
        if t_key in enriched_dict:
            enriched_tables.append({**enriched_dict[t_key], "physical_schema": schema_name})
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


async def _upsert_semantic_table(
    db: AsyncSession,
    connection_id: int,
    table_name: str,
    enrichment: dict[str, Any],
    schema_name: str,
    pk_col: str | None,
    user_id: int,
) -> int:
    """Upsert a table by database and normalized physical schema/name."""
    stmt = select(SemanticTableModel).where(
        SemanticTableModel.db_id == connection_id,
        func.lower(SemanticTableModel.table_name) == table_name.lower(),
        func.lower(func.coalesce(SemanticTableModel.physical_schema, "")) == (schema_name or "").lower(),
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        apply_ai_proposal(existing, enrichment.get("business_name", table_name), enrichment.get("description", ""))
        existing.primary_key_column = pk_col
        return existing.id

    record = SemanticTableModel(
        db_id=connection_id,
        table_name=table_name,
        business_name=enrichment.get("business_name", table_name),
        description=enrichment.get("description", ""),
        ai_business_name=enrichment.get("business_name", table_name),
        ai_description=enrichment.get("description", ""),
        review_status=REVIEW_STATUS_PENDING,
        physical_schema=schema_name,
        primary_key_column=pk_col,
        created_by=user_id,
    )
    db.add(record)
    await db.flush()
    return record.id


async def _upsert_semantic_column(
    db: AsyncSession,
    table_id: int,
    col_meta: Any,
    enrichment: dict[str, Any],
    fk_reference: tuple[str, str] | None,
) -> int:
    """Upsert a semantic column: update if exists (by table_id + column_name), insert otherwise."""
    col_name = col_meta.column_name.raw_name
    data_type = col_meta.data_type
    is_time = data_type.upper().strip() in _TIME_DIMENSION_TYPES

    stmt = select(SemanticColumnModel).where(
        SemanticColumnModel.table_id == table_id,
        SemanticColumnModel.column_name == col_name,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()

    if existing:
        if existing.data_type.lower() != data_type.lower():
            db_id = await db.scalar(select(SemanticTableModel.db_id).where(SemanticTableModel.id == table_id))
            await invalidate_relationship_columns(db, db_id, {existing.id})
        apply_ai_proposal(existing, enrichment.get("business_name", col_name), enrichment.get("description", ""))
        existing.is_time_dimension = is_time
        existing.data_type = data_type
        existing.is_primary_key = col_meta.primary_key
        existing.is_foreign_key = fk_reference is not None
        existing.fk_target_table = fk_reference[0] if fk_reference else None
        existing.fk_target_column = fk_reference[1] if fk_reference else None
        existing.is_nullable = col_meta.nullable
        existing.allowed_values = list(col_meta.sample_values) if col_meta.sample_values else None
        return existing.id

    record = SemanticColumnModel(
        table_id=table_id,
        column_name=col_name,
        data_type=data_type,
        business_name=enrichment.get("business_name", col_name),
        description=enrichment.get("description", ""),
        ai_business_name=enrichment.get("business_name", col_name),
        ai_description=enrichment.get("description", ""),
        review_status=REVIEW_STATUS_PENDING,
        is_primary_key=col_meta.primary_key,
        is_foreign_key=fk_reference is not None,
        fk_target_table=fk_reference[0] if fk_reference else None,
        fk_target_column=fk_reference[1] if fk_reference else None,
        is_nullable=col_meta.nullable,
        is_time_dimension=is_time,
        allowed_values=list(col_meta.sample_values) if col_meta.sample_values else None,
    )
    db.add(record)
    await db.flush()
    return record.id


def _foreign_key_references(table_meta: Any) -> dict[str, tuple[str, str]]:
    """Index raw FK metadata by local column for semantic-column persistence."""
    references: dict[str, tuple[str, str]] = {}
    for foreign_key in table_meta.foreign_keys:
        for source, target in zip(foreign_key.constrained_columns, foreign_key.referred_columns, strict=True):
            references[source.raw_name] = (foreign_key.referred_table.raw_name, target.raw_name)
    return references


async def _extract_and_save_relationships(
    db: AsyncSession, connection_id: int, raw_schema: RawSchemaMetadata, table_id_map: dict[tuple[str, str], int]
) -> list[dict[str, Any]]:
    """Reconcile physical evidence and retain the acquisition response contract."""
    await reconcile_relationships(db, connection_id, raw_schema)
    return [
        {
            "from_table": table.table_name.raw_name,
            "from_schema": table.schema_name.raw_name,
            "to_schema": fk.referred_schema.raw_name,
            "from_table_id": table_id_map[(table.schema_name.raw_name.lower(), table.table_name.raw_name.lower())],
            "to_table_id": table_id_map[(fk.referred_schema.raw_name.lower(), fk.referred_table.raw_name.lower())],
            "to_table": fk.referred_table.raw_name,
            "join_condition": " AND ".join(
                f"{table.table_name.raw_name}.{a.raw_name} = {fk.referred_table.raw_name}.{b.raw_name}"
                for a, b in zip(fk.constrained_columns, fk.referred_columns, strict=True)
            ),
            "relationship_type": "many_to_one",
        }
        for table in raw_schema.tables
        for fk in table.foreign_keys
    ]


async def delete_semantic_database(
    db: AsyncSession,
    db_id: int,
    user_id: int | None = None,
) -> bool:
    """Delete SemanticDatabaseModel and all linked technical DBs/schemas, tables, metrics, and relationships."""
    stmt = select(SemanticDatabaseModel).where(SemanticDatabaseModel.id == db_id)
    if user_id is not None:
        stmt = stmt.where(SemanticDatabaseModel.created_by == user_id)
    sem_db = (await db.execute(stmt)).scalar_one_or_none()
    if sem_db is None:
        return False

    live_stmt = select(LiveTargetDbModel).where(LiveTargetDbModel.semantic_db_id == db_id)
    for ldb in (await db.execute(live_stmt)).scalars().all():
        await db.delete(ldb)

    imp_stmt = select(ImportedSchemaModel).where(ImportedSchemaModel.semantic_db_id == db_id)
    for imp in (await db.execute(imp_stmt)).scalars().all():
        await db.delete(imp)

    await db.delete(sem_db)
    await db.commit()
    return True
