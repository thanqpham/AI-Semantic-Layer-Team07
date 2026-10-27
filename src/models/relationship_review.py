"""Typed relationship review API contracts; SQL input is deliberately forbidden."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ColumnPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_column_id: int
    to_column_id: int


class RelationshipDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_entity_id: int
    to_entity_id: int
    column_pairs: list[ColumnPair]
    relationship_type: Literal["many_to_one", "one_to_one", "one_to_many", "many_to_many"]
    cardinality_confirmation: str | None = None
    expected_revision: int | None = None


class RelationshipDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    impact_token: str | None = None
    acknowledge_impact: bool = False


class RelationshipReviewItem(BaseModel):
    kind: Literal["active", "candidate"]
    id: int
    active_relationship_id: int | None = None
    revision: int
    from_entity: dict[str, Any]
    to_entity: dict[str, Any]
    column_pairs: Any
    relationship_type: str
    source: str
    status: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = None
    unresolved_questions: list[str] = Field(default_factory=list)
    reviewed_by: int | None = None
    reviewer_name: str | None = None
    reviewed_at: datetime | None = None
    on_preview: str = ""
    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)


class RelationshipImpact(BaseModel):
    token: str
    relationship_ids: list[int]
    metric_ids: list[int]
    join_paths: list[list[int]]
    published_metrics: list[dict[str, Any]]
    warnings: list[dict[str, str]] = Field(default_factory=list)
    before_on: str = ""
    after_on: str = ""
