"""schema_qualified_tables

Revision ID: f9ead304ba7e
Revises: relreviewvalidation
Create Date: 2026-10-27 22:43:17.685780

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f9ead304ba7e"
down_revision: str | Sequence[str] | None = "relreviewvalidation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_constraint(table_name: str, constraint_name: str) -> bool:
    """Check if a table has a unique constraint with the given name."""
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        insp = sa.inspect(bind)
        constraints = [uc.get("name") for uc in insp.get_unique_constraints(table_name)]
        return constraint_name in constraints
    except Exception:
        return False


def _has_column(table_name: str, column_name: str) -> bool:
    """Check if a table has a column with the given name."""
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        insp = sa.inspect(bind)
        cols = [c.get("name") for c in insp.get_columns(table_name)]
        return column_name in cols
    except Exception:
        return False


def _has_index(table_name: str, index_name: str) -> bool:
    """Check if a table has an index with the given name."""
    bind = op.get_bind()
    if bind is None:
        return False
    try:
        insp = sa.inspect(bind)
        indexes = [idx.get("name") for idx in insp.get_indexes(table_name)]
        return index_name in indexes
    except Exception:
        return False


def upgrade() -> None:
    """Replace bare-name uniqueness without changing persisted identity or schema."""
    drop_uq = _has_constraint("semantic_tables", "uq_semantic_tables_db_table")
    with op.batch_alter_table("semantic_tables") as batch:
        if not _has_column("semantic_tables", "physical_schema_key"):
            batch.add_column(sa.Column("physical_schema_key", sa.String(200), nullable=True))
        if not _has_column("semantic_tables", "table_name_key"):
            batch.add_column(sa.Column("table_name_key", sa.String(200), nullable=True))
        if drop_uq:
            batch.drop_constraint("uq_semantic_tables_db_table", type_="unique")
    if not _has_index("semantic_tables", "uq_semantic_tables_db_schema_table"):
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
    if _has_index("semantic_tables", "uq_semantic_tables_db_schema_table"):
        op.drop_index("uq_semantic_tables_db_schema_table", table_name="semantic_tables")
    restore_uq = not _has_constraint("semantic_tables", "uq_semantic_tables_db_table")
    with op.batch_alter_table("semantic_tables") as batch:
        if _has_column("semantic_tables", "physical_schema_key"):
            batch.drop_column("physical_schema_key")
        if _has_column("semantic_tables", "table_name_key"):
            batch.drop_column("table_name_key")
        if restore_uq:
            batch.create_unique_constraint("uq_semantic_tables_db_table", ["db_id", "table_name"])
