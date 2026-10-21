"""add_user_llm_settings

Revision ID: bfc12f0bb328
Revises: w9x0y1z2a3
Create Date: 2026-10-21 23:18:36.745066

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfc12f0bb328'
down_revision: Union[str, Sequence[str], None] = 'w9x0y1z2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "user_llm_settings",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("credentials_enc", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_llm_settings")
