"""Match batch model replies to server-owned candidate identities."""

from __future__ import annotations

from typing import Any


def correlate(records: list[dict[str, Any]], expected: set[str]) -> dict[str, dict[str, Any] | None]:
    """Ignore unassigned IDs and invalidate duplicate/missing replies for their own KPI."""
    matched: dict[str, dict[str, Any] | None] = dict.fromkeys(expected)
    seen: set[str] = set()
    for record in records:
        identity = record.get("candidate_id")
        if not isinstance(identity, str) or identity not in expected:
            continue
        matched[identity] = None if identity in seen else record
        seen.add(identity)
    return matched
