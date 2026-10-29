"""Add isolated relationship candidate and canonical review metadata."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "relreview20261027"
down_revision: str | Sequence[str] | None = "c02b7c2cd880"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _candidate_columns() -> list[sa.Column]:
    """Define relationship candidate storage fields."""
    return [
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
    ]


def _candidate_constraints() -> list[sa.Constraint]:
    """Define candidate validation rules and parent references."""
    return [
        sa.CheckConstraint("source IN ('fk', 'ai', 'manual')", name="ck_relationship_candidates_source"),
        sa.CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected')", name="ck_relationship_candidates_status"
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_relationship_candidates_confidence"),
        sa.CheckConstraint(
            "relationship_type IN ('many_to_one', 'one_to_one', 'one_to_many', 'many_to_many')",
            name="ck_relationship_candidates_type",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_relationship_candidates_revision"),
        sa.ForeignKeyConstraint(["connection_id"], ["semantic_databases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_entity_id"], ["semantic_tables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_relationship_id"], ["canonical_relationships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["to_entity_id"], ["semantic_tables.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "fingerprint", name="uq_relationship_candidates_fingerprint"),
    ]


def _create_candidate_table() -> None:
    """Create isolated relationship-candidate persistence and lookup indexes."""
    op.create_table("relationship_candidates", *_candidate_columns(), *_candidate_constraints())
    op.create_index(
        "idx_relationship_candidates_connection_status", "relationship_candidates", ["connection_id", "status"]
    )


def _add_canonical_review_metadata() -> None:
    """Add defaults and reviewer audit state to legacy serving relationships."""
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="fk"))
        batch.add_column(sa.Column("review_status", sa.String(20), nullable=False, server_default="approved"))
        batch.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("human_modified", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("evidence", sa.JSON(), nullable=False, server_default="{}"))
        batch.create_foreign_key(
            "fk_canonical_relationships_reviewer", "users", ["reviewed_by"], ["id"], ondelete="SET NULL"
        )
        batch.create_check_constraint("ck_canonical_relationships_source", "source IN ('fk', 'ai', 'manual')")
        batch.create_check_constraint(
            "ck_canonical_relationships_review_status",
            "review_status IN ('approved', 'disabled', 'needs_review')",
        )
        batch.create_check_constraint("ck_canonical_relationships_revision", "revision >= 1")
        batch.create_index("idx_canonical_relationships_connection_review", ["connection_id", "review_status"])


def _drop_canonical_review_metadata() -> None:
    """Remove only review metadata and its constraints from canonical rows."""
    with op.batch_alter_table("canonical_relationships") as batch:
        batch.drop_index("idx_canonical_relationships_connection_review")
        batch.drop_constraint("ck_canonical_relationships_revision", type_="check")
        batch.drop_constraint("ck_canonical_relationships_review_status", type_="check")
        batch.drop_constraint("ck_canonical_relationships_source", type_="check")
        batch.drop_constraint("fk_canonical_relationships_reviewer", type_="foreignkey")
        for column in (
            "source",
            "review_status",
            "reviewed_by",
            "reviewed_at",
            "human_modified",
            "revision",
            "evidence",
        ):
            batch.drop_column(column)


def upgrade() -> None:
    """Create review candidates and mark existing serving relationships approved."""
    _create_candidate_table()
    _add_canonical_review_metadata()


def downgrade() -> None:
    """Remove only relationship review storage while retaining the serving graph."""
    op.drop_table("relationship_candidates")
    _drop_canonical_review_metadata()
