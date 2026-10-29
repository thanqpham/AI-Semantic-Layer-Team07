"""Relationship review storage upgrades preserve legacy FK identity and payloads."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _migrations():
    versions = Path(__file__).resolve().parents[2] / "alembic/versions"
    names = ("20261027_relationship_review_persistence.py", "20261027_relationship_validation_backfill.py")
    modules = []
    for index, name in enumerate(names):
        spec = importlib.util.spec_from_file_location(f"relationship_review_migration_{index}", versions / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def _legacy_schema(connection):
    metadata = sa.MetaData()
    sa.Table("users", metadata, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("semantic_databases", metadata, sa.Column("id", sa.Integer, primary_key=True))
    tables = sa.Table(
        "semantic_tables", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("db_id", sa.Integer)
    )
    columns = sa.Table(
        "semantic_columns", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("table_id", sa.Integer)
    )
    relationships = _legacy_relationship_table(metadata)
    metadata.create_all(connection)
    connection.execute(tables.insert(), [{"id": 1, "db_id": 1}, {"id": 2, "db_id": 1}, {"id": 3, "db_id": 2}])
    connection.execute(
        columns.insert(), [{"id": i, "table_id": t} for i, t in [(11, 1), (12, 1), (21, 2), (22, 2), (31, 3)]]
    )
    return relationships


def _legacy_relationship_table(metadata):
    return sa.Table(
        "canonical_relationships",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("connection_id", sa.Integer),
        sa.Column("from_entity_id", sa.Integer),
        sa.Column("to_entity_id", sa.Integer),
        sa.Column("relationship_type", sa.String(50)),
        sa.Column("join_condition", sa.Text),
        sa.Column("relationship_key", sa.String(500)),
        sa.Column("constraint_name", sa.String(200)),
        sa.Column("column_pairs", sa.JSON),
        sa.Column("validation_status", sa.String(20)),
        sa.Column("created_at", sa.DateTime),
        sa.UniqueConstraint("connection_id", "relationship_key", name="uq_canonical_rel_key"),
    )


def _seed(connection, relationships):
    pairs = [{"from_column_id": 11, "to_column_id": 21}, {"from_column_id": 12, "to_column_id": 22}]
    cases = [
        ("valid", pairs),
        ("invalid", pairs),
        (None, pairs),
        (None, []),
        (None, [{"from_column_id": 11, "to_column_id": 31}]),
        (None, [pairs[0], {}]),
        (None, [pairs[0], pairs[0]]),
        ("unknown", pairs),
        (None, "unparsed legacy payload"),
    ]
    for identifier, (status, payload) in enumerate(cases, 1):
        connection.execute(
            relationships.insert().values(
                id=identifier,
                connection_id=1,
                from_entity_id=1,
                to_entity_id=2,
                relationship_type="many_to_one",
                join_condition="a.x = b.x AND a.y = b.y",
                relationship_key=f"fk:{identifier}",
                constraint_name="fk_compound",
                column_pairs=payload,
                validation_status=status,
            )
        )
    return list(connection.execute(sa.select(relationships)).mappings())


def test_relationship_review_migration_round_trip():
    review_migration, validation_migration = _migrations()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        old = _legacy_schema(connection)
        original = _seed(connection, old)
        with patch.object(review_migration, "op", Operations(MigrationContext.configure(connection))):
            review_migration.upgrade()
        with patch.object(validation_migration, "op", Operations(MigrationContext.configure(connection))):
            validation_migration.upgrade()
            _assert_upgrade(connection, original)
            validation_migration.downgrade()
        with patch.object(review_migration, "op", Operations(MigrationContext.configure(connection))):
            review_migration.downgrade()
            assert not sa.inspect(connection).has_table("relationship_candidates")
            assert "source" not in {c["name"] for c in sa.inspect(connection).get_columns("canonical_relationships")}
            assert connection.scalar(sa.text("SELECT count(*) FROM canonical_relationships")) == len(original)
            review_migration.upgrade()
        with patch.object(validation_migration, "op", Operations(MigrationContext.configure(connection))):
            validation_migration.upgrade()
            _assert_upgrade(connection, original, expect_legacy_evidence=False)
    engine.dispose()


def _assert_upgrade(connection, original, *, expect_legacy_evidence=True):
    table = sa.Table("canonical_relationships", sa.MetaData(), autoload_with=connection)
    rows = list(connection.execute(sa.select(table).order_by(table.c.id)).mappings())
    assert len(rows) == len(original)
    for old, row in zip(original, rows, strict=True):
        for key in ("id", "column_pairs", "join_condition", "constraint_name", "relationship_key"):
            assert row[key] == old[key]
        assert (row["source"], row["review_status"], row["revision"]) == ("fk", "approved", 1)
        assert row["reviewed_by"] is None and row["reviewed_at"] is None
        assert row["human_modified"] is False
    assert [r["validation_status"] for r in rows] == ["valid", "invalid", "valid"] + ["needs_review"] * 6
    if expect_legacy_evidence:
        assert rows[7]["evidence"]["legacy_validation_status"] == "unknown"
    assert sa.inspect(connection).has_table("relationship_candidates")
    index = sa.inspect(connection).get_indexes("relationship_candidates")
    assert any(i["column_names"] == ["connection_id", "status"] for i in index)


@pytest.mark.parametrize("field,value", [("source", "other"), ("review_status", "pending"), ("revision", 0)])
def test_migrated_canonical_constraints(field, value):
    review_migration, validation_migration = _migrations()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        old = _legacy_schema(connection)
        _seed(connection, old)
        with patch.object(review_migration, "op", Operations(MigrationContext.configure(connection))):
            review_migration.upgrade()
        with patch.object(validation_migration, "op", Operations(MigrationContext.configure(connection))):
            validation_migration.upgrade()
        table = sa.Table("canonical_relationships", sa.MetaData(), autoload_with=connection)
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(table.update().where(table.c.id == 1).values(**{field: value}))
    engine.dispose()
