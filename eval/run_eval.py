"""Minimal end-to-end runner that wires the evaluation public API.

Skeleton/demo: loads a Golden Dataset domain and runs ``evaluate_domain_suite``
with placeholder (empty) candidate outputs so the framework executes end-to-end.
Replace ``_placeholder_candidates`` with real candidate outputs produced by the
agent (Stage 2-4) to score an actual run — or use ``--source agent`` to collect
those candidates live from the real ``src/`` pipeline.

Run from the repository root:

    python -m eval.run_eval --domain ecommerce
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from eval.agent_runner import (
    AgentRunContext,
    ProductionGuardrailAdapter,
    collect_candidates,
    prepare_run,
    write_candidates,
    write_resolver_diagnostics,
)
from eval.dataset.loader import load_domain_dataset
from eval.evaluator import (
    DomainCandidateOutputs,
    DomainEvaluationResult,
    EvaluationDependencies,
    evaluate_domain_suite,
)
from eval.evaluator.discovery_eval import CandidateDiscoveryOutput
from eval.evaluator.hybrid import HybridRunRequest, run_hybrid_evaluation
from eval.evaluator.hybrid.reporting import (
    write_csv_report,
    write_json_report,
    write_markdown_report,
)
from eval.evaluator.schemas import (
    CandidateCompilerOutput,
    CandidateEnrichmentOutput,
    CandidateGuardrailOutput,
    CandidateMetricOutput,
    EvaluationConfig,
)

if TYPE_CHECKING:
    from eval.agent_runner import AgentCandidates
    from eval.dataset.loader import DomainDataset
    from eval.evaluator.hybrid.judge.base import JudgeRunner
    from eval.evaluator.hybrid.run_result import HybridRunResult

GOLDEN_ROOT = Path("eval/golden_dataset")
SUITES = ("enrichment", "metrics", "compiler", "guardrails")


async def run_evaluation(golden_root: Path, domain: str) -> DomainEvaluationResult:
    """Load one domain dataset and evaluate its candidate outputs."""
    dataset = await load_domain_dataset(golden_root, domain)
    deps = EvaluationDependencies(config=EvaluationConfig())
    return await evaluate_domain_suite(dataset, _placeholder_candidates(), deps)


def _placeholder_candidates() -> DomainCandidateOutputs:
    """Return empty candidate outputs (replace with real agent output)."""
    return DomainCandidateOutputs(enrichment={}, metrics={}, compiler={})


def _print_summary(result: DomainEvaluationResult) -> None:
    """Print micro precision/recall/F1 for each evaluated suite."""
    for name in SUITES:
        micro = getattr(result, name).micro
        if micro is None:
            print(f"{name:<12}: (chưa có case nào được chấm)")
            continue
        print(f"{name:<12}: F1={micro.f1:.3f}  P={micro.precision:.3f}  R={micro.recall:.3f}")


#: Internal task names accepted as --suite aliases, mapped to their CLI spellings.
_SUITE_ALIASES: dict[str, str] = {
    "metric_generation": "metrics",
    "query_compilation": "compiler",
    "guardrail": "guardrails",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments; the hybrid engine is the default."""
    parser = argparse.ArgumentParser(description="Run the evaluation framework on one domain.")
    parser.add_argument("--golden-root", type=Path, default=GOLDEN_ROOT, help="Golden Dataset root directory.")
    parser.add_argument("--domain", default="ecommerce", help="Domain identifier to evaluate.")
    parser.add_argument(
        "--engine",
        choices=("legacy", "hybrid"),
        default="hybrid",
        help="scoring engine (legacy is deprecated: AND-gated case status and CQM path matching)",
    )
    parser.add_argument("--source", choices=("smoke", "agent"), default="smoke")
    parser.add_argument("--query-mode", choices=("resolver", "oracle"), default="resolver")
    parser.add_argument(
        "--suite",
        choices=(
            "all",
            "discovery",
            "enrichment",
            "metrics",
            "metric_generation",
            "compiler",
            "query_compilation",
            "guardrails",
            "guardrail",
        ),
        default="all",
        help="evaluate only a single suite (default: all); internal task names "
        "(metric_generation, query_compilation, guardrail) are accepted as aliases",
    )
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--run-type", choices=("smoke", "benchmark", "release"), default="smoke")
    parser.add_argument(
        "--judge",
        action="store_true",
        help="enable the isolated AI Judge lane (requires JUDGE_* configuration)",
    )
    parser.add_argument("--report-dir", type=Path, default=Path("eval/reports/hybrid"))
    parser.add_argument(
        "--rescore",
        type=Path,
        default=None,
        metavar="RUN_DIR",
        help=(
            "Re-score an existing run dir's candidates.json with the current engine "
            "(no agent collection; agent LLM is not called). Add --judge to re-run the "
            "AI-judge lane over the fixed candidates (A/B judge model/prompt changes). "
            "Uses the CURRENT CLI flags (e.g. --run-type), not the original run's — pass "
            "--run-type explicitly to match how the run was collected."
        ),
    )
    args = parser.parse_args(argv)
    args.suite = _SUITE_ALIASES.get(args.suite, args.suite)
    if args.source == "agent" and args.engine != "hybrid":
        parser.error("--source agent requires --engine hybrid")
    if args.engine == "legacy":
        print(
            "warning: --engine legacy is deprecated (case-level AND-gating and CQM path "
            "matching are superseded by the hybrid engine) and will be removed.",
            file=sys.stderr,
        )
    return args


def _build_judge_runner() -> JudgeRunner:
    """Wire the isolated get_llm(role='judge') lane."""
    from eval.evaluator.hybrid.judge.base import JudgeRunner, LangChainJudgeLLM
    from eval.evaluator.hybrid.judge.cache import MemoryJudgeCache

    return JudgeRunner(llm=LangChainJudgeLLM(), cache=MemoryJudgeCache())


async def run_hybrid_engine(args: argparse.Namespace) -> int:
    """Execute a golden-derived hybrid run and write the three reports."""
    from eval.evaluator.hybrid import smoke_candidates
    from eval.evaluator.hybrid.smoke import SmokeGuardrailAdapter

    dataset = await load_domain_dataset(args.golden_root, args.domain)
    config = EvaluationConfig()
    candidates = await smoke_candidates(dataset, config)
    result = await run_hybrid_evaluation(
        HybridRunRequest(
            dataset=dataset,
            config=config,
            guardrail_adapter=SmokeGuardrailAdapter(config),
            judge_runner=_build_judge_runner() if args.judge else None,
            run_id=f"hybrid-{args.domain}",
            run_type=args.run_type,
            **asdict(candidates),
        )
    )
    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(result, args.report_dir / "report.json")
    write_csv_report(result, args.report_dir / "report.csv")
    write_markdown_report(result, args.report_dir / "report.md")
    print(
        f"hybrid run {result.run_id}: status={result.status} "
        f"score={result.overall_score} coverage={result.coverage:.0%}"
    )
    return 0 if result.status in {"PASS", "WARN"} else 1


def _utc_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp for run dir names."""
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _contract_gap_fields() -> dict[str, frozenset[str]]:
    """Convert the collector's disclosed gaps into engine policy declarations."""
    from eval.agent_runner.collect import CONTRACT_GAPS

    return {"metric": frozenset(CONTRACT_GAPS.get("metric", []))}


def _agent_request(
    dataset: DomainDataset,
    candidates: AgentCandidates,
    args: argparse.Namespace,
    run_id: str,
) -> HybridRunRequest:
    """Assemble the hybrid run request over collected agent candidates."""
    config = EvaluationConfig()
    return HybridRunRequest(
        dataset=dataset,
        config=config,
        discovery=candidates.discovery,
        enrichment=candidates.enrichment,
        metrics=candidates.metrics,
        compiler=candidates.compiler,
        guardrail=candidates.guardrail,
        guardrail_adapter=ProductionGuardrailAdapter(config),
        judge_runner=_build_judge_runner() if args.judge else None,
        run_id=run_id,
        run_type=args.run_type,
        candidate_source="agent_live",
        profile="pipeline",
        contract_gap_fields=_contract_gap_fields(),
    )


def _write_agent_reports(result: HybridRunResult, run_dir: Path) -> None:
    """Write the JSON, CSV, and Markdown reports inside the run dir."""
    report_dir = run_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(result, report_dir / "report.json")
    write_csv_report(result, report_dir / "report.csv")
    write_markdown_report(result, report_dir / "report.md")


async def run_agent_engine(args: argparse.Namespace) -> int:
    """Collect real-agent candidates and run the hybrid engine over them."""
    run_dir = args.run_dir or Path(f"eval/runs/agent-{args.domain}-{_utc_timestamp()}")
    ctx = await prepare_run(args.golden_root, args.domain, run_dir)
    try:
        return await _collect_and_report(args, run_dir, ctx)
    finally:
        await ctx.aclose()


async def _collect_and_report(args: argparse.Namespace, run_dir: Path, ctx: AgentRunContext) -> int:
    """Collect candidates from the prepared context and emit hybrid reports."""
    dataset = await load_domain_dataset(args.golden_root, args.domain)
    suites = frozenset({args.suite}) if args.suite != "all" else None
    candidates = await collect_candidates(ctx, dataset, query_mode=args.query_mode, suites=suites)
    write_candidates(run_dir, candidates)
    diagnostics_path = write_resolver_diagnostics(run_dir, candidates)
    if diagnostics_path is not None:
        print(f"resolver diagnostics: {diagnostics_path}")
    run_id = f"agent-{args.domain}"
    result = await run_hybrid_evaluation(_agent_request(dataset, candidates, args, run_id))
    _write_agent_reports(result, run_dir)
    print(f"agent run {run_id}: status={result.status} score={result.overall_score} coverage={result.coverage:.0%}")
    return 0 if result.status in {"PASS", "WARN"} else 1


def _load_rescore_payload(run_dir: Path) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    """Read candidates.json and rebuild the five candidate sections plus manifest."""
    payload = json.loads((run_dir / "candidates.json").read_text(encoding="utf-8"))
    sections = {
        "discovery": {k: CandidateDiscoveryOutput.model_validate(v) for k, v in payload.get("discovery", {}).items()},
        "enrichment": {
            k: CandidateEnrichmentOutput.model_validate(v) for k, v in payload.get("enrichment", {}).items()
        },
        "metrics": {k: CandidateMetricOutput.model_validate(v) for k, v in payload.get("metrics", {}).items()},
        "compiler": {k: CandidateCompilerOutput.model_validate(v) for k, v in payload.get("compiler", {}).items()},
        "guardrail": {k: CandidateGuardrailOutput.model_validate(v) for k, v in payload.get("guardrail", {}).items()},
    }
    manifest = payload.get("manifest") or {}
    return sections, manifest


async def run_rescore_engine(args: argparse.Namespace) -> int:
    """Re-score an existing run's collected candidates (no collection, optional judge)."""
    dataset = await load_domain_dataset(args.golden_root, args.domain)
    config = EvaluationConfig()
    sections, manifest = _load_rescore_payload(args.rescore)
    result = await run_hybrid_evaluation(
        HybridRunRequest(
            dataset=dataset,
            config=config,
            guardrail_adapter=ProductionGuardrailAdapter(config),
            judge_runner=_build_judge_runner() if args.judge else None,
            run_id=f"rescore-{args.rescore.name}",
            run_type=args.run_type,
            candidate_source=str(manifest.get("candidate_source", "agent_live")),
            profile="pipeline",
            contract_gap_fields=_contract_gap_fields(),
            **sections,
        )
    )
    report_dir = args.rescore / "reports-rescore"
    report_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(result, report_dir / "report.json")
    write_csv_report(result, report_dir / "report.csv")
    write_markdown_report(result, report_dir / "report.md")
    print(f"rescore run: status={result.status} score={result.overall_score} coverage={result.coverage:.0%}")
    return 0 if result.status in {"PASS", "WARN"} else 1


def main() -> int:
    """CLI entry point: parse args, run evaluation, and print the summary."""
    args = parse_args()
    if args.rescore is not None:
        return asyncio.run(run_rescore_engine(args))
    if args.source == "agent":
        return asyncio.run(run_agent_engine(args))
    if args.engine == "hybrid":
        return asyncio.run(run_hybrid_engine(args))
    result = asyncio.run(run_evaluation(args.golden_root, args.domain))
    _print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
