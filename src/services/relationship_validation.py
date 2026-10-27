"""Metadata-only relationship validation and safe SQL previews."""

import hashlib
import json
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlglot import exp

from src.models.db import (
    ImportedSchemaModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.relationship_review import RelationshipDraft


def invalid(code: str, message: str, pair_index: int | None = None) -> None:
    """Raise a structured validation error identifying the offending pair."""
    raise HTTPException(
        422, detail={"errors": [{"code": code, "pair_index": pair_index, "field": "column_pairs", "message": message}]}
    )


async def endpoints(db: AsyncSession, db_id: int, draft: RelationshipDraft) -> tuple:
    """Resolve endpoint IDs strictly inside the requested database."""
    tables = []
    for entity_id in (draft.from_entity_id, draft.to_entity_id):
        table = await db.get(SemanticTableModel, entity_id)
        if table is None or table.db_id != db_id:
            invalid("FOREIGN_TABLE", "Table does not belong to this database")
        columns = list(
            (await db.scalars(select(SemanticColumnModel).where(SemanticColumnModel.table_id == entity_id))).all()
        )
        tables.append((table, columns))
    return tuple(tables)


def family(value: str) -> str | None:
    """Normalize only equality-compatible metadata type families."""
    value = value.lower().strip()
    for name, pattern in (
        ("integer", r"^(smallint|bigint|integer|int\b)"),
        ("text", r"^(varchar|character varying|char\b|text)"),
    ):
        if re.match(pattern, value):
            return name
    return (
        value
        if re.match(
            r"^(numeric|decimal|float|double|real|boolean|bool|uuid|date|time|timestamp|datetime|binary|varbinary)\b",
            value,
        )
        else None
    )


def column_sql(table: SemanticTableModel, column: SemanticColumnModel, dialect: str) -> str:
    """Render a qualified column through the compiler's SQL AST library."""
    return exp.column(column.column_name, table=table.table_name, db=table.physical_schema, quoted=True).sql(
        dialect=dialect
    )


async def validate_relationship(
    db: AsyncSession, db_id: int, draft: RelationshipDraft, *, approval: bool = False
) -> dict:
    """Validate ordered pairs and cardinality without querying customer data."""
    if not draft.column_pairs:
        invalid("EMPTY_PAIRS", "At least one column pair is required")
    sides = await endpoints(db, db_id, draft)
    present = await _physical_column_ids(db, db_id, sides)
    database = await db.get(SemanticDatabaseModel, db_id)
    dialect = {"postgresql": "postgres", "sqlserver": "tsql", "mssql": "tsql"}.get(database.db_type, database.db_type)
    seen = [set(), set()]
    clauses = []
    for index, pair in enumerate(draft.column_pairs):
        columns = []
        for side, column_id in enumerate((pair.from_column_id, pair.to_column_id)):
            column = next((c for c in sides[side][1] if c.id == column_id), None)
            if column is None or column_id in seen[side]:
                invalid("INVALID_PAIR", "Column is missing, foreign, or reused", index)
            if present is not None and column_id not in present:
                invalid("ABSENT_COLUMN", "Column is absent from the current physical schema", index)
            seen[side].add(column_id)
            columns.append(column)
        if not family(columns[0].data_type) or family(columns[0].data_type) != family(columns[1].data_type):
            invalid("INCOMPATIBLE_TYPES", "Column types are not proven equality-compatible", index)
        clauses.append(
            f"{column_sql(sides[0][0], columns[0], dialect)} = {column_sql(sides[1][0], columns[1], dialect)}"
        )
    warnings = cardinality_warnings(sides, seen, draft, approval)
    return {"sides": sides, "on_preview": " AND ".join(clauses), "warnings": warnings}


def cardinality_warnings(sides: tuple, seen: list[set], draft: RelationshipDraft, approval: bool) -> list[dict]:
    """Require complete keys or a deliberate human uniqueness attestation."""
    warnings = []
    required = {"many_to_one": [1], "one_to_one": [0, 1], "one_to_many": [0], "many_to_many": []}[
        draft.relationship_type
    ]
    for side in required:
        keys = {c.id for c in sides[side][1] if c.is_primary_key}
        if keys and seen[side] & keys and not keys <= seen[side]:
            invalid("PARTIAL_COMPOSITE_KEY", "The complete composite key is required", 0)
        if not keys or keys != seen[side]:
            if approval and not (draft.cardinality_confirmation or "").strip():
                invalid("UNPROVEN_CARDINALITY", "Explicit human uniqueness confirmation is required")
            warnings.append(
                {"code": "UNPROVEN_CARDINALITY", "message": "Uniqueness requires explicit human confirmation"}
            )
    if draft.relationship_type in ("one_to_many", "many_to_many"):
        warnings.append({"code": "UNSAFE_FANOUT", "message": "This cardinality is unsafe for metric joins"})
    return warnings


def fingerprint(draft: RelationshipDraft, target_id: int | None = None) -> str:
    """Hash identity from scoped endpoint and ordered column IDs."""
    data = draft.model_dump(exclude={"expected_revision", "cardinality_confirmation"})
    return hashlib.sha256(json.dumps([data, target_id], sort_keys=True).encode()).hexdigest()


async def _physical_column_ids(db: AsyncSession, db_id: int, sides: tuple) -> set[int] | None:
    """Keep historical metadata readable while requiring current physical endpoints."""
    snapshot = await _source_snapshot(db, db_id)
    if snapshot is None:
        return None
    present = set()
    for table, columns in sides:
        matches = [
            t
            for t in snapshot
            if t["table_name"]["raw_name"] == table.table_name
            and (table.physical_schema is None or t["schema_name"]["raw_name"] == table.physical_schema)
        ]
        if len(matches) != 1:
            invalid("ABSENT_TABLE", "Table is absent from the current physical schema")
        names = {column["column_name"]["raw_name"] for column in matches[0]["columns"]}
        present.update(column.id for column in columns if column.column_name in names)
    return present


async def _source_snapshot(db: AsyncSession, db_id: int) -> list[dict] | None:
    for model in (LiveTargetDbModel, ImportedSchemaModel):
        snapshot = await db.scalar(select(model.schema_metadata).where(model.semantic_db_id == db_id))
        if snapshot and "tables" in snapshot:
            return snapshot["tables"]
    return None
