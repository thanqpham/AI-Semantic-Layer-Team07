"""Deterministic data-hygiene filters for canonical metric definitions.

Test/bot rows must never count toward business metrics. Rather than trusting
the LLM to declare these exclusions (three prompt regimes all failed), the
resolver attaches them deterministically at save time.
"""

from __future__ import annotations

import re
from collections.abc import Sequence, Set

from src.models.metric_definition import MetricFilter

_HYGIENE_FLAG_PATTERN = re.compile(r"^is_(test|bot)_")
_HYGIENE_TYPES = frozenset({"BOOLEAN", "BOOL"})


def hygiene_flag_filters(columns: Sequence[tuple[str, str]], existing_fields: Set[str]) -> list[MetricFilter]:
    """Return one eq-False filter per un-referenced test/bot boolean column."""
    taken = {field.lower() for field in existing_fields}
    return [
        MetricFilter(field=name, operator="eq", value=False)
        for name, data_type in columns
        if _HYGIENE_FLAG_PATTERN.match(name) and data_type.upper() in _HYGIENE_TYPES and name.lower() not in taken
    ]
