"""Shared result contract for semantic query compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CompiledQuery:
    """Hold compiled SQL, bound values, and observable metadata."""

    sql: str
    parameters: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
