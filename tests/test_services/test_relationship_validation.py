"""Metadata-only validation for relationship review drafts."""

from typing import Any

import pytest
import sqlglot
from fastapi import HTTPException

from src.models.db import (
    ImportedSchemaModel,
    LiveTargetDbModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticTableModel,
)
from src.models.relationship_review import ColumnPair, RelationshipDraft
from src.services.relationship_validation import validate_relationship


async def _seed_relationship_metadata(async_session: Any) -> dict[str, Any]:
    metadata = await _seed_database_tables(async_session)
    await _seed_endpoint_columns(async_session, metadata)
    return metadata


async def _seed_database_tables(async_session: Any) -> dict[str, Any]:
    database = SemanticDatabaseModel(
        id=1,
        display_name="Main",
        db_type="postgresql",
        conn_url_enc="metadata-only",
    )
    other_database = SemanticDatabaseModel(
        id=2,
        display_name="Other",
        db_type="postgresql",
        conn_url_enc="metadata-only",
    )
    from_table = SemanticTableModel(db_id=1, table_name="orders", business_name="Orders")
    to_table = SemanticTableModel(db_id=1, table_name="customers", business_name="Customers")
    foreign_table = SemanticTableModel(db_id=2, table_name="foreign", business_name="Foreign")
    async_session.add_all([database, other_database, from_table, to_table, foreign_table])
    await async_session.flush()
    return {
        "database": database,
        "from_table": from_table,
        "to_table": to_table,
        "foreign_table": foreign_table,
    }


async def _seed_endpoint_columns(async_session: Any, metadata: dict[str, Any]) -> None:
    from_column = SemanticColumnModel(
        table_id=metadata["from_table"].id,
        column_name="customer_id",
        data_type="integer",
        business_name="Customer ID",
    )
    to_column = SemanticColumnModel(
        table_id=metadata["to_table"].id,
        column_name="id",
        data_type="bigint",
        business_name="ID",
        is_primary_key=True,
    )
    foreign_column = SemanticColumnModel(
        table_id=metadata["foreign_table"].id,
        column_name="id",
        data_type="integer",
        business_name="ID",
    )
    async_session.add_all([from_column, to_column, foreign_column])
    await async_session.flush()
    metadata.update(from_column=from_column, to_column=to_column, foreign_column=foreign_column)


def _snapshot_table(table_name: str, column_names: list[str]) -> dict[str, Any]:
    return {
        "schema_name": _identifier("public"),
        "table_name": _identifier(table_name),
        "columns": [{"column_name": _identifier(name)} for name in column_names],
    }


def _identifier(name: str) -> dict[str, Any]:
    return {"raw_name": name, "normalized_name": name, "quoted": False}


def _schema_snapshot(tables: list[dict[str, Any]]) -> dict[str, Any]:
    return {"contract_version": "1.0", "dialect": "postgresql", "tables": tables}


async def _add_imported_snapshot(async_session: Any, tables: list[dict[str, Any]]) -> None:
    async_session.add(
        ImportedSchemaModel(
            created_by=1,
            display_name="Snapshot",
            dialect="postgresql",
            semantic_db_id=1,
            schema_metadata=_schema_snapshot(tables),
        )
    )
    await async_session.flush()


async def _composite_key_pairs(async_session: Any, metadata: dict[str, Any]) -> list[ColumnPair]:
    from_tenant = SemanticColumnModel(
        table_id=metadata["from_table"].id,
        column_name="tenant_id",
        data_type="integer",
        business_name="Tenant ID",
    )
    to_tenant = SemanticColumnModel(
        table_id=metadata["to_table"].id,
        column_name="tenant_id",
        data_type="integer",
        business_name="Tenant ID",
        is_primary_key=True,
    )
    metadata["to_column"].is_primary_key = True
    async_session.add_all([from_tenant, to_tenant])
    await async_session.flush()
    return [
        ColumnPair(from_column_id=metadata["from_column"].id, to_column_id=metadata["to_column"].id),
        ColumnPair(from_column_id=from_tenant.id, to_column_id=to_tenant.id),
    ]


def _draft(
    metadata: dict[str, Any],
    *,
    from_entity_id: int | None = None,
    to_entity_id: int | None = None,
    pairs: list[ColumnPair] | None = None,
    relationship_type: str = "many_to_one",
    cardinality_confirmation: str | None = None,
) -> RelationshipDraft:
    return RelationshipDraft(
        from_entity_id=from_entity_id or metadata["from_table"].id,
        to_entity_id=to_entity_id or metadata["to_table"].id,
        column_pairs=pairs
        if pairs is not None
        else [
            ColumnPair(
                from_column_id=metadata["from_column"].id,
                to_column_id=metadata["to_column"].id,
            )
        ],
        relationship_type=relationship_type,  # type: ignore[arg-type]
        cardinality_confirmation=cardinality_confirmation,
    )


def _error_code(error: HTTPException) -> str:
    return error.detail["errors"][0]["code"]


@pytest.mark.asyncio
async def test_empty_column_pairs_raise_structured_422(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata, pairs=[]))

    assert error.value.status_code == 422
    assert _error_code(error.value) == "EMPTY_PAIRS"


@pytest.mark.asyncio
async def test_foreign_table_id_is_rejected_at_database_boundary(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)

    with pytest.raises(HTTPException) as error:
        await validate_relationship(
            async_session,
            1,
            _draft(metadata, to_entity_id=metadata["foreign_table"].id),
        )

    assert _error_code(error.value) == "FOREIGN_TABLE"


@pytest.mark.asyncio
async def test_repeated_endpoint_table_id_is_rejected(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)

    with pytest.raises(HTTPException) as error:
        await validate_relationship(
            async_session,
            1,
            _draft(metadata, to_entity_id=metadata["from_table"].id),
        )

    assert _error_code(error.value) == "REPEATED_TABLE"


@pytest.mark.asyncio
async def test_column_must_belong_to_its_respective_endpoint(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    draft = _draft(
        metadata,
        pairs=[
            ColumnPair(
                from_column_id=metadata["to_column"].id,
                to_column_id=metadata["from_column"].id,
            )
        ],
    )

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, draft)

    assert _error_code(error.value) == "INVALID_PAIR"


@pytest.mark.asyncio
async def test_repeated_column_ids_are_rejected(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    pair = ColumnPair(
        from_column_id=metadata["from_column"].id,
        to_column_id=metadata["to_column"].id,
    )

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata, pairs=[pair, pair]))

    assert _error_code(error.value) == "INVALID_PAIR"


@pytest.mark.asyncio
async def test_unproven_type_families_are_rejected(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    metadata["to_column"].data_type = "jsonb"
    await async_session.flush()

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata))

    assert _error_code(error.value) == "INCOMPATIBLE_TYPES"


@pytest.mark.asyncio
async def test_preview_quotes_identifiers_and_never_executes_sql(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    metadata["from_table"].table_name = 'order "items'
    metadata["from_column"].column_name = 'customer"; DROP TABLE customers; --'
    await async_session.flush()

    result = await validate_relationship(async_session, 1, _draft(metadata))

    assert '"order ""items"' in result["on_preview"]
    assert '"customer""; DROP TABLE customers; --"' in result["on_preview"]
    parsed = sqlglot.parse("SELECT 1 WHERE " + result["on_preview"], read="postgres")
    assert len(parsed) == 1
    assert not list(parsed[0].find_all(sqlglot.exp.Drop))
    assert result["warnings"] == []


@pytest.mark.asyncio
async def test_snapshot_rejects_an_endpoint_table_that_is_absent(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    await _add_imported_snapshot(
        async_session,
        [_snapshot_table("orders", ["customer_id"])],
    )

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata))

    assert _error_code(error.value) == "ABSENT_TABLE"


@pytest.mark.asyncio
async def test_live_snapshot_is_used_to_reject_absent_endpoint_table(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    async_session.add(
        LiveTargetDbModel(
            created_by=1,
            display_name="Live snapshot",
            dialect="postgresql",
            conn_url_enc="encrypted",
            semantic_db_id=1,
            schema_metadata={"tables": []},
        )
    )
    await async_session.flush()

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata))

    assert _error_code(error.value) == "ABSENT_TABLE"


@pytest.mark.asyncio
async def test_snapshot_rejects_column_absent_from_endpoint_table(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    await _add_imported_snapshot(
        async_session,
        [
            _snapshot_table("orders", ["customer_id"]),
            _snapshot_table("customers", ["stale_id"]),
        ],
    )

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata))

    assert _error_code(error.value) == "ABSENT_COLUMN"


@pytest.mark.asyncio
async def test_approval_requires_confirmation_when_target_uniqueness_is_unproven(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    metadata["to_column"].is_primary_key = False
    await async_session.flush()

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata), approval=True)

    assert _error_code(error.value) == "UNPROVEN_CARDINALITY"


@pytest.mark.asyncio
async def test_approval_accepts_explicit_confirmation_for_unproven_uniqueness(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    metadata["to_column"].is_primary_key = False
    await async_session.flush()

    result = await validate_relationship(
        async_session,
        1,
        _draft(metadata, cardinality_confirmation="I verified uniqueness"),
        approval=True,
    )

    assert result["warnings"][0]["code"] == "UNPROVEN_CARDINALITY"


@pytest.mark.asyncio
async def test_approval_rejects_incomplete_composite_key(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    second_key = SemanticColumnModel(
        table_id=metadata["to_table"].id,
        column_name="tenant_id",
        data_type="integer",
        business_name="Tenant ID",
        is_primary_key=True,
    )
    async_session.add(second_key)
    await async_session.flush()

    with pytest.raises(HTTPException) as error:
        await validate_relationship(async_session, 1, _draft(metadata), approval=True)

    assert _error_code(error.value) == "PARTIAL_COMPOSITE_KEY"


@pytest.mark.asyncio
async def test_approval_accepts_complete_composite_key(async_session: Any) -> None:
    metadata = await _seed_relationship_metadata(async_session)
    pairs = await _composite_key_pairs(async_session, metadata)
    result = await validate_relationship(
        async_session,
        1,
        _draft(metadata, pairs=pairs),
        approval=True,
    )

    assert result["warnings"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("relationship_type", ["one_to_many", "many_to_many"])
async def test_fanout_relationships_return_warning(async_session: Any, relationship_type: str) -> None:
    metadata = await _seed_relationship_metadata(async_session)

    result = await validate_relationship(
        async_session,
        1,
        _draft(metadata, relationship_type=relationship_type),
    )

    assert {"code": "UNSAFE_FANOUT", "message": "This cardinality is unsafe for metric joins"} in result["warnings"]
