"""Versioned trace accumulation for deterministic semantic compilation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

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
