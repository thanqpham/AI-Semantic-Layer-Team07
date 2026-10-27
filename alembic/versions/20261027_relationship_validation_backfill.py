"""Normalize legacy relationship validation after review storage migration."""

from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "relreviewvalidation"
down_revision: str | None = "relreview20261027"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Mark only complete, database-local legacy column pairs as valid."""
    bind = op.get_bind()
    metadata = sa.MetaData()
    relationships = sa.Table("canonical_relationships", metadata, autoload_with=bind)
    tables = sa.Table("semantic_tables", metadata, autoload_with=bind)
    columns = sa.Table("semantic_columns", metadata, autoload_with=bind)
    table_databases = dict(bind.execute(sa.select(tables.c.id, tables.c.db_id)).all())
    column_tables = dict(bind.execute(sa.select(columns.c.id, columns.c.table_id)).all())
    for row in bind.execute(sa.select(relationships)).mappings():
        status = row["validation_status"]
        if status in {"valid", "invalid", "needs_review"}:
            continue
        resolved = status is None and _pairs_resolve(row, table_databases, column_tables)
        values: dict[str, Any] = {"validation_status": "valid" if resolved else "needs_review"}
        if status is not None:
            values["evidence"] = {"legacy_validation_status": status}
        bind.execute(relationships.update().where(relationships.c.id == row["id"]).values(**values))
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.alter_column("validation_status", existing_type=sa.String(20), nullable=False)


def _pairs_resolve(row: Any, tables: dict[int, int], columns: dict[int, int]) -> bool:
    pairs = row["column_pairs"]
    if not isinstance(pairs, list) or not pairs:
        return False
    endpoints = (row["from_entity_id"], row["to_entity_id"])
    if any(tables.get(entity) != row["connection_id"] for entity in endpoints):
        return False
    seen_from: set[int] = set()
    seen_to: set[int] = set()
    for pair in pairs:
        if not isinstance(pair, dict) or set(pair) != {"from_column_id", "to_column_id"}:
            return False
        source, target = pair["from_column_id"], pair["to_column_id"]
        if type(source) is not int or type(target) is not int:
            return False
        if columns.get(source) != endpoints[0] or columns.get(target) != endpoints[1]:
            return False
        if source in seen_from or target in seen_to:
            return False
        seen_from.add(source)
        seen_to.add(target)
    return True


def downgrade() -> None:
    """Restore nullable validation status; keep the safe backfilled values."""
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.alter_column("validation_status", existing_type=sa.String(20), nullable=True)
