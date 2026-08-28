"""Unit tests for the trace-aware benchmark contracts and runner."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from eval.benchmark import BenchmarkCase, BenchmarkProfile, BenchmarkRunRequest, run_benchmark
from eval.benchmark.contracts import ScenarioExecution, TraceConstraints
from eval.benchmark.graph_runner import run_flow1_graph
from eval.benchmark.pricing import load_pricing_catalog
from eval.benchmark.product import AgentRunnerBenchmarkExecutor
from eval.benchmark.redaction import digest_observation, redact_state_delta, redact_value
from eval.benchmark.reporting import write_artifacts, write_replay_input
from src.observability import trace_action, trace_node
from src.observability.llm_usage import BenchmarkUsageCallback


class _Executor:
    async def execute(self, case: BenchmarkCase) -> ScenarioExecution:
        await _node({"conn_url_enc": "secret", "intent": "semantic_query"})
        await trace_action("query_compile", {"token": "hidden"}, _value())
        return ScenarioExecution(terminal=case.expected_terminal, outcome_score=1.0)


@trace_node("semantic_parse")
async def _node(state: dict[str, str]) -> dict[str, str]:
    return {"intent": state["intent"]}


async def _value() -> dict[str, str]:
    return {"sql": "SELECT 1"}


def _case() -> BenchmarkCase:
    return BenchmarkCase(
        case_id="trace_001",
        suite="query",
        fixture="sqlite",
        expected_terminal="resolved",
        constraints=TraceConstraints(
            required_nodes=("semantic_parse",),
            required_actions=("query_compile",),
            required_precedence=(("semantic_parse", "query_compile"),),
            required_state_keys=("intent",),
            required_evidence_actions=("query_compile",),
        ),
    )


@pytest.mark.asyncio
async def test_run_benchmark_records_redacted_trace_and_scores() -> None:
    request = BenchmarkRunRequest(
        "bench-1", BenchmarkProfile(model="m", provider="p", trials=1), (_case(),), _Executor()
    )
    result = await run_benchmark(request)
    assert result.status == "PASS"
    assert result.overall_score == 100.0
    assert any(event.action == "query_compile" for event in result.events)
    assert all("secret" not in event.model_dump_json() for event in result.events)


def test_redaction_preserves_safe_state_and_digests_observations() -> None:
    redacted = redact_value({"conn_url": "sqlite:///secret", "answer": "safe"})
    assert redacted["conn_url"] == "[REDACTED]"
    assert redact_state_delta({"intent": "ok", "conn_url_enc": "bad"}) == {"intent": "ok"}
    assert digest_observation({"token": "secret"}) == digest_observation({"token": "secret"})


@pytest.mark.asyncio
async def test_artifact_bundle_is_replayable_without_secret(tmp_path) -> None:
    request = BenchmarkRunRequest(
        "bench-2", BenchmarkProfile(model="m", provider="p", trials=1), (_case(),), _Executor()
    )
    result = await run_benchmark(request)
    write_artifacts(result, tmp_path, {"model": "m"})
    write_replay_input(tmp_path, {"fixture": "sqlite", "request": {"token": "[REDACTED]"}})
    assert (tmp_path / "traces.jsonl").read_text(encoding="utf-8").count("\n") == len(result.events)
    assert json.loads((tmp_path / "results.json").read_text(encoding="utf-8"))["status"] == "PASS"
    assert (tmp_path / "replay-input.json").exists()


@pytest.mark.asyncio
async def test_product_executor_uses_new_sqlite_sandbox_for_each_trial(tmp_path, monkeypatch) -> None:
    contexts: list[object] = []
    report_dirs: list[object] = []

    async def fake_prepare(*_args):
        context = SimpleNamespace(run_dir=tmp_path / f"trial-{len(contexts) + 1}")
        contexts.append(context)
        return context

    async def fake_collect(context, *_args, **_kwargs):
        assert contexts.count(context) == 1
        return SimpleNamespace(discovery={}, enrichment={}, metrics={}, compiler={}, guardrail={})

    async def fake_evaluate(_request):
        return SimpleNamespace(overall_score=100.0, status="PASS")

    monkeypatch.setattr("eval.benchmark.product.prepare_run", fake_prepare)
    monkeypatch.setattr("eval.benchmark.product.run_flow1_graph", lambda _context, request: _graph_state())
    monkeypatch.setattr("eval.benchmark.product.collect_candidates", fake_collect)
    monkeypatch.setattr("eval.benchmark.product.run_hybrid_evaluation", fake_evaluate)
    monkeypatch.setattr("eval.benchmark.product._write_hybrid_reports", lambda _result, path: report_dirs.append(path))
    executor = AgentRunnerBenchmarkExecutor(tmp_path, "ecommerce", tmp_path / "run", object())
    await executor.execute(_case())
    await executor.execute(_case())
    assert len(contexts) == 2
    assert report_dirs == [tmp_path / "trial-1" / "reports", tmp_path / "trial-2" / "reports"]


async def _graph_state() -> dict[str, object]:
    return {}


class _Graph:
    def __init__(self) -> None:
        self.state: dict[str, object] | None = None

    async def ainvoke(self, state: dict[str, object]) -> dict[str, object]:
        self.state = state
        return {"raw_schema": {"tables": []}}


@pytest.mark.asyncio
async def test_flow_graph_adapter_invokes_real_graph_interface_with_encrypted_url() -> None:
    graph = _Graph()
    context = SimpleNamespace(user_id=7, target_url="sqlite:///sandbox.sqlite")
    await run_flow1_graph(context, graph)
    assert graph.state is not None
    assert graph.state["db_type"] == "sqlite"
    assert graph.state["conn_url_enc"] != context.target_url
    assert graph.state["user_message"]


@pytest.mark.asyncio
async def test_flow_graph_adapter_uses_case_metric_request() -> None:
    graph = _Graph()
    context = SimpleNamespace(user_id=7, target_url="sqlite:///sandbox.sqlite")
    await run_flow1_graph(context, graph, {"user_message": "Đếm order_id của fact_orders"})
    assert graph.state is not None
    assert graph.state["user_message"] == "Đếm order_id của fact_orders"


@trace_node("introspect")
async def _node_with_action(_state: dict[str, object]) -> dict[str, object]:
    await trace_action("schema_introspection", {}, _value())
    return {"raw_schema": {"tables": [{"table_name": "orders"}]}}


class _NodeExecutor:
    async def execute(self, case: BenchmarkCase) -> ScenarioExecution:
        await _node_with_action({})
        return ScenarioExecution(terminal=case.expected_terminal, outcome_score=1.0)


@pytest.mark.asyncio
async def test_node_action_and_state_are_traceable() -> None:
    case = BenchmarkCase(
        case_id="node_trace_001",
        suite="flow1",
        fixture="sqlite",
        expected_terminal="completed",
        constraints=TraceConstraints(
            required_nodes=("introspect",),
            required_actions=("schema_introspection",),
            required_state_keys=("raw_schema",),
        ),
    )
    result = await run_benchmark(
        BenchmarkRunRequest("bench-node", BenchmarkProfile(model="m", provider="p", trials=1), (case,), _NodeExecutor())
    )
    action = next(event for event in result.events if event.action == "schema_introspection")
    assert action.node == "introspect"
    assert any(event.kind == "node_finished" and "raw_schema" in event.state_delta for event in result.events)
    assert next(gate for gate in result.gates if gate.name == "required_trace_evidence").passed


@pytest.mark.asyncio
async def test_transition_label_cannot_satisfy_required_node() -> None:
    case = _case().model_copy(update={"constraints": TraceConstraints(required_nodes=("introspect",))})
    request = BenchmarkRunRequest(
        "bench-transition", BenchmarkProfile(model="m", provider="p", trials=1), (case,), _LinearActionExecutor()
    )
    result = await run_benchmark(request)
    assert not next(gate for gate in result.gates if gate.name == "required_trace_evidence").passed


class _LinearActionExecutor:
    async def execute(self, case: BenchmarkCase) -> ScenarioExecution:
        for _ in range(3):
            await trace_action("sql_guardrail", {}, _value())
        return ScenarioExecution(terminal=case.expected_terminal, outcome_score=1.0)


@pytest.mark.asyncio
async def test_linear_actions_do_not_count_as_agent_iterations() -> None:
    case = _case().model_copy(update={"constraints": TraceConstraints(max_iterations=1, max_actions=10)})
    request = BenchmarkRunRequest(
        "bench-linear", BenchmarkProfile(model="m", provider="p", trials=1), (case,), _LinearActionExecutor()
    )
    result = await run_benchmark(request)
    gate = next(item for item in result.gates if item.name == "iteration_budget")
    assert gate.passed


def _llm_response(usage: dict[str, object] | None) -> SimpleNamespace:
    message = SimpleNamespace(usage_metadata=usage, response_metadata={"model_name": "gpt-4o-mini"})
    return SimpleNamespace(generations=[[SimpleNamespace(message=message)]], llm_output={})


def test_usage_callback_records_provider_tokens_and_priced_cost() -> None:
    from eval.benchmark.tracer import BenchmarkTraceRecorder
    from src.observability import activate_trace

    recorder = BenchmarkTraceRecorder("usage-run")
    callback = BenchmarkUsageCallback("openai", "gpt-4o-mini")
    with activate_trace(recorder), recorder.trial_context("usage-case", 1):
        callback.on_llm_end(
            _llm_response(
                {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "input_token_details": {"cache_read": 200},
                }
            )
        )
    event = recorder.events[0]
    assert event.input_tokens == 1000
    assert event.cached_input_tokens == 200
    assert event.output_tokens == 500
    assert event.estimated_cost_usd == pytest.approx(0.000435)
    assert event.cost_status == "estimated"


def test_usage_callback_marks_missing_provider_metadata_unavailable() -> None:
    from eval.benchmark.tracer import BenchmarkTraceRecorder
    from src.observability import activate_trace

    recorder = BenchmarkTraceRecorder("usage-run")
    callback = BenchmarkUsageCallback("gemini", "gemini-test")
    with activate_trace(recorder), recorder.trial_context("usage-case", 1):
        callback.on_llm_end(_llm_response(None))
    event = recorder.events[0]
    assert event.input_tokens is None
    assert event.estimated_cost_usd is None
    assert event.cost_status == "unavailable"


def test_pricing_catalog_does_not_guess_unknown_provider_cost() -> None:
    estimate = load_pricing_catalog().estimate("mimo", "mimo-v2", 10, 10, None, None)
    assert estimate.cost_usd is None
    assert estimate.status == "unavailable"
