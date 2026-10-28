"""Bounded read-only discovery of categorical values."""

from sqlalchemy import Column, MetaData, Table, select
from sqlalchemy.sql import Select
from sqlalchemy.sql.elements import quoted_name


def build_probe_statement(schema: str | None, table: str, column_name: str) -> Select:
    """Quote metadata identifiers and probe one column for up to 21 distinct values."""
    source = Table(quoted_name(table, True), MetaData(), Column(quoted_name(column_name, True)),
                   schema=quoted_name(schema, True) if schema else None)
    field = source.c[column_name]
    return select(field).distinct().where(field.is_not(None)).limit(21)
