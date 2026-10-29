"""Versioned trace accumulation for deterministic semantic compilation."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from src.models.db import SemanticMetricModel
from src.models.metric_definition import MetricDefinition

TRACE_SCHEMA_VERSION = 1


class CompileTraceBuilder:
    """Collect trace fields as compile phases complete; snapshots are isolated."""

    def __init__(self) -> None:
        self._steps: list[str] = []
        self._fields: dict[str, Any] = {}

    @property
    def completed_steps(self) -> tuple[str, ...]:
        """Return the compile phases that finished without an error."""
        return tuple(self._steps)

    def step(self, name: str) -> None:
        """Mark one named compile phase as completed, in call order."""
        self._steps.append(name)

    def record(self, **fields: Any) -> None:
        """Store trace fields; a repeated key overwrites its earlier value."""
        self._fields.update(fields)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-safe deep copy of everything recorded so far."""
        return {"schema_version": TRACE_SCHEMA_VERSION, "completed_steps": list(self._steps), **deepcopy(self._fields)}


def record_loaded_trace(
    trace: CompileTraceBuilder,
    metrics: list[SemanticMetricModel],
    definitions: list[MetricDefinition],
    limit: int,
) -> None:
    trace.record(
        metrics=[
            {
                "id": metric.id,
                "name": metric.name,
                "version": metric.version,
                "grain_column_ids": list(definition.metric.grain.column_ids),
            }
            for metric, definition in zip(metrics, definitions, strict=True)
        ],
        effective_limit=limit,
    )
    trace.step("load_metadata")


def trace_join_path(base_name: str, joins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"relationship_id": join["relationship_id"], "from_table": base_name, "to_table": join["table_name"]}
        for join in joins
    ]


def trace_filters(definitions: list[MetricDefinition], runtime_filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = [
        {"column_id": item.column_id, "operator": item.operator, "scope": "metric"}
        for definition in definitions
        for item in definition.metric.filters
        if item.column_id is not None
    ] + [{"column_id": item["column_id"], "operator": item["operator"], "scope": "runtime"} for item in runtime_filters]
    return list({json.dumps(entry, sort_keys=True): entry for entry in entries}.values())
