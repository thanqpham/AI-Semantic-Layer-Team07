"""add_column_value_proposals

Revision ID: 625f9b05ce74
Revises: f9ead304ba7e
"""

from alembic import op
import sqlalchemy as sa

revision = "625f9b05ce74"
down_revision = "f9ead304ba7e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add isolated value proposals."""
    op.create_table(
        "column_value_proposals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("column_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.CheckConstraint("source IN ('declared', 'observed')", name="ck_column_value_proposal_source"),
        sa.CheckConstraint("status IN ('pending', 'approved', 'dismissed')", name="ck_column_value_proposal_status"),
        sa.ForeignKeyConstraint(["column_id"], ["semantic_columns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("column_id", name="uq_column_value_proposal_column"),
    )


def downgrade() -> None:
    """Drop proposal storage only."""
    op.drop_table("column_value_proposals")
