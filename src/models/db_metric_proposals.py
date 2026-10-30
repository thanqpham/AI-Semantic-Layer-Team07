"""Durable review evidence for new AI-generated metrics."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.db_base import Base, utc_now


class MetricProposalModel(Base):
    """Keep reviewed inputs and outputs separate from the published catalog."""

    __tablename__ = "metric_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pass','needs_revision','needs_clarification','rejected','unsupported','error')",
            name="ck_metric_proposals_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    db_id: Mapped[int] = mapped_column(ForeignKey("semantic_databases.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("metric_proposals.id", ondelete="SET NULL"))
    context: Mapped[dict[str, Any]] = mapped_column(JSON)
    original_definition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    final_definition: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    review: Mapped[dict[str, Any]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    schema_fingerprint: Mapped[str] = mapped_column(String(64))
    metric_id: Mapped[int | None] = mapped_column(ForeignKey("semantic_metrics.id", ondelete="SET NULL"))
    metric_version: Mapped[int | None] = mapped_column(Integer)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("metric_requests.id", ondelete="SET NULL"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
