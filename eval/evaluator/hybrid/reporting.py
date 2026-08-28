"""JSON, CSV, and Markdown report emitters (spec §11)."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from eval.evaluator.hybrid.contracts import MetricResult
from eval.evaluator.hybrid.run_result import HybridRunResult

#: Below this many scored samples a judge metric's mean gets an ``(n=...)`` note.
_JUDGE_MIN_SAMPLES = 3


def write_json_report(result: HybridRunResult, path: Path) -> None:
    """Write the complete run contract as pretty JSON."""
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def write_csv_report(result: HybridRunResult, path: Path) -> None:
    """Write one row per (sample, task) pair with one score column per metric."""
    metric_names = sorted({r.metric for r in result.results})
    metric_task = {metric: _task(result, metric) for metric in metric_names}
    by_key = {(r.sample_id, r.metric): r for r in result.results}
    rows = sorted({(r.sample_id, metric_task[r.metric]) for r in result.results})
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["sample_id", "task", *metric_names])
    for sample_id, task in rows:
        cells = [_cell(by_key.get((sample_id, m))) if metric_task[m] == task else "" for m in metric_names]
        writer.writerow([sample_id, task, *cells])
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _task(result: HybridRunResult, metric: str) -> str:
    """Find the suite that owns one metric name."""
    return next((suite.task for suite in result.suite_scores if metric in suite.metric_scores), "unknown")


def _cell(result: MetricResult | None) -> str:
    """Render one CSV cell as a score or a status."""
    if result is None:
        return ""
    return str(result.score) if result.score is not None else result.status


def render_markdown(result: HybridRunResult) -> str:
    """Render the team-facing Markdown summary."""
    lines = [
        "# Evaluation Report",
        "",
        f"- Run: `{result.run_id}` ({result.run_type}) — status **{result.status}**",
        f"- Overall score: {_fmt(result.overall_score)} / 100"
        f" (valid={result.score_valid}, coverage={result.coverage:.0%})",
        "",
        "## Suite scores",
        "",
        "| Suite | Weight | Score | Minimum | Samples | Errors |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    lines.extend(_suite_rows(result))
    lines.extend(["", "## Metric scores"])
    for section in _metric_sections(result):
        lines.extend(["", *section])
    lines.extend(["", "## Quality gates", "", "| Gate | Passed | Detail |", "|---|---|---|"])
    lines.extend(f"| {gate.name} | {'✅' if gate.passed else '❌'} | {gate.detail} |" for gate in result.quality_gates)
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in result.warnings)
    if not result.warnings:
        lines.append("- none")
    lines.extend(["", "## Failed results", ""])
    failures = [r for r in result.results if r.status in {"failed", "error"}]
    lines.extend(f"- `{r.sample_id}` / `{r.metric}`: {r.status} — {r.reason}" for r in failures)
    if not failures:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _suite_rows(result: HybridRunResult) -> list[str]:
    """Render one markdown table row per suite."""
    return [
        f"| {suite.task} | {suite.weight:.0%} | {_fmt(suite.score)} | {suite.minimum:.2f} | "
        f"{suite.sample_count} | {suite.error_count} |"
        for suite in result.suite_scores
    ]


def _metric_sections(result: HybridRunResult) -> list[list[str]]:
    """Render one metric-score table per suite so related metrics stay together."""
    judge_counts = _judge_metric_counts(result)
    sections: list[list[str]] = []
    grouped: set[str] = set()
    for suite in result.suite_scores:
        grouped.update(suite.metric_scores)
        if suite.metric_scores:
            sections.append(_metric_section(result, suite.task, sorted(suite.metric_scores), judge_counts))
    ungrouped = sorted(set(result.metric_summary) - grouped)
    if ungrouped:
        sections.append(_metric_section(result, "other", ungrouped, judge_counts))
    return sections


def _judge_metric_counts(result: HybridRunResult) -> dict[str, int]:
    """Map each AI-judge metric to its scored-sample count (0 when none scored)."""
    counts = {entry.metric: 0 for entry in result.results if entry.metric_type == "ai_judge"}
    for entry in result.results:
        if entry.metric_type == "ai_judge" and entry.score is not None:
            counts[entry.metric] += 1
    return counts


def _metric_section(
    result: HybridRunResult,
    task: str,
    names: list[str],
    judge_counts: dict[str, int],
) -> list[str]:
    """Render one suite's metric-score table under its own heading."""
    rows = _metric_rows(result, names, judge_counts)
    return [f"### {task}", "", "| Metric | Mean score | Source |", "|---|---:|---|", *rows]


def _metric_rows(result: HybridRunResult, names: list[str], judge_counts: dict[str, int]) -> list[str]:
    """Render one markdown table row per metric name."""
    return [
        f"| {name} | {_scored(result.metric_summary.get(name), judge_counts.get(name))} "
        f"| {_source(name, judge_counts)} |"
        for name in names
    ]


def _source(name: str, judge_counts: dict[str, int]) -> str:
    """Name the measurement lane: the AI judge or deterministic code."""
    return "AI judge" if name in judge_counts else "code"


def _scored(value: float | None, judge_count: int | None) -> str:
    """Format a mean, noting thin judge samples so single-verdict means aren't over-read."""
    text = _fmt(value)
    if judge_count is not None and judge_count < _JUDGE_MIN_SAMPLES:
        text += f" (n={judge_count})"
    return text


def _fmt(value: float | None) -> str:
    """Format an optional score for markdown."""
    return f"{value:.3f}" if value is not None else "n/a"


def write_markdown_report(result: HybridRunResult, path: Path) -> None:
    """Write the Markdown summary to disk."""
    path.write_text(render_markdown(result), encoding="utf-8")
