"""Select safe bridge evidence without deciding a metric's join path."""

from itertools import combinations
from typing import Any

from src.services.relationship_runtime import relationship_paths


def table_key(table: Any) -> str:
    """Identify a table using its physical schema when present."""
    name = table.get("table_name") if isinstance(table, dict) else table.table_name
    schema = table.get("physical_schema") if isinstance(table, dict) else getattr(table, "physical_schema", None)
    return f"{schema}.{name}" if schema else name


def _selected_tables(tables: list[Any], selected: set[str]) -> list[Any]:
    names = [table.table_name for table in tables]
    return [
        t for t in tables if table_key(t) in selected or (t.table_name in selected and names.count(t.table_name) == 1)
    ]


def expand_bridges(tables: list[Any], relationships: list[Any], selected: set[str]) -> tuple[set[str], str | None]:
    """Include safe path alternatives so later validation can detect ambiguity."""
    chosen = _selected_tables(tables, selected)
    by_id = {table.id: table for table in tables}
    included = {table.id for table in chosen}
    eligible = {t.id for t in tables if getattr(t, "review_status", None) == "approved"} | included
    relationships = [r for r in relationships if r.from_entity_id in eligible and r.to_entity_id in eligible]
    for first, second in combinations(chosen, 2):
        paths = relationship_paths(relationships, first.id, second.id)
        paths += relationship_paths(relationships, second.id, first.id)
        if not paths:
            paths = relationship_paths(relationships, first.id, second.id, allow_fanout=True)
        unique = {tuple(sorted(step.id for step in path)): path for path in paths}
        for path in unique.values():
            for step in path:
                included.update((step.from_entity_id, step.to_entity_id))
    if any(table_id not in by_id for table_id in included):
        return set(), "Đường liên kết chứa bảng ngoài phạm vi schema."
    names = [by_id[table_id].table_name for table_id in included]
    if len(names) != len(set(names)):
        return set(), "Các bảng liên kết trùng tên; hãy chọn phạm vi schema rõ ràng hơn."
    return {table_key(by_id[table_id]) for table_id in included}, None
