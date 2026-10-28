"""Contracts for unsaved, reviewed AI metric proposals."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SkipValidation

from src.models.metric_agent_output import AgentCandidate
from src.models.metric_definition import MetricDefinition

ProposalMode = Literal["requested", "discovery"]
ReviewStatus = Literal["pass", "needs_revision", "needs_clarification", "rejected", "unsupported", "error"]
RunStatus = Literal["completed", "partial", "needs_clarification", "error"]
MetricReasonCode = Literal[
    "UNRESOLVED_ASSUMPTION",
    "MISSING_GRAIN",
    "VARIANT_CONFLICT",
    "MISSING_RATIO",
    "TECHNICAL_VALIDATION",
    "REVIEWER_FINDING",
    "BUILDER_CLARIFICATION",
    "BUILDER_UNSUPPORTED",
    "BUILDER_REJECTED",
    "INVALID_AGENT_OUTPUT",
    "PROVIDER_FAILURE",
    "OTHER",
]


class MetricOutputIssue(BaseModel):
    """Identify an invalid output field without retaining its input value."""

    field: str
    type: str
    message: str


class MetricExecutionError(BaseModel):
    """Expose a sanitized operational failure separately from business judgment."""

    model_config = ConfigDict(extra="forbid")
    code: Literal["INVALID_AGENT_OUTPUT", "RATE_LIMITED", "QUOTA_EXHAUSTED", "PROVIDER_ERROR", "LLM_BUSY"]
    stage: str
    message: str
    retryable: bool = False
    retry_after_seconds: float | None = None
    validation_errors: list[MetricOutputIssue] = Field(default_factory=list)
    candidate_id: str | None = None
    attempt: int | None = None


class MetricBuildArtifact(BaseModel):
    """Require an actual definition before a draft can reach business review."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    definition: MetricDefinition
    knowledge_id: str | None = None
    variant_id: str | None = None
    criteria: dict[str, str] = Field(default_factory=dict)
    status: Literal["ready"] = "ready"
    reason: str = ""


class BlockedMetricArtifact(BaseModel):
    """Represent a deliberate feasibility decision without a fake definition."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    status: Literal["needs_clarification", "unsupported", "rejected"]
    reason: str = Field(min_length=1)
    knowledge_id: str | None = None
    variant_id: str | None = None
    criteria: dict[str, str] = Field(default_factory=dict)
    definition: None = None


class MetricBuildBatch(BaseModel):
    """Parse individual untrusted items separately to preserve valid siblings."""

    task_id: str = Field(description="Copy the exact server task_id from the user payload. Never invent an ID.")
    candidates: list[SkipValidation[AgentCandidate]] = Field(
        max_length=10,
        description=(
            'Each ready candidate must have name, status="ready", definition={"metric":{'
            '"name":...,"base_entity":...,"formula":... (omit only with query_plan),'
            '"query_plan":...,"filters":[],"excluded_notes":""}}, knowledge_id, variant_id, criteria, reason. '
            "For schema v3 query_plan, formula may be omitted or contain a regular aggregate; the backend normalizes it. "
            "Repairs must also include the supplied candidate_id. Put legacy ratios inside formula. "
            "knowledge_id is the family ID, e.g. aov; variant_id is its variant, e.g. woocommerce_order_value. "
            "Never emit grain, base_entity_id, column_id, or expression_ast; the backend resolves these. "
            "Blocked candidates have status needs_clarification/unsupported/rejected and a reason, no definition."
        ),
    )


class MetricReviewDecision(BaseModel):
    """Model judgment only; audit, sources and retry counts belong to the server."""

    model_config = ConfigDict(extra="forbid")
    candidate_id: str = Field(description="Copy the exact candidate_id assigned to this item in the user payload.")
    status: Literal["pass", "needs_revision", "needs_clarification", "rejected", "unsupported"]
    summary: str = Field(min_length=1)
    issues: list[ReviewIssue] = Field(default_factory=list)
    clarification: str | None = None


class MetricReviewBatch(BaseModel):
    """Correlate business decisions to exactly one coordinator task."""

    task_id: str = Field(description="Copy the exact server task_id from the user payload.")
    decisions: list[SkipValidation[MetricReviewDecision]]


class MetricScopeSelection(BaseModel):
    """Select metadata inventory scope without hidden JSON retries."""

    table_names: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    question: str = ""
    options: list[str] = Field(default_factory=list)


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
    reason_code: MetricReasonCode | None = None
    issues: list[ReviewIssue] = Field(default_factory=list)
    clarification: str | None = None
    sources: list[KnowledgeSource] = Field(default_factory=list)
    variant_id: str | None = None
    criteria: dict[str, str] = Field(default_factory=dict)
    revised: bool = False
    repair_count: int = Field(default=0, ge=0, le=1)
    repair_reason: str | None = None
    repair_feedback: list[ReviewIssue] = Field(default_factory=list)
    requirement: str = ""
    original_definition: dict[str, Any] | None = None
    execution_error: MetricExecutionError | None = None
    handoffs: list[dict[str, Any]] = Field(default_factory=list)


class MetricCandidateReport(BaseModel):
    """Describe a blocked KPI independently of the metric compiler contract."""

    name: str
    proposal_id: str | None = None
    candidate_id: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    review: MetricReview


class MetricProposalReviewRequest(BaseModel):
    """Re-review a human edit against the original business context."""

    definition: MetricDefinition


class MetricProposalReviewResponse(BaseModel):
    """Return a new immutable proposal after a review attempt."""

    proposal_id: str
    candidate_id: str | None = None
    group_id: str | None = None
    definition: MetricDefinition | None
    yaml_preview: str = ""
    review: MetricReview


class MetricDraft(BaseModel):
    """Preserve invalid drafts so validation feedback can reach the repair call."""

    name: str = "Metric đề xuất"
    knowledge_id: str | None = None
    variant_id: str | None = None
    criteria: dict[str, str] = Field(default_factory=dict)
    definition: dict[str, Any] | None = None
    status: Literal["candidate", "needs_clarification", "unsupported", "rejected"] = "candidate"
    reason: str = ""


class MetricDraftBatch(BaseModel):
    """Describe feasible drafts and unavailable KPI candidates separately."""

    candidates: list[MetricDraft] = Field(default_factory=list, max_length=10)
