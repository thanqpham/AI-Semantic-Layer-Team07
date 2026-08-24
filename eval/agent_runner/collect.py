"""Orchestrator: run every stage and persist candidates for one agent run."""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval.agent_runner.adapters import ProductionGuardrailAdapter
from eval.agent_runner.bootstrap import AgentRunContext
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.agent_runner.discovery import collect_discovery, introspect_target
from eval.agent_runner.enrichment import collect_enrichment, run_enrichment_pipeline
from eval.agent_runner.golden_view import (
    GuardrailCaseView,
    iter_discovery_ids,
    iter_guardrail_cases,
    iter_metric_cases,
    iter_query_cases,
)
from eval.agent_runner.metrics_stage import MetricCollectResult, collect_metrics
from eval.agent_runner.query_stage import OracleInput, collect_queries
from eval.agent_runner.resolver import ResolverFilter
from eval.dataset.loader import DomainDataset
from eval.dataset.models import QueryCaseExpected, WhereConditionExpectation
from eval.evaluator.discovery_eval import CandidateDiscoveryOutput
from eval.evaluator.schemas import (
    CandidateCompilerOutput,
    CandidateEnrichmentOutput,
    CandidateGuardrailOutput,
    CandidateMetricOutput,
    EvaluationConfig,
)

logger = logging.getLogger(__name__)

CANDIDATES_FILENAME = "candidates.json"
DEFAULT_ORACLE_LIMIT = 100
QUERY_MODES = frozenset({"resolver", "oracle"})

# Schema-forced placeholder values in the metric candidate contract (spec D6):
# the contract has no empty representation for these fields.
CONTRACT_GAPS: dict[str, Any] = {
    "metric": ["business_formula", "default_time_grain"],
    "note": (
        "business_formula is always empty and default_time_grain is always 'day': "
        "the candidate contract forces non-empty values (spec decision D6)."
    ),
    "enrichment": [],
    "enrichment_note": (
        "RESOLVED: entity_f1/dimension_f1 were previously declared as gaps because "
        "the connector emitted PHYSICAL table names against golden CANONICAL names; "
        "CanonicalResolver now maps identifiers to canonical names before scoring, "
        "so no enrichment gap remains declared (kept for manifest key stability)."
    ),
}

# Canonical where operators -> resolver operator vocabulary; unmapped operators
# (e.g. 'like') are passed through verbatim and fail closed as UNKNOWN_OPERATOR.
_RESOLVER_OPERATORS: dict[str, str] = {
    "=": "eq",
    "!=": "neq",
    ">": "gt",
    ">=": "gte",
    "<": "lt",
    "<=": "lte",
    "in": "in",
    "not_in": "not_in",
}


@dataclass
class AgentCandidates:
    """Collected candidates plus run manifest (provenance)."""

    discovery: dict[str, CandidateDiscoveryOutput] = field(default_factory=dict)
    enrichment: dict[str, CandidateEnrichmentOutput] = field(default_factory=dict)
    metrics: dict[str, CandidateMetricOutput] = field(default_factory=dict)
    compiler: dict[str, CandidateCompilerOutput] = field(default_factory=dict)
    guardrail: dict[str, CandidateGuardrailOutput] = field(default_factory=dict)
    manifest: dict[str, Any] = field(default_factory=dict)


async def collect_candidates(
    ctx: AgentRunContext,
    dataset: DomainDataset,
    *,
    query_mode: str = "resolver",
    enrichment_override: dict | None = None,
) -> AgentCandidates:
    """Run discovery, enrichment, metrics, query, and guardrail collection."""
    if query_mode not in QUERY_MODES:
        raise ValueError(f"unknown query mode: {query_mode!r}")
    raw = await introspect_target(ctx)
    conn_id = await run_enrichment_pipeline(ctx, raw, enrichment=enrichment_override)
    entity_resolver = CanonicalResolver.from_dataset(dataset, {})
    discovery_ids = iter_discovery_ids(dataset)
    discovery = await collect_discovery(ctx, discovery_ids, raw)
    enrichment = await collect_enrichment(ctx, conn_id, discovery_ids, entity_resolver)
    metric_result = await collect_metrics(ctx, conn_id, iter_metric_cases(dataset), entity_resolver)
    compiler_resolver = CanonicalResolver.from_dataset(dataset, metric_result.metric_ids)
    compiler = await _collect_compiler(ctx, conn_id, dataset, query_mode, metric_result, compiler_resolver)
    guardrail = await collect_guardrails(iter_guardrail_cases(dataset))
    return AgentCandidates(
        discovery=discovery,
        enrichment=enrichment,
        metrics=metric_result.candidates,
        compiler=compiler,
        guardrail=guardrail,
        manifest=_manifest(ctx, query_mode, entity_resolver, compiler_resolver),
    )


async def collect_guardrails(cases: list[GuardrailCaseView]) -> dict[str, CandidateGuardrailOutput]:
    """Validate every guardrail probe with the product adapter (pure, no LLM)."""
    adapter = ProductionGuardrailAdapter(EvaluationConfig())
    outputs: dict[str, CandidateGuardrailOutput] = {}
    for case in cases:
        outputs[case.case_id] = await _validate_guardrail(adapter, case)
    return outputs


async def _validate_guardrail(
    adapter: ProductionGuardrailAdapter,
    case: GuardrailCaseView,
) -> CandidateGuardrailOutput:
    """Run one probe; a crash degrades to a rejected candidate, never kills the run."""
    try:
        return await adapter.validate(case.sql, case.dialect)
    except Exception:
        logger.warning("guardrail case %s crashed unexpectedly", case.case_id, exc_info=True)
        return CandidateGuardrailOutput(accepted=False, error_code="AGENT_UNEXPECTED_ERROR")


async def _collect_compiler(
    ctx: AgentRunContext,
    conn_id: int,
    dataset: DomainDataset,
    query_mode: str,
    metric_result: MetricCollectResult,
    resolver: CanonicalResolver,
) -> dict[str, CandidateCompilerOutput]:
    """Compile query candidates in the requested mode, with oracle inputs."""
    oracle_inputs = _build_oracle_inputs(dataset, metric_result) if query_mode == "oracle" else None
    return await collect_queries(
        ctx,
        conn_id,
        iter_query_cases(dataset),
        mode=query_mode,
        metric_map=metric_result.metric_ids,
        oracle_inputs=oracle_inputs,
        resolver=resolver,
    )


def write_candidates(run_dir: Path, candidates: AgentCandidates) -> Path:
    """Serialize every candidate dict plus the manifest to candidates.json."""
    payload = {
        "manifest": candidates.manifest,
        "discovery": _dump(candidates.discovery),
        "enrichment": _dump(candidates.enrichment),
        "metrics": _dump(candidates.metrics),
        "compiler": _dump(candidates.compiler),
        "guardrail": _dump(candidates.guardrail),
    }
    path = run_dir / CANDIDATES_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _dump(candidates: dict[str, Any]) -> dict[str, Any]:
    """JSON-dump every pydantic candidate in one dict."""
    return {case_id: item.model_dump(mode="json") for case_id, item in candidates.items()}


def _manifest(
    ctx: AgentRunContext,
    query_mode: str,
    *resolvers: CanonicalResolver,
) -> dict[str, Any]:
    """Build the provenance manifest; no secrets, only the throwaway run dir."""
    return {
        "run_dir": str(ctx.run_dir),
        "created_at": datetime.now(UTC).isoformat(),
        "candidate_source": "agent_live",
        "query_mode": query_mode,
        "contract_gaps": CONTRACT_GAPS,
        "identity_resolutions": _dedupe_logs(entry for r in resolvers for entry in r.resolutions),
        "identity_unresolved": _dedupe_logs(entry for r in resolvers for entry in r.unresolved),
    }


def _dedupe_logs(entries: Iterable[dict[str, str]]) -> list[dict[str, str]]:
    """Stable de-duplication of identity audit log entries."""
    seen: set[tuple[tuple[str, str], ...]] = set()
    unique: list[dict[str, str]] = []
    for entry in entries:
        key = tuple(sorted(entry.items()))
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def _build_oracle_inputs(dataset: DomainDataset, metric_result: MetricCollectResult) -> dict[str, OracleInput]:
    """Derive ground-truth selections from expected cases (spec section 3 exception).

    This is the single sanctioned reader of ``expected`` outside the evaluator.
    Expected dimensions/filters carry canonical entity names; they are translated
    to physical ``table.column`` via the canonical registry before use.
    """
    case_id_by_name = _metric_case_by_name(dataset)
    inputs: dict[str, OracleInput] = {}
    for case in dataset.query_cases:
        oracle = _oracle_for_case(dataset, case.expected, case_id_by_name, metric_result)
        if oracle is not None:
            inputs[case.case_id] = oracle
    return inputs


def _metric_case_by_name(dataset: DomainDataset) -> dict[str, str]:
    """Index metric case ids by their expected metric name."""
    return {
        case.expected_metric.name: case.case_id for case in dataset.metric_cases if case.expected_metric is not None
    }


def _physical_dimension(dataset: DomainDataset, dotted: str) -> str | None:
    """Translate one canonical ``entity.name`` to its physical ``table.field``.

    The physical column is the matched dimension's ``field`` (the YAML contract
    permits ``name != field``), never the canonical name itself.
    """
    entity_name, _, dimension_name = dotted.partition(".")
    entity = dataset.canonical_entities.get(entity_name)
    if entity is None:
        return None
    for dimension in entity.dimensions:
        if dimension.name == dimension_name:
            return f"{entity.table_mapping}.{dimension.field}"
    return None


def _oracle_for_case(
    dataset: DomainDataset,
    expected: QueryCaseExpected | None,
    case_id_by_name: dict[str, str],
    metric_result: MetricCollectResult,
) -> OracleInput | None:
    """Map one expected canonical query onto an OracleInput; None when unmappable."""
    canonical = getattr(expected, "canonical_query", None)
    if canonical is None:
        return None
    metric_ids = _expected_metric_ids(canonical.metrics, case_id_by_name, metric_result)
    dimensions = _physical_dimensions(dataset, canonical.dimensions)
    filters = _oracle_filters(dataset, canonical.where_conditions)
    if metric_ids is None or dimensions is None or filters is None:
        return None
    return OracleInput(
        metric_ids=metric_ids,
        dimensions=dimensions,
        filters=filters,
        limit=getattr(canonical, "limit", None) or DEFAULT_ORACLE_LIMIT,
    )


def _expected_metric_ids(
    names: list[str],
    case_id_by_name: dict[str, str],
    metric_result: MetricCollectResult,
) -> tuple[int, ...] | None:
    """Map expected metric names to persisted ids; None when any is unmappable."""
    metric_ids: list[int] = []
    for name in names:
        metric_case_id = case_id_by_name.get(name)
        if metric_case_id is None or metric_case_id not in metric_result.metric_ids:
            return None
        metric_ids.append(metric_result.metric_ids[metric_case_id])
    return tuple(metric_ids)


def _physical_dimensions(
    dataset: DomainDataset,
    names: list[str],
) -> tuple[str, ...] | None:
    """Translate canonical dimension names; None when any is unmappable."""
    translated: list[str] = []
    for name in names:
        physical = _physical_dimension(dataset, name)
        if physical is None:
            return None
        translated.append(physical)
    return tuple(translated)


def _oracle_filters(
    dataset: DomainDataset,
    conditions: list[WhereConditionExpectation],
) -> tuple[ResolverFilter, ...] | None:
    """Translate expected where conditions into resolver filters; None if unmappable."""
    filters: list[ResolverFilter] = []
    for item in conditions:
        dimension = _physical_dimension(dataset, item.dimension)
        if dimension is None:
            return None
        filters.append(
            ResolverFilter(
                dimension=dimension,
                operator=_RESOLVER_OPERATORS.get(item.operator, item.operator),
                value=item.value,
            )
        )
    return tuple(filters)
