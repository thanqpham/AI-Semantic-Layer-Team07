"""schema_qualified_tables

Revision ID: f9ead304ba7e
Revises: relreviewvalidation
Create Date: 2026-10-27 22:43:17.685780

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9ead304ba7e"
down_revision: Union[str, Sequence[str], None] = "relreviewvalidation"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace bare-name uniqueness without changing persisted identity or schema."""
    with op.batch_alter_table("semantic_tables") as batch:
        batch.add_column(sa.Column("physical_schema_key", sa.String(200), nullable=True))
        batch.add_column(sa.Column("table_name_key", sa.String(200), nullable=True))
        batch.drop_constraint("uq_semantic_tables_db_table", type_="unique")
    op.create_index(
        "uq_semantic_tables_db_schema_table",
        "semantic_tables",
        [
            "db_id",
            sa.text("coalesce(physical_schema_key, physical_schema, '')"),
            sa.text("coalesce(table_name_key, table_name)"),
        ],
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
        batch.drop_column("physical_schema_key")
        batch.drop_column("table_name_key")
        batch.create_unique_constraint("uq_semantic_tables_db_table", ["db_id", "table_name"])
