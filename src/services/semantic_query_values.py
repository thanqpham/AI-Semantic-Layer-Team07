"""Resolve user filter values using approved semantic metadata."""

from __future__ import annotations

from typing import Any

from src.models.schemas import SemanticQueryFilter
from src.services.metric_knowledge import normalized_text


def _normalize_filter_values(
    filters: list[SemanticQueryFilter], catalog: dict[str, Any]
) -> list[SemanticQueryFilter] | None:
    """Resolve categorical labels through approved values and mappings only."""
    columns = {item["column_id"]: item for item in catalog.get("filter_columns", [])}
    result = []
    for item in filters:
        column = columns.get(item.column_id)
        if column is None:
            return None
        dtype = str(column.get("data_type", "")).upper()
        if item.operator in {"is_null", "is_not_null"} or not any(t in dtype for t in ("CHAR", "TEXT", "ENUM")):
            result.append(item)
            continue
        values = item.value if item.operator in {"in", "not_in"} and isinstance(item.value, list) else [item.value]
        resolved = [_approved_value(value, column) for value in values]
        if not resolved or any(value is None for value in resolved):
            return None
        result.append(item.model_copy(update={"value": resolved if item.operator in {"in", "not_in"} else resolved[0]}))
    return result


def _approved_value(value: Any, column: dict[str, Any]) -> Any | None:
    """Resolve exact normalized labels only when they map to one approved value."""
    if not isinstance(value, str):
        return None
    key = normalized_text(value.strip())
    candidates = {str(v) for v in column.get("allowed_values", []) if normalized_text(str(v).strip()) == key}
    for mapping in column.get("_approved_mappings", column.get("allowed_value_mappings", [])):
        if key in {normalized_text(str(mapping.get(field, "")).strip()) for field in ("db_value", "business_value")}:
            candidates.add(str(mapping.get("db_value", "")))
    return next(iter(candidates)) if len(candidates) == 1 else None
