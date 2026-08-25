"""merge_all_heads

Revision ID: 0f940d398032
Revises: 95ff234b973e, p2q3r4s5t6u7, p2q3r4s5t6u
Create Date: 2026-08-25 13:41:59.930966

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f940d398032'
down_revision: Union[str, Sequence[str], None] = ('95ff234b973e', 'p2q3r4s5t6u7', 'p2q3r4s5t6u')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
