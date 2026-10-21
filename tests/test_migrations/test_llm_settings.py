"""The account settings migration adds and removes only its own table."""

import importlib.util
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_llm_settings_upgrade_and_downgrade_preserve_users():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/bfc12f0bb328_add_user_llm_settings.py"
    spec = importlib.util.spec_from_file_location("llm_settings_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("INSERT INTO users (id) VALUES (1)"))
        with patch.object(migration, "op", Operations(MigrationContext.configure(connection))):
            migration.upgrade()
            columns = {column["name"] for column in sa.inspect(connection).get_columns("user_llm_settings")}
            assert columns == {"user_id", "provider", "credentials_enc"}
            migration.downgrade()
        assert not sa.inspect(connection).has_table("user_llm_settings")
        assert connection.scalar(sa.text("SELECT id FROM users")) == 1
    engine.dispose()
