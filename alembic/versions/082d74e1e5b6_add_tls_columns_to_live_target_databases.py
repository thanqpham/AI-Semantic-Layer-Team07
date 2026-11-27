"""add tls columns to live_target_databases

Revision ID: 082d74e1e5b6
Revises: c94fcf35e320
Create Date: 2026-11-23 21:45:43.885696

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '082d74e1e5b6'
down_revision: str | Sequence[str] | None = 'c94fcf35e320'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('live_target_databases', sa.Column('tls_mode', sa.String(length=20), server_default='prefer', nullable=False))
    op.add_column('live_target_databases', sa.Column('ca_cert', sa.Text(), nullable=True))
    op.add_column('live_target_databases', sa.Column('client_cert', sa.Text(), nullable=True))
    op.add_column('live_target_databases', sa.Column('client_key_enc', sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('live_target_databases', 'client_key_enc')
    op.drop_column('live_target_databases', 'client_cert')
    op.drop_column('live_target_databases', 'ca_cert')
    op.drop_column('live_target_databases', 'tls_mode')
