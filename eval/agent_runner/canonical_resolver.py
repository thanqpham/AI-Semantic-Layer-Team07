"""Map agent-emitted physical identifiers onto golden canonical names.

Only exact, evidence-backed mappings are used: the golden registry's declared
``table_mapping``/``field`` values and the metric-case provenance from Stage 3.
Unmapped values stay raw (fail-open-to-mismatch) and are logged for the run
manifest, so raw agent output always stays reconstructible.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from eval.dataset.models import CanonicalEntityDefinition

if TYPE_CHECKING:
    from eval.dataset.loader import DomainDataset


class CanonicalResolver:
    """Resolve physical table/column/metric identifiers to canonical names."""

    def __init__(
        self,
        entities: Mapping[str, CanonicalEntityDefinition],
        metric_names_by_id: Mapping[int, str],
    ) -> None:
        """Index reverse mappings; ambiguous keys are dropped fail-closed."""
        self._entity_by_table: dict[str, str] = {}
        self._columns_by_table: dict[str, dict[str, str]] = {}
        self._collisions: set[str] = set()
        self._metrics = dict(metric_names_by_id)
        self._resolutions: list[dict[str, str]] = []
        self._unresolved: list[dict[str, str]] = []
        for entity in entities.values():
            self._index_entity(entity)

    @classmethod
    def from_dataset(cls, dataset: DomainDataset, metric_ids: Mapping[str, int]) -> CanonicalResolver:
        """Build from a loaded dataset plus persisted metric ids per case id."""
        names: dict[int, str] = {}
        for case in dataset.metric_cases:
            if case.expected_metric is None:
                continue
            persisted = metric_ids.get(case.case_id)
            if persisted is not None:
                names[persisted] = case.expected_metric.name
        return cls(dataset.canonical_entities, names)

    def _index_entity(self, entity: CanonicalEntityDefinition) -> None:
        """Add one entity's reverse mappings; collisions void the shared key."""
        table = entity.table_mapping
        existing = self._entity_by_table.get(table)
        if existing is not None and existing != entity.entity:
            self._collisions.add(table)
            self._entity_by_table.pop(table, None)
            self._columns_by_table.pop(table, None)
            return
        self._entity_by_table[table] = entity.entity
        self._columns_by_table[table] = _column_index(entity)

    def resolve_entity(self, table_name: str) -> str:
        """Map one physical table to its canonical entity name (raw on miss)."""
        canonical = self._entity_by_table.get(table_name)
        if canonical is None:
            self._miss("entity", table_name)
            return table_name
        if canonical != table_name:
            self._log("entity", table_name, canonical)
        return canonical

    def resolve_column(self, table_name: str, column_name: str) -> str:
        """Map one physical column to its canonical dimension name (raw on miss)."""
        canonical = self._columns_by_table.get(table_name, {}).get(column_name)
        if canonical is None:
            self._miss("column", f"{table_name}.{column_name}")
            return column_name
        if canonical != column_name:
            self._log("column", f"{table_name}.{column_name}", canonical)
        return canonical

    def resolve_dimension(self, dotted: str) -> str:
        """Map one ``table.field`` name to canonical ``entity.name`` (raw on miss)."""
        table, separator, field = dotted.partition(".")
        if not separator or not field:
            return dotted
        canonical = self._columns_by_table.get(table, {}).get(field)
        if canonical is None:
            self._miss("column", dotted)
            return dotted
        entity = self._entity_by_table.get(table, table)
        mapped = f"{entity}.{canonical}"
        if mapped != dotted:
            self._log("column", dotted, mapped)
        return mapped

    def resolve_metric_id(self, metric_id: int) -> str:
        """Map one persisted metric id to its golden canonical name."""
        canonical = self._metrics.get(metric_id)
        if canonical is None:
            self._miss("metric", f"metric_{metric_id}")
            return f"metric_{metric_id}"
        self._log("metric", f"metric_{metric_id}", canonical)
        return canonical

    @property
    def resolutions(self) -> tuple[dict[str, str], ...]:
        """Audit log of every successful raw-to-canonical mapping."""
        return tuple(self._resolutions)

    @property
    def unresolved(self) -> tuple[dict[str, str], ...]:
        """Audit log of values that stayed raw (fail-open-to-mismatch)."""
        return tuple(self._unresolved)

    def _log(self, kind: str, raw: str, canonical: str) -> None:
        self._resolutions.append({"kind": kind, "from": raw, "to": canonical})

    def _miss(self, kind: str, value: str) -> None:
        self._unresolved.append({"kind": kind, "value": value})


def _column_index(entity: CanonicalEntityDefinition) -> dict[str, str]:
    """Reverse-map physical fields to canonical dimension names; collisions drop."""
    index: dict[str, str] = {}
    for dimension in entity.dimensions:
        existing = index.get(dimension.field)
        if existing is not None and existing != dimension.name:
            del index[dimension.field]
            continue
        index[dimension.field] = dimension.name
    return index
