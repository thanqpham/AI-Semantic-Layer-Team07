"""Write replayable benchmark artifacts without persisting secrets."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from eval.benchmark.contracts import BenchmarkRunResult


def write_artifacts(result: BenchmarkRunResult, run_dir: Path, manifest: dict[str, Any]) -> None:
    """Write the standard local artifact bundle for one benchmark run."""
    run_dir.mkdir(parents=True, exist_ok=True)
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "results.json", result.model_dump(mode="json"))
    _write_traces(result, run_dir / "traces.jsonl")
    _write_csv(result, run_dir / "results.csv")
    (run_dir / "report.md").write_text(render_markdown(result), encoding="utf-8")


def write_replay_input(run_dir: Path, payload: dict[str, Any]) -> None:
    """Persist fixture references and requests suitable for a safe replay."""
    _write_json(run_dir / "replay-input.json", payload)


def render_markdown(result: BenchmarkRunResult) -> str:
    """Render a compact human-facing benchmark summary."""
    lines = [
        "# Agent Trace Benchmark",
        "",
        f"- Run: `{result.run_id}` — status **{result.status}**",
        f"- Overall score: {result.overall_score if result.overall_score is not None else 'n/a'} / 100",
        f"- Coverage: {result.coverage:.0%}",
        "",
        "## Scores",
        "",
        "| Dimension | Weight | Score |",
        "|---|---:|---:|",
    ]
    lines.extend(f"| {item.name} | {item.weight:.0%} | {item.score:.3f} |" for item in result.scores)
    lines.extend(["", "## Critical gates", "", "| Gate | Passed | Detail |", "|---|---|---|"])
    lines.extend(f"| {gate.name} | {'yes' if gate.passed else 'CRITICAL'} | {gate.detail} |" for gate in result.gates)
    if result.baseline is not None:
        lines.extend(["", "## Baseline", "", f"- {result.baseline.detail}"])
    if result.warnings:
        lines.extend(["", "## Advisory warnings", ""])
        lines.extend(f"- {warning}" for warning in result.warnings)
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_traces(result: BenchmarkRunResult, path: Path) -> None:
    lines = [event.model_dump_json() for event in result.events]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_csv(result: BenchmarkRunResult, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["case_id", "trial", "iteration", "kind", "node", "action", "status", "latency_ms"])
        for event in result.events:
            writer.writerow(
                [
                    event.case_id,
                    event.trial,
                    event.iteration,
                    event.kind,
                    event.node,
                    event.action,
                    event.status,
                    event.latency_ms,
                ]
            )
