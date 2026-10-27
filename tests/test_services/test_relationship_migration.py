"""Relationship persistence migration keeps the serving graph intact."""

import importlib.util
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    paths = list(versions.glob("*relationship_review*.py"))
    assert paths, "Relationship-review Alembic revision is missing"
    path = paths[0]
    spec = importlib.util.spec_from_file_location("relationship_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_relationship_migration_preserves_existing_canonical_serving_row():
    """Upgrade retains canonical IDs and serving fields while approving legacy rows."""
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        users = sa.Table("users", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True))
        databases = sa.Table("semantic_databases", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True))
        tables = sa.Table("semantic_tables", sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True))
        canonical = sa.Table(
            "canonical_relationships",
            sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("connection_id", sa.Integer, nullable=False),
            sa.Column("from_entity_id", sa.Integer, nullable=False),
            sa.Column("to_entity_id", sa.Integer, nullable=False),
            sa.Column("relationship_type", sa.String(50), nullable=False),
            sa.Column("join_condition", sa.Text, nullable=False),
            sa.Column("relationship_key", sa.String(500), nullable=False),
            sa.Column("constraint_name", sa.String(200)),
            sa.Column("column_pairs", sa.JSON, nullable=False),
            sa.Column("validation_status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.UniqueConstraint("connection_id", "relationship_key", name="uq_canonical_rel_key"),
        )
        for table in (users, databases, tables, canonical):
            table.create(connection)
        connection.execute(users.insert().values(id=1))
        connection.execute(databases.insert().values(id=2))
        connection.execute(tables.insert(), [{"id": 3}, {"id": 4}])
        connection.execute(
            canonical.insert().values(
                id=17,
                connection_id=2,
                from_entity_id=3,
                to_entity_id=4,
                relationship_type="many_to_one",
                join_condition="orders.customer_id = customers.id",
                relationship_key="orders_customer",
                constraint_name="fk_orders_customer",
                column_pairs=[{"from_column_id": 31, "to_column_id": 41}],
                validation_status="valid",
                created_at=datetime(2026, 10, 27, 12, 0, 0),
            )
        )
        before = connection.execute(sa.select(canonical)).mappings().one()

        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()

        inspector = sa.inspect(connection)
        assert inspector.has_table("relationship_candidates")
        candidate_columns = {column["name"] for column in inspector.get_columns("relationship_candidates")}
        assert {
            "target_relationship_id",
            "unresolved_questions",
            "updated_by",
            "updated_at",
        } <= candidate_columns
        candidate_indexes = {index["name"] for index in inspector.get_indexes("relationship_candidates")}
        assert "idx_relationship_candidates_connection_status" in candidate_indexes
        columns = {column["name"] for column in inspector.get_columns("canonical_relationships")}
        assert {
            "source",
            "review_status",
            "reviewed_by",
            "reviewed_at",
            "human_modified",
            "revision",
            "evidence",
        } <= columns
        canonical_after = sa.Table("canonical_relationships", sa.MetaData(), autoload_with=connection)
        after = connection.execute(sa.select(canonical_after).where(canonical_after.c.id == 17)).mappings().one()
        for field in before:
            assert after[field] == before[field]
        assert after["source"] == "fk"
        assert after["review_status"] == "approved"
        assert after["human_modified"] is False
        assert after["revision"] == 1
        assert after["evidence"] == {}
        reviewer_fks = inspector.get_foreign_keys("canonical_relationships")
        assert any(
            fk["constrained_columns"] == ["reviewed_by"] and fk["referred_table"] == "users" for fk in reviewer_fks
        )

        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.downgrade()
        assert not sa.inspect(connection).has_table("relationship_candidates")
        remaining_columns = {column["name"] for column in sa.inspect(connection).get_columns("canonical_relationships")}
        assert remaining_columns == set(before)
    engine.dispose()
