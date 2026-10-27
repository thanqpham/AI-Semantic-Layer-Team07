"""Proposed relationships kept separate from the serving canonical graph."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.db_base import Base, utc_now


class RelationshipCandidateModel(Base):
    """Store reviewable proposals and copy-on-write edits to active relationships."""

    __tablename__ = "relationship_candidates"
    __table_args__ = (
        UniqueConstraint("connection_id", "fingerprint", name="uq_relationship_candidates_fingerprint"),
        Index("idx_relationship_candidates_connection_status", "connection_id", "status"),
        CheckConstraint("source IN ('fk', 'ai', 'manual')", name="ck_relationship_candidates_source"),
        CheckConstraint(
            "status IN ('pending_review', 'approved', 'rejected')", name="ck_relationship_candidates_status"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_relationship_candidates_confidence"),
        CheckConstraint("revision >= 1", name="ck_relationship_candidates_revision"),
        CheckConstraint(
            "relationship_type IN ('many_to_one', 'one_to_one', 'one_to_many', 'many_to_many')",
            name="ck_relationship_candidates_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("semantic_databases.id", ondelete="CASCADE"))
    target_relationship_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_relationships.id", ondelete="SET NULL")
    )
    from_entity_id: Mapped[int] = mapped_column(ForeignKey("semantic_tables.id", ondelete="CASCADE"))
    to_entity_id: Mapped[int] = mapped_column(ForeignKey("semantic_tables.id", ondelete="CASCADE"))
    column_pairs: Mapped[list[dict[str, int]]] = mapped_column(JSON, default=list)
    relationship_type: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending_review", server_default="pending_review")
    fingerprint: Mapped[str] = mapped_column(String(64))
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    confidence: Mapped[float | None] = mapped_column(Float)
    unresolved_questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
