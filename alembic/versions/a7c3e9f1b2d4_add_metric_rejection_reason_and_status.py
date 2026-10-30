"""add metric rejection_reason and rejected status

Revision ID: a7c3e9f1b2d4
Revises: 08b6d0db1fc1
Create Date: 2026-10-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f1b2d4'
down_revision: Union[str, Sequence[str], None] = '08b6d0db1fc1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "ck_semantic_metrics_status"
_OLD_STATUSES = "('draft', 'pending_approval', 'needs_review', 'approved', 'unverified')"
_NEW_STATUSES = "('draft', 'pending_approval', 'needs_review', 'approved', 'unverified', 'rejected')"


def _swap_status_constraint(new_statuses: str) -> None:
    """Replace the metric status CHECK constraint portably (SQLite + PostgreSQL)."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("semantic_metrics", recreate="always") as batch:
            batch.drop_constraint(_CONSTRAINT_NAME, type_="check")
            batch.create_check_constraint(_CONSTRAINT_NAME, f"status IN {new_statuses}")
        return
    op.drop_constraint(_CONSTRAINT_NAME, "semantic_metrics", type_="check")
    op.create_check_constraint(_CONSTRAINT_NAME, "semantic_metrics", f"status IN {new_statuses}")


def upgrade() -> None:
    """Add proposal rejection_reason and allow the 'rejected' metric status."""
    op.add_column('metric_proposals', sa.Column('rejection_reason', sa.Text(), nullable=True))
    _swap_status_constraint(_NEW_STATUSES)


def downgrade() -> None:
    """Map rejected metrics back to needs_review and drop the new column."""
    op.get_bind().execute(
        sa.text("UPDATE semantic_metrics SET status = 'needs_review' WHERE status = 'rejected'")
    )
    _swap_status_constraint(_OLD_STATUSES)
    op.drop_column('metric_proposals', 'rejection_reason')
