"""Notifications db_id/handled_at migration must add and drop cleanly."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _load_migration():
    versions_dir = Path(__file__).resolve().parents[2] / "alembic/versions"
    matches = list(versions_dir.glob("*add_notifications_db_id_and_handled_at.py"))
    assert len(matches) == 1, f"expected exactly one migration file, found {matches}"
    spec = importlib.util.spec_from_file_location("notifications_columns_migration", matches[0])
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_notifications_migration_adds_and_drops_db_id_handled_at():
    migration = _load_migration()
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        sa.Table(
            "notifications",
            sa.MetaData(),
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("recipient_id", sa.Integer),
            sa.Column("type", sa.String(50)),
        ).create(connection)
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            columns = {c["name"] for c in sa.inspect(connection).get_columns("notifications")}
            assert {"db_id", "handled_at"} <= columns
            migration.downgrade()
            columns = {c["name"] for c in sa.inspect(connection).get_columns("notifications")}
            assert not {"db_id", "handled_at"} & columns
    engine.dispose()
