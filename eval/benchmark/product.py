"""Adapter that runs the existing isolated agent collector as a benchmark scenario."""

from __future__ import annotations

from pathlib import Path

from eval.agent_runner.bootstrap import prepare_run
from eval.agent_runner.collect import collect_candidates
from eval.benchmark.contracts import BenchmarkCase, ScenarioExecution
from eval.benchmark.graph_runner import run_flow1_graph
from eval.dataset.loader import DomainDataset
from eval.evaluator.hybrid import HybridRunRequest, HybridRunResult, run_hybrid_evaluation
from eval.evaluator.hybrid.reporting import write_csv_report, write_json_report, write_markdown_report
from eval.evaluator.schemas import EvaluationConfig


class AgentRunnerBenchmarkExecutor:
    """Execute product pipeline suites with the existing SQLite sandbox adapter."""

    def __init__(self, golden_root: Path, domain: str, run_dir: Path, dataset: DomainDataset) -> None:
        self._golden_root = golden_root
        self._domain = domain
        self._run_dir = run_dir
        self._dataset = dataset
        self._attempts: dict[str, int] = {}

    async def execute(self, case: BenchmarkCase) -> ScenarioExecution:
        """Run one selected pipeline suite without using oracle query inputs."""
        context = await prepare_run(self._golden_root, self._domain, self._next_trial_dir(case.case_id))
        graph_state = await run_flow1_graph(context, request=case.request) if case.suite == "pipeline" else {}
        candidates = await collect_candidates(context, self._dataset, query_mode="resolver", suites=_suites(case.suite))
        result = await run_hybrid_evaluation(_request(self._dataset, candidates))
        _write_hybrid_reports(result, context.run_dir / "reports")
        score = (result.overall_score or 0.0) / 100
        error_code = _terminal_error_code(result.status, graph_state)
        return ScenarioExecution(
            terminal="failed" if error_code else "completed", outcome_score=score, error_code=error_code
        )

    def _next_trial_dir(self, case_id: str) -> Path:
        """Allocate a fresh metadata and target SQLite sandbox for each execution."""
        attempt = self._attempts.get(case_id, 0) + 1
        self._attempts[case_id] = attempt
        return self._run_dir / "trials" / case_id / f"trial-{attempt}"


def _terminal_error_code(status: str, graph_state: dict[str, object]) -> str | None:
    """Expose whether graph execution or output evaluation caused a failed terminal."""
    if graph_state.get("error") or status in {"FAIL", "INCOMPLETE"}:
        return "FLOW1_GRAPH_FAILED" if graph_state.get("error") else "HYBRID_EVALUATION_FAILED"
    return None


def _write_hybrid_reports(result: HybridRunResult, report_dir: Path) -> None:
    """Persist evaluator evidence next to the isolated benchmark trial."""
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(result, report_dir / "report.json")
    write_csv_report(result, report_dir / "report.csv")
    write_markdown_report(result, report_dir / "report.md")


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
