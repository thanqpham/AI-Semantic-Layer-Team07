"""Pending reviewed suggestions derived from declared or observed values."""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models.db_base import Base, utc_now


class ColumnValueProposalModel(Base):
    """Store safe categorical suggestions separately from approved values."""

    __tablename__ = "column_value_proposals"
    __table_args__ = (
        UniqueConstraint("column_id", name="uq_column_value_proposal_column"),
        CheckConstraint("source IN ('declared', 'observed')", name="ck_column_value_proposal_source"),
        CheckConstraint("status IN ('pending', 'approved', 'dismissed')", name="ck_column_value_proposal_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    column_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("semantic_columns.id", ondelete="CASCADE"), nullable=False
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    values: Mapped[list] = mapped_column(JSON, nullable=False)
    schema_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    reviewed_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
