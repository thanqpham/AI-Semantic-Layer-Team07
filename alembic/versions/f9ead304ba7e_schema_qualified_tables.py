"""schema_qualified_tables

Revision ID: f9ead304ba7e
Revises: b3fa66ced28c
Create Date: 2026-10-27 22:43:17.685780

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9ead304ba7e"
down_revision: Union[str, Sequence[str], None] = "b3fa66ced28c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace bare-name uniqueness without changing persisted identity or schema."""
    collisions = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT db_id FROM semantic_tables GROUP BY db_id, lower(coalesce(physical_schema, '')), lower(table_name) HAVING COUNT(*) > 1"
            )
        )
        .first()
    )
    if collisions:
        raise RuntimeError("Cannot qualify table identity: normalized schema/table names collide")
    with op.batch_alter_table("semantic_tables") as batch:
        batch.drop_constraint("uq_semantic_tables_db_table", type_="unique")
    op.create_index(
        "uq_semantic_tables_db_schema_table",
        "semantic_tables",
        ["db_id", sa.text("lower(coalesce(physical_schema, ''))"), sa.text("lower(table_name)")],
        unique=True,
    )


def downgrade() -> None:
    """Refuse a lossy downgrade before modifying schema or rows."""
    duplicates = (
        op.get_bind()
        .execute(
            sa.text("SELECT db_id, table_name FROM semantic_tables GROUP BY db_id, table_name HAVING COUNT(*) > 1")
        )
        .first()
    )
    if duplicates:
        raise RuntimeError("Cannot downgrade schema-qualified tables: duplicate table names must be resolved first")
    op.drop_index("uq_semantic_tables_db_schema_table", table_name="semantic_tables")
    with op.batch_alter_table("semantic_tables") as batch:
        batch.create_unique_constraint("uq_semantic_tables_db_table", ["db_id", "table_name"])
