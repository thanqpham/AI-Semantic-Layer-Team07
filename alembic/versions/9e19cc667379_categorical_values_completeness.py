"""Track whether allowed values are an exhaustive declared domain."""

from alembic import op
import sqlalchemy as sa

revision = "9e19cc667379"
down_revision = "625f9b05ce74"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add completeness without changing existing domains."""
    op.add_column("semantic_columns", sa.Column("allowed_values_complete", sa.Boolean(), server_default="true", nullable=False))


def downgrade() -> None:
    """Remove the completeness flag."""
    op.drop_column("semantic_columns", "allowed_values_complete")
