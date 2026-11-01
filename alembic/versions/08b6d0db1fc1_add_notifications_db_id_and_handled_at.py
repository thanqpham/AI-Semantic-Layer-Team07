"""add notifications db_id and handled_at

Revision ID: 08b6d0db1fc1
Revises: bd2ef25c54e8
Create Date: 2026-10-30 12:29:07.652577

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08b6d0db1fc1'
down_revision: Union[str, Sequence[str], None] = 'bd2ef25c54e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Only the two new notification columns — the FK lives on the model
    # (fresh DBs via create_all); ALTER ADD CONSTRAINT is not portable here.
    op.add_column('notifications', sa.Column('db_id', sa.Integer(), nullable=True))
    op.add_column('notifications', sa.Column('handled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('notifications', 'handled_at')
    op.drop_column('notifications', 'db_id')
