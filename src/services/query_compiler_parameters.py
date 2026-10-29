"""Column-type-driven filter parameter coercion and binding for the semantic compiler."""

from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from src.services.semantic_compile_error import SemanticCompileError

_INT_PATTERN = re.compile(r"^[+-]?\d+$")
_INT_TYPES = frozenset(
    {
        "INTEGER",
        "INT",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "MEDIUMINT",
        "SERIAL",
        "BIGSERIAL",
        "SMALLSERIAL",
        "INT2",
        "INT4",
        "INT8",
        "SIGNED",
        "UNSIGNED",
    }
)
_DECIMAL_TYPES = frozenset({"DECIMAL", "NUMERIC", "DEC", "NUMBER", "MONEY", "SMALLMONEY"})
_FLOAT_TYPES = frozenset({"FLOAT", "REAL", "DOUBLE", "DOUBLE PRECISION", "FLOAT4", "FLOAT8"})
_BOOL_TYPES = frozenset({"BOOLEAN", "BOOL", "BIT"})
_DATETIME_TYPES = frozenset(
    {
        "DATETIME",
        "TIMESTAMP",
        "TIMESTAMPTZ",
        "TIMESTAMP WITH TIME ZONE",
        "TIMESTAMP WITHOUT TIME ZONE",
        "SMALLDATETIME",
    }
)


def coerce_filter_value(value: Any, data_type: str, dialect: str) -> Any:
    """Coerce a scalar filter value strictly according to column data_type and dialect."""
    base_type = _normalize_base_type(data_type)
    if not base_type:
        return _coerce_untyped(value, data_type, dialect)
    if base_type in _INT_TYPES:
        return _coerce_integer(value, data_type, dialect)
    if base_type in _DECIMAL_TYPES:
        return _coerce_decimal(value, data_type, dialect)
    if base_type in _FLOAT_TYPES:
        return _coerce_float(value, data_type, dialect)
    if base_type in _BOOL_TYPES:
        return _coerce_boolean(value, data_type, dialect)
    if base_type == "DATE":
        return _coerce_date(value, data_type, dialect)
    if base_type in _DATETIME_TYPES or "TIMESTAMP" in base_type or "DATETIME" in base_type:
        return _coerce_datetime(value, data_type, dialect)
    return _coerce_text(value, data_type, dialect)


def coerce_sequence_filter_values(
    value: Any,
    data_type: str,
    dialect: str,
    *,
    expected_length: int | None = None,
) -> list[Any]:
    """Validate a list/tuple filter value and coerce every element by column type."""
    if not isinstance(value, (list, tuple)) or not value:
        raise _invalid_filter_error(data_type, dialect, value)
    if expected_length is not None and len(value) != expected_length:
        raise _invalid_filter_error(data_type, dialect, value)
    return [coerce_filter_value(element, data_type, dialect) for element in value]


def validate_null_filter_value(value: Any, data_type: str, dialect: str) -> None:
    """Reject non-null filter payloads for IS NULL and IS NOT NULL operators."""
    if value is not None:
        raise _invalid_filter_error(data_type, dialect, value)


def bind_coerced_parameter(
    value: Any,
    data_type: str,
    dialect: str,
    parameters: dict[str, Any],
    prefix: str,
) -> str:
    """Coerce a scalar filter value and bind it into the parameter dictionary."""
    coerced = coerce_filter_value(value, data_type, dialect)
    key = f"{prefix}_{len(parameters)}"
    parameters[key] = coerced
    return _placeholder(key, coerced, dialect)


def bind_coerced_sequence(
    value: Any,
    data_type: str,
    dialect: str,
    parameters: dict[str, Any],
    prefix: str,
    *,
    expected_length: int | None = None,
) -> list[str]:
    """Coerce a sequence of filter values and bind each element into parameters."""
    coerced_items = coerce_sequence_filter_values(
        value,
        data_type,
        dialect,
        expected_length=expected_length,
    )
    placeholders: list[str] = []
    for item in coerced_items:
        key = f"{prefix}_{len(parameters)}"
        parameters[key] = item
        placeholders.append(_placeholder(key, item, dialect))
    return placeholders


def _placeholder(key: str, value: Any, dialect: str) -> str:
    if dialect == "sqlite" and isinstance(value, Decimal):
        return f"CAST(:{key} AS NUMERIC)"
    return f":{key}"


def _normalize_base_type(data_type: str | None) -> str:
    """Extract the uppercase base SQL type name without parenthesized modifiers."""
    return (data_type or "").strip().upper().split("(", 1)[0].strip()


def _coerce_untyped(value: Any, data_type: str, dialect: str) -> Any:
    if value is not None and isinstance(value, (str, int, float, bool, Decimal, date, datetime)):
        return value
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_text(value: Any, data_type: str, dialect: str) -> str:
    if isinstance(value, str):
        return value
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_integer(value: Any, data_type: str, dialect: str) -> int:
    if isinstance(value, bool):
        raise _invalid_filter_error(data_type, dialect, value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if _INT_PATTERN.fullmatch(stripped):
            return int(stripped, 10)
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_decimal(value: Any, data_type: str, dialect: str) -> Decimal:
    if isinstance(value, bool):
        raise _invalid_filter_error(data_type, dialect, value)
    if isinstance(value, Decimal):
        if value.is_finite():
            return value
        raise _invalid_filter_error(data_type, dialect, value)
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if math.isfinite(value):
            return Decimal(str(value))
        raise _invalid_filter_error(data_type, dialect, value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation as exc:
            raise _invalid_filter_error(data_type, dialect, value) from exc
        if parsed.is_finite():
            return parsed
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_float(value: Any, data_type: str, dialect: str) -> float:
    if isinstance(value, bool):
        raise _invalid_filter_error(data_type, dialect, value)
    if isinstance(value, (int, float, Decimal)):
        num = float(value)
        if math.isfinite(num):
            return num
        raise _invalid_filter_error(data_type, dialect, value)
    if isinstance(value, str) and value.strip():
        try:
            num = float(value.strip())
        except ValueError as exc:
            raise _invalid_filter_error(data_type, dialect, value) from exc
        if math.isfinite(num):
            return num
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_boolean(value: Any, data_type: str, dialect: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        folded = value.strip().casefold()
        if folded in {"true", "1"}:
            return True
        if folded in {"false", "0"}:
            return False
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_date(value: Any, data_type: str, dialect: str) -> date:
    if type(value) is date:
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) == 10:
            try:
                return date.fromisoformat(stripped)
            except ValueError as exc:
                raise _invalid_filter_error(data_type, dialect, value) from exc
    raise _invalid_filter_error(data_type, dialect, value)


def _coerce_datetime(value: Any, data_type: str, dialect: str) -> date | datetime:
    if isinstance(value, datetime) or type(value) is date:
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if len(stripped) == 10:
            try:
                return date.fromisoformat(stripped)
            except ValueError as exc:
                raise _invalid_filter_error(data_type, dialect, value) from exc
        iso_text = f"{stripped[:-1]}+00:00" if stripped.endswith(("Z", "z")) else stripped
        try:
            return datetime.fromisoformat(iso_text)
        except ValueError as exc:
            raise _invalid_filter_error(data_type, dialect, value) from exc
    raise _invalid_filter_error(data_type, dialect, value)


def _invalid_filter_error(data_type: str, dialect: str, value: Any) -> SemanticCompileError:
    return SemanticCompileError(
        "INVALID_FILTER_VALUE",
        f"Filter value is incompatible with column type '{data_type or 'UNKNOWN'}'",
        {
            "data_type": data_type or "",
            "dialect": dialect,
            "value_type": type(value).__name__,
        },
    )
