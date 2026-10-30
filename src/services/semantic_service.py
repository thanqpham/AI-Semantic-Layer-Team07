"""Semantic Service — Canonical schema enrichment and HITL compliance.

Provides:
  - ensure_semantic_database: Create or find SemanticDatabaseModel for a source.
  - enrich_and_save_canonical_schema: LLM-enrich raw schema → draft semantic tables/columns/FKs.

The metric lifecycle lives in :mod:`src.services.metric_service` and is re-exported
here so existing call sites keep working.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.db import (
    ImportedSchemaModel,
    LiveTargetDbModel,
    NotificationModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.review_mixin import REVIEW_STATUS_PENDING
from src.models.schema_metadata import RawSchemaMetadata
from src.services import enrichment_progress
from src.services.database import lock_semantic_database
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
from src.services.relationship_sync import invalidate_relationship_columns, reconcile_relationships
from src.services.review_notifications import sync_schema_review_notifications
from src.services.schema_review_service import pending_review_counts
from src.services.semantic_fill import (
    apply_proposal_values as _apply_proposal_values,
)
from src.services.semantic_fill import (
    call_llm_enrichment as _call_llm_enrichment,
)
from src.services.semantic_fill import (
    load_existing_state as _load_existing_state,
)
from src.services.semantic_fill import (
    progress_publisher as _progress_publisher,
)
from src.services.semantic_fill import (
    table_needs_llm as _table_needs_llm,
)

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

    publish_progress = enrichment is None
    existing_state: dict[tuple[str, str], dict[str, Any]] = {}
    if enrichment is not None:
        enrichment_tables: list[dict[str, Any]] = enrichment.get("tables", [])
        logger.info("[AI Semantic Agent] Using provided enrichment (%d tables, HITL path)", len(enrichment_tables))
    else:
        existing_state = await _load_existing_state(db, connection_id)
        llm_tables = [t for t in raw_schema.tables if _table_needs_llm(existing_state, t)]
        enrichment_progress.start(connection_id, len(llm_tables))
        logger.info(
            "[AI Semantic Agent] Fill-missing: %d/%d tables need LLM enrichment",
            len(llm_tables),
            len(raw_schema.tables),
        )
        if llm_tables:
            enrichment_tables = await _call_llm_enrichment(
                raw_schema.model_copy(update={"tables": llm_tables}),
                dialect,
                on_progress=_progress_publisher(connection_id),
            )
        else:
            enrichment_tables = []
    logger.info("[AI Semantic Agent] Enrichment ready for %d tables", len(enrichment_tables))

    enrichment_by_key = {
        ((e.get("physical_schema") or e.get("schema_name") or ""), e.get("table_name", "")): e
        for e in enrichment_tables
    }
    name_counts = {
        t.table_name.raw_name: sum(other.table_name.raw_name == t.table_name.raw_name for other in raw_schema.tables)
        for t in raw_schema.tables
    }

    table_id_map: dict[tuple[str, str], int] = {}

    for table_meta in raw_schema.tables:
        table_name = table_meta.table_name.raw_name
        identity = (table_meta.schema_name.normalized_name, table_meta.table_name.normalized_name)
        proposal_key = (table_meta.schema_name.raw_name, table_name)
        table_enrichment = enrichment_by_key.get(proposal_key)
        if table_enrichment is None:
            table_enrichment = enrichment_by_key.get(("", table_name), {}) if name_counts[table_name] == 1 else {}
        pk_cols = table_meta.primary_key.constrained_columns if table_meta.primary_key else ()
        pk_col_name = pk_cols[0].raw_name if pk_cols else None
        table_state = existing_state.get((identity[0] or "", identity[1] or ""), {})

        # shortcut: per-table commit below releases the row lock, so re-take it every iteration
        await lock_semantic_database(db, connection_id)
        table_id = await _upsert_semantic_table(
            db=db,
            connection_id=connection_id,
            table_name=table_name,
            enrichment=table_enrichment,
            schema_name=table_meta.schema_name.raw_name,
            schema_key=identity[0],
            table_key=identity[1],
            pk_col=pk_col_name,
            user_id=user_id,
            apply_proposal=not table_state.get("complete", False),
            fill_missing=publish_progress,
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
                apply_proposal=not table_state.get("columns", {}).get(col_meta.column_name.raw_name, False),
                fill_missing=publish_progress,
            )
        await db.commit()
        if publish_progress:
            enrichment_progress.mark_saving(connection_id)

    relationships = await _extract_and_save_relationships(db, connection_id, raw_schema, table_id_map)
    logger.info(
        "[AI Semantic Agent] Extracted %d foreign key relationships for connection_id=%d",
        len(relationships),
        connection_id,
    )

    await db.commit()
    if publish_progress:
        enrichment_progress.finish(connection_id)
    logger.info("[AI Semantic Agent] Canonical schema enrichment completed for connection_id=%d", connection_id)

    review = await pending_review_counts(db, connection_id)
    # Post-commit: notify data leads that a schema review batch is waiting.
    await sync_schema_review_notifications(db, connection_id)
    return {
        "tables": [
            {
                "table_name": t.table_name.raw_name,
                "physical_schema": t.schema_name.raw_name,
                "table_id": table_id_map[(t.schema_name.normalized_name, t.table_name.normalized_name)],
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


async def _upsert_semantic_table(
    db: AsyncSession,
    connection_id: int,
    table_name: str,
    enrichment: dict[str, Any],
    schema_name: str,
    pk_col: str | None,
    user_id: int,
    schema_key: str | None = None,
    table_key: str | None = None,
    apply_proposal: bool = True,
    fill_missing: bool = True,
) -> int:
    """Upsert a table by database and normalized physical schema/name."""
    schema_key = schema_key if schema_key is not None else schema_name
    table_key = table_key if table_key is not None else table_name
    stmt = select(SemanticTableModel).where(
        SemanticTableModel.db_id == connection_id,
        or_(
            and_(
                func.coalesce(SemanticTableModel.table_name_key, SemanticTableModel.table_name) == table_key,
                func.coalesce(SemanticTableModel.physical_schema_key, SemanticTableModel.physical_schema, "")
                == (schema_key or ""),
            ),
            and_(
                SemanticTableModel.table_name_key.is_(None),
                SemanticTableModel.physical_schema_key.is_(None),
                SemanticTableModel.table_name == table_name,
                func.coalesce(SemanticTableModel.physical_schema, "") == (schema_name or ""),
            ),
        ),
    )
    rows = (await db.execute(stmt)).scalars().all()
    if len(rows) > 1:
        raise ValueError(f"Ambiguous legacy table identity: {schema_name}.{table_name}")
    existing = rows[0] if rows else None

    if existing:
        if apply_proposal:
            _apply_proposal_values(
                existing,
                table_name,
                enrichment.get("business_name", table_name),
                enrichment.get("description", ""),
                fill_missing,
            )
        existing.physical_schema_key = schema_key
        existing.table_name_key = table_key
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
        physical_schema_key=schema_key,
        table_name_key=table_key,
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
    apply_proposal: bool = True,
    fill_missing: bool = True,
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
        if apply_proposal:
            _apply_proposal_values(
                existing,
                col_name,
                enrichment.get("business_name", col_name),
                enrichment.get("description", ""),
                fill_missing,
            )
        existing.is_time_dimension = is_time
        existing.data_type = data_type
        existing.is_primary_key = col_meta.primary_key
        existing.is_foreign_key = fk_reference is not None
        existing.fk_target_table = fk_reference[0] if fk_reference else None
        existing.fk_target_column = fk_reference[1] if fk_reference else None
        existing.is_nullable = col_meta.nullable
        if col_meta.sample_values:
            existing.allowed_values = list(col_meta.sample_values)
            existing.allowed_values_complete = True
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
            "from_table_id": table_id_map[(table.schema_name.normalized_name, table.table_name.normalized_name)],
            "to_table_id": table_id_map[(fk.referred_schema.normalized_name, fk.referred_table.normalized_name)],
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

    # shortcut: prod schema has no FK on notifications.db_id, so delete explicitly
    await db.execute(delete(NotificationModel).where(NotificationModel.db_id == db_id))
    await db.delete(sem_db)
    await db.commit()
    return True
