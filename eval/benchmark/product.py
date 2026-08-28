"""Adapter that runs the existing isolated agent collector as a benchmark scenario."""

from __future__ import annotations

from eval.agent_runner.bootstrap import AgentRunContext
from eval.agent_runner.collect import collect_candidates
from eval.benchmark.contracts import BenchmarkCase, ScenarioExecution
from eval.dataset.loader import DomainDataset
from eval.evaluator.hybrid import HybridRunRequest, run_hybrid_evaluation
from eval.evaluator.schemas import EvaluationConfig


class AgentRunnerBenchmarkExecutor:
    """Execute product pipeline suites with the existing SQLite sandbox adapter."""

    def __init__(self, context: AgentRunContext, dataset: DomainDataset) -> None:
        self._context = context
        self._dataset = dataset

    async def execute(self, case: BenchmarkCase) -> ScenarioExecution:
        """Run one selected pipeline suite without using oracle query inputs."""
        suites = _suites(case.suite)
        candidates = await collect_candidates(self._context, self._dataset, query_mode="resolver", suites=suites)
        result = await run_hybrid_evaluation(_request(self._dataset, candidates))
        score = (result.overall_score or 0.0) / 100
        terminal = "completed" if result.status not in {"FAIL", "INCOMPLETE"} else "failed"
        return ScenarioExecution(terminal=terminal, outcome_score=score)


def _suites(suite: str) -> frozenset[str] | None:
    """Map a benchmark suite name to existing collector suite keys."""
    return None if suite == "pipeline" else frozenset({suite})


def _request(dataset: DomainDataset, candidates) -> HybridRunRequest:
    """Build a leakage-safe hybrid outcome request for collected candidates."""
    return HybridRunRequest(
        dataset=dataset,
        config=EvaluationConfig(),
        discovery=candidates.discovery,
        enrichment=candidates.enrichment,
        metrics=candidates.metrics,
        compiler=candidates.compiler,
        guardrail=candidates.guardrail,
        run_type="benchmark",
        candidate_source="agent_live",
        profile="pipeline",
    )
