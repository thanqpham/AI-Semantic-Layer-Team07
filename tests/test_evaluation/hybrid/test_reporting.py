"""Tests for JSON, CSV, and Markdown report emitters."""

import csv
import json

from eval.evaluator.hybrid.aggregation import build_suite_scores
from eval.evaluator.hybrid.contracts import MetricResult
from eval.evaluator.hybrid.reporting import (
    render_markdown,
    write_csv_report,
    write_json_report,
    write_markdown_report,
)
from eval.evaluator.hybrid.run_result import HybridRunResult, RunProvenance, evaluate_gates


def _mini_run() -> HybridRunResult:
    results = (
        MetricResult(
            sample_id="disc_001",
            metric="table_f1",
            metric_type="deterministic",
            status="passed",
            score=1.0,
            threshold=0.95,
        ),
    )
    return HybridRunResult(
        run_id="eval-test",
        run_type="smoke",
        status="PASS",
        score_valid=True,
        overall_score=100.0,
        coverage=1.0,
        suite_scores=build_suite_scores(results),
        metric_summary={"table_f1": 1.0},
        quality_gates=evaluate_gates(results, "smoke", "golden_derived", "pipeline", "pending"),
        results=results,
        provenance=RunProvenance(
            hybrid_contract_version="1.0.0",
            dataset_version="1.0.0",
            dataset_contract_version="2.0.0",
            dataset_review_status="pending",
            run_type="smoke",
            candidate_source="golden_derived",
            profile="pipeline",
        ),
    )


def test_json_report_round_trips(tmp_path) -> None:
    path = tmp_path / "report.json"
    write_json_report(_mini_run(), path)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["run_id"] == "eval-test"
    assert loaded["results"][0]["metric"] == "table_f1"


def test_csv_report_writes_one_row_per_single_task_sample(tmp_path) -> None:
    path = tmp_path / "report.csv"
    write_csv_report(_mini_run(), path)
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    assert rows[0]["sample_id"] == "disc_001"
    assert rows[0]["task"] == "discovery"
    assert rows[0]["table_f1"] == "1.0"


def _discovery_case_run() -> HybridRunResult:
    results = (
        MetricResult(
            sample_id="disc_001",
            metric="table_f1",
            metric_type="deterministic",
            status="passed",
            score=1.0,
            threshold=0.95,
        ),
        MetricResult(
            sample_id="disc_001",
            metric="entity_f1",
            metric_type="deterministic",
            status="passed",
            score=0.9,
            threshold=0.95,
        ),
    )
    return HybridRunResult(
        run_id="eval-test",
        run_type="smoke",
        status="PASS",
        score_valid=True,
        overall_score=100.0,
        coverage=1.0,
        suite_scores=build_suite_scores(results),
        metric_summary={"table_f1": 1.0, "entity_f1": 0.9},
        quality_gates=evaluate_gates(results, "smoke", "golden_derived", "pipeline", "pending"),
        results=results,
        provenance=RunProvenance(
            hybrid_contract_version="1.0.0",
            dataset_version="1.0.0",
            dataset_contract_version="2.0.0",
            dataset_review_status="pending",
            run_type="smoke",
            candidate_source="golden_derived",
            profile="pipeline",
        ),
    )


def test_csv_report_splits_discovery_case_into_two_task_rows(tmp_path) -> None:
    path = tmp_path / "report.csv"
    write_csv_report(_discovery_case_run(), path)
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    assert [(row["sample_id"], row["task"]) for row in rows] == [
        ("disc_001", "discovery"),
        ("disc_001", "enrichment"),
    ]
    discovery, enrichment = rows
    assert discovery["table_f1"] == "1.0" and discovery["entity_f1"] == ""
    assert enrichment["entity_f1"] == "0.9" and enrichment["table_f1"] == ""


def test_markdown_contains_summary_sections(tmp_path) -> None:
    markdown = render_markdown(_mini_run())
    assert "# Evaluation Report" in markdown
    assert "eval-test" in markdown
    assert "table_f1" in markdown
    assert "### discovery" in markdown  # metrics are grouped under their suite
    assert "quality gate" in markdown.lower()
    assert "- none" in markdown  # empty warnings still render the section
    write_markdown_report(_mini_run(), tmp_path / "report.md")
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == markdown


def test_markdown_notes_thin_judge_sample_counts() -> None:
    """Judge means computed from fewer than 3 samples carry an (n=...) note."""
    base = _mini_run()
    judge = MetricResult(
        sample_id="disc_001",
        metric="business_semantic_correctness",
        metric_type="ai_judge",
        status="passed",
        score=0.755,
        threshold=0.5,
    )
    results = (*base.results, judge)
    run = base.model_copy(
        update={
            "results": results,
            "suite_scores": build_suite_scores(results),
            "metric_summary": {**base.metric_summary, "business_semantic_correctness": 0.755},
        }
    )
    markdown = render_markdown(run)
    assert "| business_semantic_correctness | 0.755 (n=1) | AI judge |" in markdown
    assert "| table_f1 | 1.000 | code |" in markdown  # deterministic metrics say "code"


def test_markdown_groups_metrics_under_their_suite_heading() -> None:
    markdown = render_markdown(_discovery_case_run())
    assert markdown.index("### discovery") < markdown.index("| table_f1") < markdown.index("### enrichment")
    assert markdown.index("### enrichment") < markdown.index("| entity_f1") < markdown.index("## Quality gates")


def test_markdown_renders_warnings(tmp_path) -> None:
    run = _mini_run().model_copy(update={"warnings": ("judge metric m errored on 2 sample(s)",)})
    markdown = render_markdown(run)
    assert "## Warnings" in markdown
    assert "- judge metric m errored on 2 sample(s)" in markdown


def test_markdown_failed_rows_distinguish_zero_from_partial_credit() -> None:
    """Failed lines carry their score so 0.00 (sai thật) reads apart from 0.67 (một phần)."""
    base = _mini_run()
    zero = MetricResult(
        sample_id="q_001",
        metric="sql_ast_equivalence",
        metric_type="deterministic",
        status="failed",
        score=0.0,
        threshold=1.0,
    )
    partial = MetricResult(
        sample_id="m_001",
        metric="allowed_dimension_f1",
        metric_type="deterministic",
        status="failed",
        score=0.67,
        threshold=1.0,
    )
    crashed = MetricResult(
        sample_id="q_002",
        metric="sql_execution_accuracy",
        metric_type="deterministic",
        status="error",
        threshold=1.0,
        reason="judge runner unavailable",
    )
    results = (*base.results, zero, partial, crashed)
    run = base.model_copy(update={"results": results})
    markdown = render_markdown(run)
    assert "`q_001` / `sql_ast_equivalence`: failed (score 0.00)" in markdown
    assert "`m_001` / `allowed_dimension_f1`: failed (score 0.67)" in markdown
    assert "`q_002` / `sql_execution_accuracy`: error — judge runner unavailable" in markdown
