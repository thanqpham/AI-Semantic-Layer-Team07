"""Bounded observed-value proposals isolated from approved schema metadata."""

import hashlib
import json

from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel


def proposal_fingerprint(
    database: SemanticDatabaseModel, table: SemanticTableModel, column: SemanticColumnModel
) -> str:
    """Bind proposals to their physical identity and current semantic state."""
    data = [
        database.id,
        database.schema_fingerprint,
        table.id,
        table.physical_schema,
        table.table_name,
        column.id,
        column.column_name,
        column.data_type,
        column.is_primary_key,
        column.is_foreign_key,
        column.fk_target_table,
        column.fk_target_column,
        column.allowed_values,
    ]
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def queue_discovery(db_id: int, *, refresh_dismissed: bool = False) -> bool:
    """Keep the legacy hook inert; categorical values must come from metadata or manual input."""
    return False
