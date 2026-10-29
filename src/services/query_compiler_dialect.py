"""Dialect-aware time bucket SQL rendering shared across all query compiler paths."""

from __future__ import annotations

from src.services.semantic_compile_error import SemanticCompileError

SUPPORTED_TIME_GRAINS = frozenset({"day", "week", "month", "quarter", "year"})

_MYSQL_GRAIN_FORMATS = {
    "day": "%Y-%m-%d",
    "week": "%x-W%v",
    "month": "%Y-%m",
    "year": "%Y",
}

_SQLITE_GRAIN_FORMATS = {
    "day": "%Y-%m-%d",
    "month": "%Y-%m",
    "year": "%Y",
}


def time_bucket_sql(column_sql: str, grain: str, dialect: str, data_type: str) -> str:
    """Render a dialect-specific time bucket expression for a column SQL fragment."""
    normalized_grain = grain.strip().casefold()
    if normalized_grain not in SUPPORTED_TIME_GRAINS:
        raise SemanticCompileError(
            "INVALID_TIME_GRAIN",
            f"Unsupported time grain: {grain}",
            {"grain": grain, "dialect": dialect, "data_type": data_type},
        )
    normalized_dialect = dialect.strip().casefold()
    if normalized_dialect == "sqlite":
        return _sqlite_time_bucket(column_sql, normalized_grain)
    if normalized_dialect == "mysql":
        return _mysql_time_bucket(column_sql, normalized_grain)
    return _postgres_time_bucket(column_sql, normalized_grain, data_type)


def _postgres_time_bucket(column_sql: str, grain: str, data_type: str) -> str:
    """Render PostgreSQL DATE_TRUNC bucket, normalizing TIMESTAMPTZ columns to UTC."""
    if _is_timezone_aware_type(data_type):
        return f"DATE_TRUNC('{grain}', {column_sql} AT TIME ZONE 'UTC')"
    return f"DATE_TRUNC('{grain}', {column_sql})"


def _is_timezone_aware_type(data_type: str) -> bool:
    """Return True when the declared SQL type carries a time zone."""
    folded = (data_type or "").strip().casefold()
    if "without time zone" in folded:
        return False
    return "timestamptz" in folded or "with time zone" in folded or folded.endswith("tz")


def _mysql_time_bucket(column_sql: str, grain: str) -> str:
    """Render MySQL string label for day, ISO week, month, quarter, or year."""
    if grain == "quarter":
        return f"CONCAT(YEAR({column_sql}), '-Q', QUARTER({column_sql}))"
    fmt = _MYSQL_GRAIN_FORMATS[grain]
    return f"DATE_FORMAT({column_sql}, '{fmt}')"


def _sqlite_time_bucket(column_sql: str, grain: str) -> str:
    """Render SQLite string label for day, ISO week, month, quarter, or year."""
    if grain == "week":
        iso_thursday = f"date({column_sql}, 'weekday 0', '-3 days')"
        iso_year = f"strftime('%Y', {iso_thursday})"
        iso_week = f"printf('%02d', (cast(strftime('%j', {iso_thursday}) as integer) - 1) / 7 + 1)"
        return f"{iso_year} || '-W' || {iso_week}"
    if grain == "quarter":
        return f"strftime('%Y', {column_sql}) || '-Q' || ((cast(strftime('%m', {column_sql}) as integer) - 1) / 3 + 1)"
    fmt = _SQLITE_GRAIN_FORMATS[grain]
    return f"strftime('{fmt}', {column_sql})"


__all__ = ["SUPPORTED_TIME_GRAINS", "time_bucket_sql"]
