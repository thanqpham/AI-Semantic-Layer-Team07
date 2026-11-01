"""merge notifications and value mappings heads

Revision ID: 62260812bd87
Revises: a7c3e9f1b2d4, v22allowedpairs
Create Date: 2026-11-01 21:57:34.566559

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62260812bd87'
down_revision: Union[str, Sequence[str], None] = ('a7c3e9f1b2d4', 'v22allowedpairs')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
