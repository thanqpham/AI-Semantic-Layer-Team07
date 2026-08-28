"""Merge the branch and main migration heads.

Revision ID: w9x0y1z2a3
Revises: 0f940d398032, v8w9x0y1z2a3
Create Date: 2026-08-28

This migration only reconciles the revision graph and performs no schema
mutations.
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "w9x0y1z2a3"
down_revision: tuple[str, str] = ("0f940d398032", "v8w9x0y1z2a3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge both migration heads without changing the schema."""
    pass


def downgrade() -> None:
    """Keep the merge revision reversible without changing the schema."""
    pass
