"""New proposal storage must not change existing catalog or user data."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_proposal_migration_round_trip_preserves_existing_tables():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/c02b7c2cd880_add_metric_proposals.py"
    spec = importlib.util.spec_from_file_location("metric_proposal_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        for table in ("users", "semantic_databases", "semantic_metrics", "metric_requests"):
            existing = sa.Table(table, sa.MetaData(), sa.Column("id", sa.Integer, primary_key=True))
            existing.create(connection)
            connection.execute(existing.insert().values(id=1))
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            assert sa.inspect(connection).has_table("metric_proposals")
            assert "schema_fingerprint" in {c["name"] for c in sa.inspect(connection).get_columns("metric_proposals")}
            migration.downgrade()
        assert not sa.inspect(connection).has_table("metric_proposals")
        assert connection.scalar(sa.text("SELECT id FROM semantic_metrics")) == 1
    engine.dispose()
