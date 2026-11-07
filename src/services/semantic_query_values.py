"""Resolve user filter values using approved semantic metadata."""

from __future__ import annotations

import math
from typing import Any

from src.models.schemas import SemanticQueryFilter
from src.services.semantic_value_mappings import (
    approved_mapping_candidates,
    sample_value_candidates,
    scalar_value_key,
)


def filter_value_resolution(item: SemanticQueryFilter, column: dict[str, Any]) -> str:
    """Classify a categorical filter as valid, ambiguous, unmapped, or malformed."""
    if item.operator in {"is_null", "is_not_null"}:
        return "valid"
    if not _is_categorical(column):
        return "valid" if _scalar_matches_type(item.value, column) else "malformed"
    values = item.value if item.operator in {"in", "not_in"} and isinstance(item.value, list) else [item.value]
    if any(
        not isinstance(value, (str, int, float, bool)) or isinstance(value, float) and not math.isfinite(value)
        for value in values
    ):
        return "malformed"
    outcomes = [
        len(
            {
                scalar_value_key(candidate)
                for candidate in (
                    *approved_mapping_candidates(value, {**column, "allowed_values": []}),
                    *sample_value_candidates(value, column),
                )
            }
        )
        for value in values
    ]
    if any(count > 1 for count in outcomes):
        return "ambiguous"
    return "unmapped" if not outcomes or any(count == 0 for count in outcomes) else "valid"


def _scalar_matches_type(value: Any, column: dict[str, Any]) -> bool:
    """Keep noncategorical filter scalars aligned with their declared SQL type."""
    dtype = str(column.get("data_type", "")).upper()
    if any(marker in dtype for marker in ("BOOL",)):
        return isinstance(value, bool)
    if any(marker in dtype for marker in ("INT", "NUMERIC", "DECIMAL", "FLOAT", "DOUBLE", "REAL", "BIT")):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if any(marker in dtype for marker in ("DATE", "TIME")):
        return isinstance(value, str)
    return True


def _is_categorical(column: dict[str, Any]) -> bool:
    """Identify categorical text fields for approved mapping resolution."""
    dtype = str(column.get("data_type", "")).upper()
    return any(kind in dtype for kind in ("CHAR", "TEXT", "ENUM"))


def _normalize_filter_values(
    filters: list[SemanticQueryFilter], catalog: dict[str, Any]
) -> list[SemanticQueryFilter] | None:
    """Resolve approved labels and validate scalar values using declared SQL types."""
    columns = {item["column_id"]: item for item in catalog.get("filter_columns", [])}
    result = []
    for item in filters:
        column = columns.get(item.column_id)
        if column is None:
            return None
        if item.operator in {"is_null", "is_not_null"}:
            result.append(item)
            continue
        if not _is_categorical(column):
            values = item.value if item.operator in {"in", "not_in"} and isinstance(item.value, list) else [item.value]
            if any(not _scalar_matches_type(value, column) for value in values):
                return None
            result.append(item)
            continue
        values = item.value if item.operator in {"in", "not_in"} and isinstance(item.value, list) else [item.value]
        resolved = [_approved_value(value, column) for value in values]
        if not resolved or any(value is None for value in resolved):
            return None
        normalized = resolved if item.operator in {"in", "not_in"} else resolved[0]
        result.append(item.model_copy(update={"value": normalized}))
    return result


def _approved_value(value: Any, column: dict[str, Any]) -> Any | None:
    """Resolve an approved label while preserving the mapped JSON scalar type."""
    mapping_candidates = approved_mapping_candidates(value, {**column, "allowed_values": []})
    sample_candidates = sample_value_candidates(value, column)
    candidates = {scalar_value_key(candidate): candidate for candidate in (*mapping_candidates, *sample_candidates)}
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    return None
