"""Conservative eligibility and local screening for observed categories."""

import re
from typing import Any

import sqlglot
from sqlalchemy.exc import SQLAlchemyError
from sqlglot import exp

_CATEGORY = re.compile(r"(?:^|_)(?:status|state|type|category|method|channel|stage|region|zone)(?:_|$)", re.I)
_SENSITIVE_COLUMN = re.compile(
    r"(?:^|_)(?:id|key|email|phone|address|name|note|comment|description|password|secret|token|hash|"
    r"medical|health|diagnosis|disease|patient|salary|income|ip|url)(?:_|$)", re.I
)
_VALUE = re.compile(r"^[A-Za-zÀ-ỹ][A-Za-zÀ-ỹ0-9 _-]{0,63}$")
_SENSITIVE_VALUE = re.compile(
    r"(?:password|secret|token|diagnosis|patient|medical|disease|cancer|hiv|ignore |instruction|system prompt)", re.I
)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def eligible_column(column: Any) -> bool:
    """Select only named categorical text columns without known sensitive roles."""
    name, dtype = column.column_name, column.data_type.upper()
    return bool(
        not column.is_primary_key and not column.is_foreign_key and _CATEGORY.search(name)
        and not _SENSITIVE_COLUMN.search(name) and any(t in dtype for t in ("CHAR", "TEXT", "ENUM"))
    )


def safe_observed_values(values: list[Any]) -> list[Any] | None:
    """Discard the entire sample if it is ambiguous or exceeds its bounded domain."""
    if not values or len(values) > 20:
        return None
    if any(not _safe_value(value) for value in values):
        return None
    return sorted(values, key=str)


def safe_declared_values(values: list[Any]) -> list[Any] | None:
    """Keep the schema's order when accepting an enum domain."""
    if not values or len(values) > 20 or any(not _safe_value(value) for value in values):
        return None
    return list(values)


def _safe_value(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, int):
        return 0 <= value <= 999
    if not isinstance(value, str):
        return False
    if value.isascii() and value.isdigit():
        return len(value) <= 3
    return bool(_VALUE.fullmatch(value) and not _SENSITIVE_VALUE.search(value)
                and not _UUID.fullmatch(value) and not _looks_like_person_name(value))


def _looks_like_person_name(value: str) -> bool:
    words = value.split()
    # shortcut: blocks title-cased multiword names; upgrade if a local PII classifier is approved.
    return 2 <= len(words) <= 4 and all(word.istitle() for word in words)


def declared_check_values(constraints: list[dict[str, Any]], column_name: str) -> list[Any] | None:
    """Accept only a single direct column IN literal CHECK constraint."""
    matches = []
    for check in constraints:
        try:
            node = sqlglot.parse_one(check.get("sqltext", ""))
            while isinstance(node, exp.Paren):
                node = node.this
            if not isinstance(node, exp.In) or not isinstance(node.this, exp.Column):
                continue
            if node.this.table or node.this.name != column_name or not node.expressions:
                continue
            values = [item.this for item in node.expressions if isinstance(item, exp.Literal) and item.is_string]
            if len(values) != len(node.expressions):
                continue
            safe = safe_observed_values(values)
            if safe:
                matches.append(safe)
        except (sqlglot.errors.ParseError, ValueError, TypeError):
            continue
    return matches[0] if len(matches) == 1 else None


def inspect_declared_checks(inspector: Any, table_name: str, schema: str | None = None) -> list[dict[str, Any]]:
    """Read optional schema constraints without interpreting raw DB errors."""
    try:
        return list(inspector.get_check_constraints(table_name, schema=schema))
    except (SQLAlchemyError, NotImplementedError, AttributeError):
        return []
