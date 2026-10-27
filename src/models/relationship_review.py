"""Typed contracts for reviewing semantic relationship proposals."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RelationshipType = Literal["many_to_one", "one_to_one", "one_to_many", "many_to_many"]


class RelationshipReviewContract(BaseModel):
    """Reject undeclared fields in relationship review requests."""

    model_config = ConfigDict(extra="forbid")


class ColumnPair(RelationshipReviewContract):
    """An ordered equality mapping between endpoint columns."""

    from_column_id: int = Field(gt=0)
    to_column_id: int = Field(gt=0)


class RelationshipDraft(RelationshipReviewContract):
    """A proposed relationship between two semantic tables."""

    from_entity_id: int = Field(gt=0)
    to_entity_id: int = Field(gt=0)
    column_pairs: list[ColumnPair]
    relationship_type: RelationshipType
    cardinality_confirmation: str | None = None
    expected_revision: int | None = Field(default=None, gt=0)


class RelationshipDecision(RelationshipReviewContract):
    """A reviewer decision against an expected relationship revision."""

    expected_revision: int = Field(gt=0)
    impact_token: str | None = None
    acknowledge_impact: bool = False
