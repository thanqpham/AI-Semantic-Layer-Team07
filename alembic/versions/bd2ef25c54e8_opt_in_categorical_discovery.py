"""Require explicit enablement per live connection."""

from alembic import op
import sqlalchemy as sa

revision = "bd2ef25c54e8"
down_revision = "9e19cc667379"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add an opt-in flag for each connection."""
    op.add_column("live_target_databases", sa.Column("categorical_discovery_enabled", sa.Boolean(), server_default="false", nullable=False))


def downgrade() -> None:
    """Remove the connection flag."""
    op.drop_column("live_target_databases", "categorical_discovery_enabled")
