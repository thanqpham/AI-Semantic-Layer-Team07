"""Redact benchmark artifacts before persistence."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

SECRET_KEYS = frozenset({"conn_url", "conn_url_enc", "password", "token", "api_key", "authorization"})
STATE_ALLOWLIST = frozenset(
    {
        "intent",
        "error",
        "semantic_layer_id",
        "hitl_approved",
        "suggestion_action",
        "dedupe_performed",
        "introspection_warnings",
        "clarification",
        "interpretation",
    }
)


def redact_value(value: Any, key: str | None = None) -> Any:
    """Return a JSON-safe representation without secret or row-level values."""
    if key and _is_secret_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {str(k): redact_value(v, str(k)) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item) for item in value[:20]]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)[:500]


def redact_state_delta(value: Mapping[str, Any]) -> dict[str, Any]:
    """Keep only safe, observable state fields from a node update."""
    return {key: redact_value(item, key) for key, item in value.items() if key in STATE_ALLOWLIST}


def digest_observation(value: Any) -> str:
    """Build a stable digest without persisting raw observations."""
    rendered = repr(redact_value(value)).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()[:16]


def _is_secret_key(key: str) -> bool:
    normalized = key.casefold().replace("-", "_")
    return normalized in SECRET_KEYS or normalized.endswith("_token") or normalized.endswith("_secret")
