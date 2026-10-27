"""Qualified uniqueness preserves existing metadata and blocks lossy downgrade."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_preserves_rows_and_safe_downgrade():
    path = next((Path(__file__).parents[2] / "alembic/versions").glob("*_schema_qualified_tables.py"))
    spec = importlib.util.spec_from_file_location("qualified_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE semantic_tables (id INTEGER PRIMARY KEY, db_id INTEGER, table_name TEXT, physical_schema TEXT, CONSTRAINT uq_semantic_tables_db_table UNIQUE(db_id, table_name))"
        )
        connection.exec_driver_sql(
            "CREATE TABLE semantic_metrics (id INTEGER PRIMARY KEY, base_entity_id INTEGER REFERENCES semantic_tables(id), formula TEXT)"
        )
        connection.exec_driver_sql(
            "INSERT INTO semantic_tables VALUES (11,1,'orders','public'),(12,1,'legacy',NULL),(15,1,'Orders','public')"
        )
        connection.exec_driver_sql("INSERT INTO semantic_metrics VALUES (21,11,'COUNT(*)')")
        before = connection.exec_driver_sql(
            "SELECT id, db_id, table_name, physical_schema FROM semantic_tables ORDER BY id"
        ).all()
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            assert (
                connection.exec_driver_sql(
                    "SELECT id, db_id, table_name, physical_schema FROM semantic_tables ORDER BY id"
                ).all()
                == before
            )
            assert connection.exec_driver_sql("SELECT * FROM semantic_metrics").all() == [(21, 11, "COUNT(*)")]
            connection.exec_driver_sql(
                "INSERT INTO semantic_tables(id,db_id,table_name,physical_schema) VALUES (13,1,'orders','archive')"
            )
            with pytest.raises(RuntimeError, match="duplicate table names"):
                migration.downgrade()
            assert connection.exec_driver_sql("SELECT count(*) FROM semantic_tables").scalar() == 4
            with pytest.raises(sa.exc.IntegrityError):
                connection.exec_driver_sql(
                    "INSERT INTO semantic_tables(id,db_id,table_name,physical_schema,table_name_key,physical_schema_key) VALUES (14,1,'ORDERS','PUBLIC','orders','public')"
                )
            connection.exec_driver_sql("DELETE FROM semantic_tables WHERE id=13")
            migration.downgrade()
            assert (
                connection.exec_driver_sql(
                    "SELECT id, db_id, table_name, physical_schema FROM semantic_tables ORDER BY id"
                ).all()
                == before
            )
            assert connection.exec_driver_sql("SELECT * FROM semantic_metrics").all() == [(21, 11, "COUNT(*)")]
