"""Typed metric definition contract shared by generation, persistence, and compilation."""

from __future__ import annotations

import logging
import math
from typing import Any, Literal

import sqlglot
import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlglot import exp

logger = logging.getLogger(__name__)

MetricFunction = Literal["SUM", "COUNT", "COUNT_DISTINCT", "AVG", "MIN", "MAX"]
MetricStatus = Literal["draft", "pending_approval", "approved", "needs_review", "unverified"]
MetricConfidence = Literal["low", "medium", "high"]
FilterOperator = Literal["eq", "neq", "gt", "gte", "lt", "lte", "in", "not_in", "is_null", "is_not_null"]
ExpressionKind = Literal["column", "literal", "add", "sub", "mul", "div", "neg"]
TIMESTAMP_DIFF_HOURS = "TIMESTAMP_DIFF_HOURS"

_ALLOWED_EXPRESSION_NODES = (
    exp.Column,
    exp.Identifier,
    exp.Literal,
    exp.Paren,
    exp.Add,
    exp.Sub,
    exp.Mul,
    exp.Div,
    exp.Neg,
    exp.GT,
    exp.GTE,
    exp.LT,
    exp.LTE,
    exp.EQ,
    exp.NEQ,
    exp.Case,
    exp.If,
    exp.When,
    exp.Is,
    exp.Not,
    exp.Null,
    exp.Boolean,
    exp.In,
    exp.Tuple,
    exp.Between,
    exp.Like,
    exp.ILike,
)


class MetricDiagnostic(BaseModel):
    """Describe why a canonical metric requires review."""

    code: str
    message: str


class MetricExpressionNode(BaseModel):
    """Represent one typed node in a resolved arithmetic expression."""

    kind: ExpressionKind | Literal["timestamp_diff_hours"]
    column_id: int | None = None
    value: float | None = None
    children: list[MetricExpressionNode] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_shape(self) -> MetricExpressionNode:
        """Reject malformed ASTs before the compiler indexes their children."""
        expected_children = {
            "column": 0,
            "literal": 0,
            "neg": 1,
            "timestamp_diff_hours": 2,
            "add": 2,
            "sub": 2,
            "mul": 2,
            "div": 2,
        }[self.kind]
        if len(self.children) != expected_children:
            raise ValueError(f"{self.kind} expression requires {expected_children} children")
        if self.kind == "column" and self.column_id is None:
            raise ValueError("column expression requires a column_id")
        if self.kind == "literal" and self.value is None:
            raise ValueError("literal expression requires a value")
        if self.kind == "column" and self.value is not None:
            raise ValueError("column expression cannot contain a literal value")
        if self.kind == "literal" and self.column_id is not None:
            raise ValueError("literal expression cannot contain a column_id")
        if self.kind not in {"column", "literal"} and (self.column_id is not None or self.value is not None):
            raise ValueError(f"{self.kind} expression cannot contain a column_id or literal value")
        if self.value is not None and not math.isfinite(self.value):
            raise ValueError("literal expression must be finite")
        if self.kind == "timestamp_diff_hours" and any(child.kind != "column" for child in self.children):
            raise ValueError("timestamp difference requires two column expressions")
        return self


class MetricGrain(BaseModel):
    """Identify the canonical columns that uniquely define the base grain."""

    column_ids: list[int] = Field(default_factory=list)


class MetricFormula(BaseModel):
    """Describe a deterministic aggregation over a base-entity expression."""

    function: MetricFunction
    expression: str = Field(..., min_length=1, max_length=1000)
    expression_ast: MetricExpressionNode | None = None
    ratio: MetricRatio | None = None

    @field_validator("function", mode="before")
    @classmethod
    def normalize_function(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @field_validator("expression", mode="before")
    @classmethod
    def normalize_expression(cls, value: Any) -> Any:
        """Trim an expression."""
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("expression")
    @classmethod
    def validate_expression(cls, value: str) -> str:
        """Accept arithmetic and the fixed safe timestamp-difference primitive."""
        cleaned = value.strip()
        if cleaned == "*":
            return cleaned
        try:
            parsed = sqlglot.parse_one(cleaned)
        except sqlglot.errors.ParseError as exc:
            raise ValueError("Invalid metric expression") from exc
        if is_timestamp_diff_hours(parsed):
            return cleaned
        for node in parsed.walk():
            if not isinstance(node, _ALLOWED_EXPRESSION_NODES):
                raise ValueError(f"Expression node {type(node).__name__} is not allowed")
            if isinstance(node, exp.Column) and node.table:
                raise ValueError("Metric expressions cannot reference another entity")
        return cleaned

    @model_validator(mode="after")
    def validate_star(self) -> MetricFormula:
        """Allow star only for COUNT."""
        if self.expression == "*" and self.function != "COUNT":
            raise ValueError("star is only valid with COUNT")
        return self


def is_timestamp_diff_hours(node: exp.Expression) -> bool:
    """Recognize the only supported temporal function in metric expressions."""
    return (
        isinstance(node, exp.Anonymous)
        and node.name.upper() == TIMESTAMP_DIFF_HOURS
        and len(node.expressions) == 2
        and all(isinstance(item, exp.Column) and not item.table for item in node.expressions)
    )


_OP_MAP = {
    "=": "eq",
    "==": "eq",
    "eq": "eq",
    "!=": "neq",
    "<>": "neq",
    "neq": "neq",
    ">": "gt",
    "gt": "gt",
    ">=": "gte",
    "gte": "gte",
    "<": "lt",
    "lt": "lt",
    "<=": "lte",
    "lte": "lte",
    "in": "in",
    "not in": "not_in",
    "not_in": "not_in",
    "is null": "is_null",
    "is_null": "is_null",
    "is not null": "is_not_null",
    "is_not_null": "is_not_null",
}


class MetricFilter(BaseModel):
    """Represent a fixed predicate without embedding SQL."""

    field: str = Field(..., min_length=1, max_length=200, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    column_id: int | None = None
    operator: FilterOperator
    value: Any = None

    @field_validator("operator", mode="before")
    @classmethod
    def normalize_operator(cls, value: Any) -> Any:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return _OP_MAP.get(cleaned, cleaned)
        return value

    @model_validator(mode="after")
    def validate_value_shape(self) -> MetricFilter:
        """Validate operator-specific value presence and collection shape."""
        if self.operator in {"is_null", "is_not_null"}:
            if self.value is not None:
                raise ValueError(f"{self.operator} does not accept a value")
        elif self.operator in {"in", "not_in"}:
            if not isinstance(self.value, list) or not self.value:
                raise ValueError(f"{self.operator} requires a non-empty list")
        elif self.value is None:
            raise ValueError(f"{self.operator} requires a value")
        return self


class MetricAggregate(BaseModel):
    """Describe one independently aggregated side of a metric ratio."""

    function: MetricFunction
    expression: str = Field(..., min_length=1, max_length=1000)
    expression_ast: MetricExpressionNode | None = None
    filters: list[MetricFilter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_aggregate_expression(self) -> MetricAggregate:
        """Apply the same safe-expression rules as a regular metric formula."""
        MetricFormula(function=self.function, expression=self.expression)
        return self


class MetricRatio(BaseModel):
    """Define a ratio of independently aggregated values."""

    numerator: MetricAggregate
    denominator: MetricAggregate
    scale: float = 1.0
    offset: float = 0.0

    @field_validator("scale", "offset", mode="before")
    @classmethod
    def validate_finite_transform(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("ratio scale and offset must be finite numbers")
        return value


class MetricPlanFilter(MetricFilter):
    """Predicate on a qualified source field or a prior stage output."""

    field: str = Field(..., min_length=1, max_length=401, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*(?:\.[A-Za-z_][A-Za-z0-9_$]*){0,2}$")


class MetricPlanField(BaseModel):
    """A named grouping key selected from a source or prior stage."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    expression: str = Field(..., min_length=1, max_length=401)
    column_id: int | None = None

    @field_validator("expression")
    @classmethod
    def validate_group_expression(cls, value: str) -> str:
        parsed = sqlglot.parse_one(value.strip())
        if any(not isinstance(node, (exp.Column, exp.Identifier)) for node in parsed.walk()):
            raise ValueError("Metric plan grouping expressions must reference columns")
        return value.strip()


class MetricPlanAggregate(BaseModel):
    """Named aggregate in one stage of a multi-table metric plan."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    function: MetricFunction
    expression: str = Field(..., min_length=1, max_length=1000)
    filters: list[MetricPlanFilter] = Field(default_factory=list)

    @field_validator("function", mode="before")
    @classmethod
    def normalize_plan_function(cls, value: Any) -> Any:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("expression")
    @classmethod
    def validate_plan_expression(cls, value: str) -> str:
        if value.strip() == "*":
            return "*"
        parsed = sqlglot.parse_one(value.strip())
        allowed = (exp.Column, exp.Identifier, exp.Literal, exp.Paren, exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Neg)
        if any(not isinstance(node, allowed) for node in parsed.walk()):
            raise ValueError("Metric plan expressions allow only columns, literals, and arithmetic")
        return value.strip()


class MetricPlanStage(BaseModel):
    """One grouped source or a later aggregation over an earlier stage."""

    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[A-Za-z_][A-Za-z0-9_$]*$")
    base_entity: str | None = Field(default=None, min_length=1, max_length=200)
    source_stage: str | None = Field(default=None, min_length=1, max_length=100)
    joins: list[str] = Field(default_factory=list)
    group_by: list[MetricPlanField] = Field(default_factory=list)
    aggregates: list[MetricPlanAggregate] = Field(..., min_length=1)
    filters: list[MetricPlanFilter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan_source(self) -> MetricPlanStage:
        if bool(self.base_entity) == bool(self.source_stage):
            raise ValueError("A metric plan stage requires exactly one base_entity or source_stage")
        if self.base_entity and self.joins and self.base_entity in self.joins:
            raise ValueError("A metric plan stage cannot join its base entity to itself")
        if len({field.name for field in self.group_by}) != len(self.group_by):
            raise ValueError("Metric plan grouping names must be unique")
        if len({item.name for item in self.aggregates}) != len(self.aggregates):
            raise ValueError("Metric plan aggregate names must be unique")
        return self


class MetricQueryPlan(BaseModel):
    """Finite, metadata-resolved stages for multi-table metric compilation."""

    stages: list[MetricPlanStage] = Field(..., min_length=1)
    output_expression: str = Field(..., min_length=1, max_length=1000)

    @field_validator("output_expression")
    @classmethod
    def validate_output_expression(cls, value: str) -> str:
        parsed = sqlglot.parse_one(value.strip())
        allowed = (exp.Column, exp.Identifier, exp.Literal, exp.Paren, exp.Add, exp.Sub, exp.Mul, exp.Div, exp.Neg)
        if any(not isinstance(node, allowed) for node in parsed.walk()):
            raise ValueError("Metric plan output allows only stage references and arithmetic")
        return value.strip()

    @model_validator(mode="after")
    def validate_stage_graph(self) -> MetricQueryPlan:
        names = [stage.name for stage in self.stages]
        if len(names) != len(set(names)):
            raise ValueError("Metric plan stage names must be unique")
        seen: set[str] = set()
        for stage in self.stages:
            if stage.source_stage and stage.source_stage not in seen:
                raise ValueError("Metric plan stages must reference an earlier stage")
            seen.add(stage.name)
        return self


MetricFormula.model_rebuild()


class MetricSpec(BaseModel):
    """Canonical business metric persisted in the metadata store."""

    name: str = Field(..., min_length=1, max_length=200)
    formula: MetricFormula
    base_entity: str = Field(..., min_length=1, max_length=200)
    base_entity_id: int | None = None
    grain: MetricGrain = Field(default_factory=MetricGrain)
    filters: list[MetricFilter] = Field(default_factory=list)
    query_plan: MetricQueryPlan | None = None
    status: MetricStatus = "pending_approval"
    confidence: MetricConfidence | None = None
    excluded_notes: str = Field(default="", max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize_ratio_location(cls, value: Any) -> Any:
        """Normalize legacy ratios and keep plan formulas as a compatibility field."""
        if isinstance(value, dict) and "ratio" in value:
            formula = value.get("formula")
            if not isinstance(formula, dict):
                raise ValueError("formula.ratio cần formula hợp lệ.")
            if formula.get("ratio") is not None and formula["ratio"] != value["ratio"]:
                raise ValueError("metric.ratio và formula.ratio mâu thuẫn; chỉ cung cấp một cách tính.")
            value = {**value, "formula": {**formula, "ratio": value["ratio"]}}
            value.pop("ratio")
        if isinstance(value, dict) and value.get("query_plan") is not None:
            value = {**value, "formula": {"function": "COUNT", "expression": "*"}}
        return value

    @field_validator("filters", mode="before")
    @classmethod
    def normalize_filters(cls, value: Any) -> list[Any]:
        if not value or not isinstance(value, list):
            return []
        valid_filters = []
        for item in value:
            if isinstance(item, MetricFilter):
                valid_filters.append(item)
            elif isinstance(item, dict):
                fld = item.get("field") or item.get("column") or item.get("name")
                raw_op = str(item.get("operator", "eq")).strip().lower()
                op = _OP_MAP.get(raw_op)
                val = item.get("value")
                if fld and op:
                    valid_filters.append(
                        {
                            "field": str(fld).strip(),
                            "column_id": item.get("column_id"),
                            "operator": op,
                            "value": val,
                        }
                    )
        return valid_filters

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> str:
        cleaned = value.strip().lower() if isinstance(value, str) else ""
        if cleaned in {"draft", "pending_approval", "approved", "needs_review", "unverified"}:
            return cleaned
        return "pending_approval"

    @field_validator("confidence", mode="before")
    @classmethod
    def normalize_confidence(cls, value: Any) -> str | None:
        if isinstance(value, str) and value.strip().lower() in {"low", "medium", "high"}:
            return value.strip().lower()
        return "high"


class MetricDefinition(BaseModel):
    """Top-level wrapper used by JSON persistence and YAML preview."""

    schema_version: Literal[1, 2, 3] = 1
    metric: MetricSpec
    diagnostics: list[MetricDiagnostic] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_metric_payload(cls, data: Any) -> Any:
        """Wrap flat metric specification in a 'metric' container if needed."""
        if isinstance(data, dict):
            if "metric" in data and isinstance(data["metric"], dict):
                if "excluded_notes" in data:
                    metric = data["metric"]
                    if "excluded_notes" in metric and metric["excluded_notes"] != data["excluded_notes"]:
                        raise ValueError("excluded_notes trong và ngoài metric mâu thuẫn.")
                    data = {**data, "metric": {**metric, "excluded_notes": data["excluded_notes"]}}
                    data.pop("excluded_notes")
                return data
            if "name" in data or "formula" in data or "base_entity" in data:
                return {"metric": data}
        return data

    @model_validator(mode="after")
    def normalize_query_plan_version(self) -> MetricDefinition:
        """Every structured query plan is persisted under its canonical version."""
        if self.metric.query_plan is not None:
            self.schema_version = 3
        return self

    def to_yaml(self) -> str:
        """Render a stable, Unicode YAML preview."""
        payload = self.model_dump(mode="json", exclude_none=True)
        if not payload["metric"].get("filters"):
            payload["metric"].pop("filters", None)
        return yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
