"""Run the trace benchmark against the existing SQLite agent-runner sandbox."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from eval.benchmark import BenchmarkProfile, BenchmarkRunRequest, run_benchmark
from eval.benchmark.dataset import load_benchmark_cases
from eval.benchmark.product import AgentRunnerBenchmarkExecutor
from eval.benchmark.reporting import write_artifacts, write_replay_input
from eval.dataset.loader import load_domain_dataset
from src.services.llm import _resolve_llm_config, get_settings


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse manual and pre-release trace benchmark options."""
    parser = argparse.ArgumentParser(description="Run trace-aware agent benchmarks.")
    parser.add_argument("--domain", default="ecommerce")
    parser.add_argument("--golden-root", type=Path, default=Path("eval/golden_dataset"))
    parser.add_argument("--profile", choices=("benchmark", "release"), default="benchmark")
    parser.add_argument("--run-dir", type=Path, default=None)
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    """Create an isolated SQLite sandbox, execute cases, and write artifacts."""
    run_dir = args.run_dir or _run_dir(args.domain)
    dataset = await load_domain_dataset(args.golden_root, args.domain)
    cases = await load_benchmark_cases(args.golden_root, args.domain)
    config = _resolve_llm_config(get_settings())
    profile = (
        BenchmarkProfile.release(config.model, config.provider)
        if args.profile == "release"
        else BenchmarkProfile(model=config.model, provider=config.provider)
    )
    request = BenchmarkRunRequest(
        run_id=run_dir.name,
        profile=profile,
        cases=cases,
        executor=AgentRunnerBenchmarkExecutor(args.golden_root, args.domain, run_dir, dataset),
    )
    result = await run_benchmark(request)
    write_artifacts(result, run_dir, {"domain": args.domain, "profile": profile.model_dump(mode="json")})
    write_replay_input(run_dir, {"domain": args.domain, "cases": [case.model_dump(mode="json") for case in cases]})
    print(
        f"benchmark {result.run_id}: status={result.status} score={result.overall_score} coverage={result.coverage:.0%}"
    )
    return 0


def _run_dir(domain: str) -> Path:
    """Build a fresh artifact directory name without making a release-blocking decision."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return Path(f"eval/runs/benchmark-{domain}-{stamp}")


def main() -> int:
    """Execute the asynchronous benchmark command."""
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
