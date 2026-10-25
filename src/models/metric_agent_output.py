"""Provider-facing metric drafts without backend-owned canonical metadata."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.metric_definition import FilterOperator, MetricConfidence, MetricFunction, MetricQueryPlan

FilterLiteral = str | int | float | bool | None


class AgentFilter(BaseModel):
    """Describe a literal filter by column name only."""

    model_config = ConfigDict(extra="forbid")
    field: str
    operator: FilterOperator
    value: FilterLiteral | list[FilterLiteral] = None


class AgentAggregate(BaseModel):
    """Describe one side of an aggregate ratio."""

    model_config = ConfigDict(extra="forbid")
    function: MetricFunction
    expression: str
    filters: list[AgentFilter] = Field(default_factory=list)


class AgentRatio(BaseModel):
    """Expose independent aggregates and the supported numeric transform."""

    model_config = ConfigDict(extra="forbid")
    numerator: AgentAggregate
    denominator: AgentAggregate
    scale: float = 1
    offset: float = 0


class AgentFormula(BaseModel):
    """Describe a formula without resolved expression trees."""

    model_config = ConfigDict(extra="forbid")
    function: MetricFunction
    expression: str
    ratio: AgentRatio | None = None


class AgentMetricSpec(BaseModel):
    """Keep generated business meaning separate from canonical identities."""

    model_config = ConfigDict(extra="forbid")
    name: str
    base_entity: str
    formula: AgentFormula | None = None
    filters: list[AgentFilter] = Field(default_factory=list)
    status: Literal["pending_approval"] = "pending_approval"
    confidence: MetricConfidence | None = None
    excluded_notes: str = ""
    query_plan: MetricQueryPlan | None = None


class AgentDefinition(BaseModel):
    """Wrap the generated business specification."""

    model_config = ConfigDict(extra="forbid")
    metric: AgentMetricSpec


class AgentCandidate(BaseModel):
    """Describe the provider schema while the workflow validates each raw item."""

    model_config = ConfigDict(extra="forbid")
    name: str
    status: Literal["ready", "unsupported", "needs_clarification", "rejected"]
    definition: AgentDefinition | None = None
    knowledge_id: str | None = Field(default=None, description="Family ID, e.g. aov; never a variant ID.")
    variant_id: str | None = Field(default=None, description="Variant ID, e.g. woocommerce_order_value.")
    criteria: dict[str, str] = Field(default_factory=dict)
    reason: str = ""
    candidate_id: str | None = Field(default=None, description="For repairs, copy the assigned candidate_id exactly.")
