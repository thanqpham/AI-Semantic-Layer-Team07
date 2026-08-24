"""CLI: --source agent wiring with collection monkeypatched (no LLM)."""

import pytest

from eval import run_eval
from eval.agent_runner import AgentCandidates
from eval.evaluator.hybrid.runner import HybridRunRequest
from eval.evaluator.schemas import CandidateGuardrailOutput


def test_source_agent_requires_hybrid_engine(capsys):
    with pytest.raises(SystemExit) as excinfo:
        run_eval.parse_args(["--engine", "legacy", "--source", "agent"])
    assert excinfo.value.code == 2  # argparse parser.error exits 2


def test_parse_accepts_agent_source():
    args = run_eval.parse_args(["--engine", "hybrid", "--source", "agent", "--query-mode", "oracle"])
    assert args.source == "agent"
    assert args.query_mode == "oracle"
    assert args.engine == "hybrid"


async def test_run_agent_engine_wires_hybrid_request(tmp_path, monkeypatch):
    """Engine wiring: collect -> candidates.json -> hybrid request -> reports."""
    collected: dict = {}
    saved: dict = {}
    requests: dict = {}
    guardrail = {"guardrail_001": CandidateGuardrailOutput(accepted=False, error_code="NON_SELECT_STATEMENT")}

    async def fake_prepare_run(golden_root, domain, run_dir):
        collected["prepare"] = (golden_root, domain, run_dir)
        return object()  # opaque ctx

    async def fake_collect(ctx, dataset, *, query_mode, enrichment_override=None, suites=None):
        collected["query_mode"] = query_mode
        return AgentCandidates(manifest={"candidate_source": "agent_live"}, guardrail=guardrail)

    def fake_write_candidates(run_dir, candidates):
        saved["candidates"] = candidates
        return run_dir / "candidates.json"

    async def fake_run_hybrid(request):
        requests["request"] = request

        class Result:
            status = "WARN"
            overall_score = 85.0
            coverage = 1.0

        return Result()

    monkeypatch.setattr(run_eval, "prepare_run", fake_prepare_run)
    monkeypatch.setattr(run_eval, "collect_candidates", fake_collect)
    monkeypatch.setattr(run_eval, "write_candidates", fake_write_candidates)
    monkeypatch.setattr(run_eval, "run_hybrid_evaluation", fake_run_hybrid)
    monkeypatch.setattr(run_eval, "write_json_report", lambda r, p: collected.setdefault("json", p))
    monkeypatch.setattr(run_eval, "write_csv_report", lambda r, p: collected.setdefault("csv", p))
    monkeypatch.setattr(run_eval, "write_markdown_report", lambda r, p: collected.setdefault("md", p))

    args = run_eval.parse_args(
        ["--engine", "hybrid", "--source", "agent", "--domain", "ecommerce", "--run-dir", str(tmp_path / "run")]
    )
    exit_code = await run_eval.run_agent_engine(args)
    assert exit_code == 0

    run_dir = tmp_path / "run"
    assert collected["prepare"] == (args.golden_root, "ecommerce", run_dir)
    assert collected["query_mode"] == "resolver"
    assert saved["candidates"].manifest["candidate_source"] == "agent_live"
    request = requests["request"]
    assert isinstance(request, HybridRunRequest)
    assert request.run_id == "agent-ecommerce"
    assert request.run_type == "smoke"
    assert request.candidate_source == "agent_live"
    assert request.profile == "pipeline"
    assert request.judge_runner is None
    assert request.guardrail is guardrail  # scored guardrail suite, not just the adapter lane
    assert collected["json"] == run_dir / "reports" / "report.json"
    assert collected["csv"] == run_dir / "reports" / "report.csv"
    assert collected["md"] == run_dir / "reports" / "report.md"


async def test_run_agent_engine_exits_one_on_fail(tmp_path, monkeypatch):
    """FAIL status maps to exit code 1 (PASS/WARN map to 0)."""

    async def fake_prepare_run(golden_root, domain, run_dir):
        return object()

    async def fake_collect(ctx, dataset, *, query_mode, enrichment_override=None, suites=None):
        return AgentCandidates()

    async def fake_run_hybrid(request):
        class Result:
            status = "FAIL"
            overall_score = 12.0
            coverage = 0.5

        return Result()

    monkeypatch.setattr(run_eval, "prepare_run", fake_prepare_run)
    monkeypatch.setattr(run_eval, "collect_candidates", fake_collect)
    monkeypatch.setattr(run_eval, "write_candidates", lambda rd, c: rd / "candidates.json")
    monkeypatch.setattr(run_eval, "run_hybrid_evaluation", fake_run_hybrid)
    monkeypatch.setattr(run_eval, "write_json_report", lambda r, p: None)
    monkeypatch.setattr(run_eval, "write_csv_report", lambda r, p: None)
    monkeypatch.setattr(run_eval, "write_markdown_report", lambda r, p: None)
    args = run_eval.parse_args(
        ["--engine", "hybrid", "--source", "agent", "--domain", "ecommerce", "--run-dir", str(tmp_path / "run")]
    )
    assert await run_eval.run_agent_engine(args) == 1
