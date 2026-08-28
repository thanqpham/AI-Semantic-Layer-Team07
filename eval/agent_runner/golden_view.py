"""Leakage-safe views over Golden Dataset cases for agent-run collectors."""

from dataclasses import dataclass
from typing import Any

from eval.dataset.loader import DomainDataset
from eval.dataset.models import Dialect


@dataclass(frozen=True)
class MetricCaseView:
    """Leakage-safe metric case: inputs only, never expected_* fields."""

    case_id: str
    request: str
    canonical_context: dict[str, Any]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class QueryCaseView:
    """Leakage-safe query case: question only, never expected outputs."""

    case_id: str
    question: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class GuardrailCaseView:
    """Leakage-safe guardrail case: probe inputs only, never expected_* fields."""

    case_id: str
    sql: str
    dialect: Dialect


def iter_metric_cases(dataset: DomainDataset) -> list[MetricCaseView]:
    """Return leakage-safe views of every metric definition case."""
    return [
        MetricCaseView(
            case_id=case.case_id,
            request=case.request,
            canonical_context=case.canonical_context.model_dump(),
            tags=tuple(case.tags),
        )
        for case in dataset.metric_cases
    ]


def iter_query_cases(dataset: DomainDataset) -> list[QueryCaseView]:
    """Return leakage-safe views of every runtime query case."""
    return [
        QueryCaseView(
            case_id=case.case_id,
            question=case.question,
            tags=tuple(case.tags),
        )
        for case in dataset.query_cases
    ]


def iter_guardrail_cases(dataset: DomainDataset) -> list[GuardrailCaseView]:
    """Return leakage-safe views of every SQL guardrail probe case."""
    return [
        GuardrailCaseView(
            case_id=case.case_id,
            sql=case.sql,
            dialect=case.dialect,
        )
        for case in dataset.guardrail_cases
    ]


def iter_discovery_ids(dataset: DomainDataset) -> list[str]:
    """Return the case ids of every structural discovery case."""
    return [case.case_id for case in dataset.discovery_cases]
