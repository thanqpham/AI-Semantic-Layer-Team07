"""add database overview

Revision ID: c94fcf35e320
Revises: 62260812bd87
Create Date: 2026-11-11 22:47:20.390700

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c94fcf35e320'
down_revision: Union[str, Sequence[str], None] = '62260812bd87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('semantic_databases') as batch:
        batch.add_column(sa.Column('description', sa.Text(), nullable=True))
        batch.add_column(sa.Column('draft_description', sa.Text(), nullable=True))
        batch.add_column(sa.Column('ai_description', sa.Text(), nullable=True))
        batch.add_column(sa.Column('overview_revision', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('overview_reviewed_at', sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column('overview_reviewed_by', sa.Integer(), nullable=True))
        batch.create_foreign_key('fk_overview_reviewer', 'users', ['overview_reviewed_by'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('semantic_databases') as batch:
        batch.drop_constraint('fk_overview_reviewer', type_='foreignkey')
        for column in ('overview_reviewed_by', 'overview_reviewed_at', 'overview_revision', 'ai_description', 'draft_description', 'description'):
            batch.drop_column(column)
