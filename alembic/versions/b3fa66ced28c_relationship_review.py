"""Add relationship review storage without replacing serving FK rows.

Revision ID: b3fa66ced28c
Revises: c02b7c2cd880
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "b3fa66ced28c"
down_revision: str | Sequence[str] | None = "c02b7c2cd880"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add review metadata, normalize legacy validation, and create proposals."""
    _add_canonical_columns()
    _backfill_validation()
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.alter_column("validation_status", existing_type=sa.String(20), nullable=False)
        batch.create_foreign_key(
            "fk_canonical_relationships_reviewer", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
        )
        batch.create_check_constraint("ck_canonical_relationships_source", "source IN ('fk', 'ai', 'manual')")
        batch.create_check_constraint(
            "ck_canonical_relationships_review_status", "review_status IN ('approved', 'disabled', 'needs_review')"
        )
        batch.create_check_constraint("ck_canonical_relationships_revision", "revision >= 1")
        batch.create_index("idx_canonical_relationships_connection_review", ["connection_id", "review_status"])
    _create_candidates()


def _add_canonical_columns() -> None:
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="fk"))
        batch.add_column(sa.Column("review_status", sa.String(20), nullable=False, server_default="approved"))
        batch.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("human_modified", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))


def _create_candidates() -> None:
    """Create separate proposal storage; generated from the ORM metadata."""
    op.create_table("relationship_candidates", *_candidate_columns(), *_candidate_constraints())
    op.create_index(
        "idx_relationship_candidates_connection_status", "relationship_candidates", ["connection_id", "status"]
    )


def _candidate_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("target_relationship_id", sa.Integer(), nullable=True),
        sa.Column("from_entity_id", sa.Integer(), nullable=False),
        sa.Column("to_entity_id", sa.Integer(), nullable=False),
        sa.Column("column_pairs", sa.JSON(), nullable=False),
        sa.Column("relationship_type", sa.String(length=50), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending_review", nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("unresolved_questions", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    )


def _candidate_constraints() -> tuple[sa.Constraint, ...]:
    return (
        sa.CheckConstraint(
            "relationship_type IN ('many_to_one', 'one_to_one', 'one_to_many', 'many_to_many')",
            name="ck_relationship_candidates_type",
        ),
        sa.CheckConstraint("source IN ('fk', 'ai', 'manual')", name="ck_relationship_candidates_source"),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected')", name="ck_relationship_candidates_status"
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_relationship_candidates_confidence"),
        sa.CheckConstraint("revision >= 1", name="ck_relationship_candidates_revision"),
        sa.ForeignKeyConstraint(["connection_id"], ["semantic_databases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["from_entity_id"], ["semantic_tables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_relationship_id"], ["canonical_relationships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["semantic_tables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "fingerprint", name="uq_relationship_candidates_fingerprint"),
    )


def _backfill_validation() -> None:
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
    """Remove review storage while preserving canonical IDs and original payloads."""
    op.drop_table("relationship_candidates")
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.drop_index("idx_canonical_relationships_connection_review")
        batch.drop_constraint("fk_canonical_relationships_reviewer", type_="foreignkey")
        for name in ("source", "review_status", "revision"):
            batch.drop_constraint(f"ck_canonical_relationships_{name}", type_="check")
        for name in ("source", "review_status", "reviewed_by", "reviewed_at", "human_modified", "revision", "evidence"):
            batch.drop_column(name)
