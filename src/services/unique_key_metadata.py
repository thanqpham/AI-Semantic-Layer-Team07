"""Read UNIQUE-key metadata from a SQLAlchemy Inspector without touching row data."""

from typing import Any

from src.models.schema_metadata import Identifier, SchemaDialect


def build_unique_keys(
    inspector: Any, table_name: str, known_columns: set[str], dialect: SchemaDialect
) -> tuple[tuple[Identifier, ...], ...]:
    """Return complete UNIQUE constraints and non-partial unique indexes as identifier tuples."""
    keys: list[tuple[Identifier, ...]] = []
    for names in _unique_column_sets(inspector, table_name):
        if names and all(name in known_columns for name in names):
            key = tuple(Identifier.from_raw(name, dialect) for name in names)
            if key not in keys:
                keys.append(key)
    return tuple(keys)


def _unique_column_sets(inspector: Any, table_name: str) -> list[list[str]]:
    column_sets: list[list[str]] = []
    try:
        constraints = inspector.get_unique_constraints(table_name)
        column_sets.extend(list(item.get("column_names") or []) for item in constraints)
    except NotImplementedError:
        pass
    column_sets.extend(
        list(item.get("column_names") or [])
        for item in inspector.get_indexes(table_name)
        if item.get("unique") and not _is_partial(item)
    )
    return column_sets


def _is_partial(index: Any) -> bool:
    """A partial unique index only constrains the rows its predicate selects."""
    options = index.get("dialect_options") or {}
    return any(key.endswith("_where") and value for key, value in options.items())
