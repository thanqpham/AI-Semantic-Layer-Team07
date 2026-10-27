"""Unit & integration tests for schema self-healing service and AST rewriting."""

import sqlite3

import pytest
from sqlalchemy import select

from src.models.db import (
    LiveTargetDbModel,
    MetricVersionModel,
    SemanticColumnModel,
    SemanticDatabaseModel,
    SemanticMetricModel,
    SemanticTableModel,
)
from src.services.database import encrypt_conn_url
from src.services.schema_fingerprint import fast_introspect_schema_fingerprint
from src.services.schema_self_healing_service import (
    execute_self_healing,
    heal_sql_formula_ast,
)


def test_heal_sql_formula_ast():
    """Test AST column rewriting in formulas."""
    # Simple SUM
    assert heal_sql_formula_ast("SUM(total_price)", "total_price", "amount") == "SUM(amount)"
    # Arithmetic expression
    assert heal_sql_formula_ast("total_price * 1.1", "total_price", "amount") == "amount * 1.1"
    # Case insensitivity
    assert heal_sql_formula_ast("SUM(TOTAL_PRICE)", "total_price", "amount") == "SUM(amount)"
    # Multiple occurrences
    assert (
        heal_sql_formula_ast("total_price - (total_price * 0.1)", "total_price", "amount") == "amount - (amount * 0.1)"
    )


@pytest.mark.asyncio
async def test_execute_self_healing_flow(async_session, tmp_path):
    """Integration test: live DB column rename -> self-heal -> metric formula rewritten + VN name preserved."""
    # 1. Setup mock target live DB
    db_file = tmp_path / "live_shop.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total_price REAL, status TEXT)")
    conn.execute("INSERT INTO orders (id, total_price, status) VALUES (1, 100.0, 'completed')")
    conn.commit()
    conn.close()

    conn_url = f"sqlite:///{db_file}"
    initial_fp = fast_introspect_schema_fingerprint(conn_url, "sqlite")

    # 2. Setup semantic database, tables, columns, and metric
    sem_db = SemanticDatabaseModel(
        id=101,
        created_by=1,
        display_name="Live Shop",
        db_type="sqlite",
        conn_url_enc="semantic:live_target_db:101",
        schema_fingerprint=initial_fp,
        status="approved",
    )
    async_session.add(sem_db)
    await async_session.flush()

    live_db = LiveTargetDbModel(
        id=101,
        created_by=1,
        semantic_db_id=sem_db.id,
        display_name="Live Shop",
        dialect="sqlite",
        conn_url_enc=encrypt_conn_url(conn_url),
        schema_metadata={},
    )
    async_session.add(live_db)

    tbl = SemanticTableModel(
        id=201,
        db_id=sem_db.id,
        table_name="orders",
        business_name="Đơn hàng",
        description="Bảng thông tin đơn hàng",
        created_by=1,
    )
    async_session.add(tbl)
    await async_session.flush()

    col1 = SemanticColumnModel(
        id=301,
        table_id=tbl.id,
        column_name="total_price",
        data_type="REAL",
        business_name="Tổng tiền đơn",
        description="Tổng giá trị đơn hàng",
    )
    col2 = SemanticColumnModel(
        id=302,
        table_id=tbl.id,
        column_name="status",
        data_type="TEXT",
        business_name="Trạng thái",
        description="Trạng thái đơn hàng",
    )
    async_session.add_all([col1, col2])
    await async_session.flush()

    metric = SemanticMetricModel(
        id=401,
        db_id=sem_db.id,
        created_by=1,
        name="Tổng Doanh Thu",
        description="Tổng doanh thu từ các đơn hàng hoàn tất",
        formula="SUM(total_price)",
        sql_template="SUM(total_price)",
        status="approved",
        base_entity_id=tbl.id,
        definition={"formula": {"expression": "total_price"}},
    )
    async_session.add(metric)
    await async_session.commit()

    # 3. Alter target table in Live DB (Rename column total_price -> amount)
    conn = sqlite3.connect(db_file)
    conn.execute("ALTER TABLE orders RENAME COLUMN total_price TO amount")
    conn.commit()
    conn.close()

    # 4. Trigger Self-Healing
    log = await execute_self_healing(async_session, sem_db.id, trigger_type="instant_check")

    # 5. Assertions
    assert log.status == "healed"
    assert log.changes_summary is not None
    assert len(log.changes_summary.get("renamed_columns", [])) == 1
    assert log.changes_summary["renamed_columns"][0]["old_name"] == "total_price"
    assert log.changes_summary["renamed_columns"][0]["new_name"] == "amount"

    # Verify column was renamed but Vietnamese business name is strictly preserved
    await async_session.refresh(col1)
    assert col1.column_name == "amount"
    assert col1.business_name == "Tổng tiền đơn"

    # Verify metric formula was rewritten to SUM(amount)
    await async_session.refresh(metric)
    assert metric.formula == "SUM(amount)"
    assert metric.sql_template == "SUM(amount)"
    assert metric.name == "Tổng Doanh Thu"
    assert metric.version == 2

    # Verify version audit entry was created
    versions = (
        (await async_session.execute(select(MetricVersionModel).where(MetricVersionModel.metric_id == metric.id)))
        .scalars()
        .all()
    )
    assert len(versions) == 1
    assert "total_price" in versions[0].change_reason
    assert "amount" in versions[0].change_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["rename", "table_rename", "drop", "type"])
async def test_relationship_sync_preserves_endpoint_history(async_session, change):
    from unittest.mock import patch

    from src.models.db import CanonicalRelationshipModel
    from src.models.schema_metadata import Identifier, SchemaDialect
    from tests.test_services.test_relationship_sync import seed

    raw, relationship = await seed(async_session)
    old_pairs, old_id = list(relationship.column_pairs), relationship.id
    source = next(t for t in raw.tables if t.foreign_keys)
    if change == "drop":
        raw = raw.model_copy(update={"tables": tuple(t for t in raw.tables if t != source)})
    elif change == "table_rename":
        renamed = source.model_copy(update={"table_name": Identifier.from_raw("purchases", raw.dialect)})
        raw = raw.model_copy(update={"tables": tuple(renamed if t == source else t for t in raw.tables)})
    else:
        ident = Identifier.from_raw("buyer_id", raw.dialect)
        columns = tuple(
            c.model_copy(update={"column_name": ident}) if c.column_name.raw_name == "user_id" else c
            for c in source.columns
        )
        fks = tuple(fk.model_copy(update={"constrained_columns": (ident,)}) for fk in source.foreign_keys)
        if change == "type":
            columns = tuple(
                c.model_copy(update={"data_type": "TEXT", "raw_data_type": "TEXT"})
                if c.column_name.raw_name == "user_id"
                else c
                for c in source.columns
            )
            fks = source.foreign_keys
        renamed = source.model_copy(update={"columns": columns, "foreign_keys": fks})
        raw = raw.model_copy(update={"tables": tuple(renamed if t == source else t for t in raw.tables)})
    live = LiveTargetDbModel(
        created_by=1,
        semantic_db_id=90,
        display_name="Sync",
        dialect="postgresql",
        conn_url_enc=encrypt_conn_url("postgresql://local/test"),
        schema_metadata={},
    )
    async_session.add(live)
    await async_session.commit()
    with (
        patch("src.services.schema_self_healing_service.introspect_live_database", return_value=raw),
        patch(
            "src.services.schema_self_healing_service.resolve_and_validate_dialect",
            return_value=SchemaDialect.POSTGRESQL,
        ),
    ):
        log = await execute_self_healing(async_session, 90)
    assert relationship.id == old_id and relationship.column_pairs == old_pairs
    assert await async_session.get(CanonicalRelationshipModel, old_id) is not None
    if change in {"rename", "table_rename"}:
        assert relationship.validation_status == "valid"
    else:
        assert relationship.review_status == "needs_review" and relationship.validation_status == "invalid"
        assert log.changes_summary["relationship_impacts"]
    assert live.schema_metadata == raw.model_dump(mode="json")
