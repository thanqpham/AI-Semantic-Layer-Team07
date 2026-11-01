"""add reviewed business labels for allowed column values"""

from alembic import op
import sqlalchemy as sa

revision = "v22allowedpairs"
down_revision = "bd2ef25c54e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("semantic_columns", sa.Column("allowed_value_mappings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("semantic_columns", "allowed_value_mappings")
