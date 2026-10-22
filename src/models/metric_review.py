"""Contracts for unsaved, reviewed AI metric proposals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.metric_definition import MetricDefinition

ProposalMode = Literal["requested", "discovery"]
ReviewStatus = Literal["pass", "needs_revision", "needs_clarification", "rejected", "unsupported", "error"]


class ReviewIssue(BaseModel):
    """Describe an evidenced problem and its required action."""

    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    action: str = Field(min_length=1)


class KnowledgeSource(BaseModel):
    """Identify a curated source, never a URL invented by the model."""

    id: str
    title: str
    url: str
    reviewed_at: str


class MetricReview(BaseModel):
    """Return a bounded review without changing human approval status."""

    model_config = ConfigDict(extra="forbid")
    status: ReviewStatus
    summary: str = Field(min_length=1)
    issues: list[ReviewIssue] = Field(default_factory=list)
    clarification: str | None = None
    sources: list[KnowledgeSource] = Field(default_factory=list)
    revised: bool = False
    repair_count: int = Field(default=0, ge=0, le=1)
    repair_reason: str | None = None
    repair_feedback: list[ReviewIssue] = Field(default_factory=list)
    requirement: str = ""
    original_definition: dict[str, Any] | None = None


class MetricCandidateReport(BaseModel):
    """Describe a blocked KPI independently of the metric compiler contract."""

    name: str
    proposal_id: str | None = None
    review: MetricReview


class MetricProposalReviewRequest(BaseModel):
    """Re-review a human edit against the original business context."""

    definition: MetricDefinition


class MetricProposalReviewResponse(BaseModel):
    """Return a new immutable proposal after a review attempt."""

    proposal_id: str
    definition: MetricDefinition | None
    yaml_preview: str = ""
    review: MetricReview


class MetricDraft(BaseModel):
    """Preserve invalid drafts so validation feedback can reach the repair call."""

    name: str = "Metric đề xuất"
    knowledge_id: str | None = None
    definition: dict[str, Any] | None = None
    status: Literal["candidate", "needs_clarification", "unsupported", "rejected"] = "candidate"
    reason: str = ""


class MetricDraftBatch(BaseModel):
    """Describe feasible drafts and unavailable KPI candidates separately."""

    candidates: list[MetricDraft] = Field(default_factory=list, max_length=10)
