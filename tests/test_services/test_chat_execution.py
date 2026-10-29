"""Public traces must remain accurate, isolated, and free of raw agent data."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.observability import trace_node
from src.services.chat_execution import ChatExecution, execution_context, execution_step, stream_execution
from src.services.chat_tasks import start_chat_task


def test_trace_uses_monotonic_time_and_allowlist(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr("src.services.chat_execution.time.perf_counter", lambda: clock[0])
    execution = ChatExecution()
    secret = "private-key-and-connection-url"
    execution.record("node_started", {"node": "orchestrator", "state_before": {"secret": secret}})
    clock[0] += 2.25
    execution.record("node_finished", {"node": "orchestrator", "state_delta": {"prompt": secret}})
    execution.record("llm_usage", {"node": "orchestrator", "secret": secret})
    execution.record("action_started", {"node": secret, "action": secret})
    trace = execution.finish("completed", "out_of_scope")
    assert trace["elapsed_ms"] == 2250
    assert trace["events"][2]["duration_ms"] == 2250
    assert secret not in json.dumps(trace)
    assert [event["seq"] for event in trace["events"]] == list(range(1, len(trace["events"]) + 1))
    assert any(event.get("target") == "out_of_scope" for event in trace["events"])


def test_node_outcomes_are_allowlisted_bounded_and_attached_to_invocation():
    execution = ChatExecution()
    secret = "customer-secret-and-private-prompt"
    execution.record("node_started", {"node": "metric_suggest", "state_before": {}})
    execution.record(
        "node_finished",
        {"node": "metric_suggest", "state_delta": {"suggested_metrics": [{"id": "1"}, {"id": "2"}], "prompt": secret}},
    )
    events = [event for event in execution.snapshot()["events"] if event["kind"] == "step"]
    assert len(events) == 2
    assert events[0]["step_id"] == events[1]["step_id"]
    assert events[-1]["outcome_summary"] == "Đề xuất 2 metric"
    assert secret not in json.dumps(events)


@pytest.mark.parametrize(
    ("node", "output", "expected"),
    [
        ("orchestrator", {"intent": "semantic_query"}, "Truy v\u1ea5n d\u1eef li\u1ec7u theo metric"),
        (
            "semantic_parse",
            {"interpretation": {"status": "resolved", "rationale": "Selected revenue by customer"}},
            "Selected revenue by customer",
        ),
        ("metric_review", {"items": [{"report": SimpleNamespace(summary="Missing time range")}]}, "Missing time range"),
    ],
)
def test_node_outcome_exposes_actual_decision_or_explanation(node, output, expected):
    execution = ChatExecution()
    execution.record("node_started", {"node": node, "state_before": {}})
    execution.record("node_finished", {"node": node, "state_delta": {**output, "prompt": "private-prompt"}})
    event = execution.snapshot()["events"][-1]
    assert expected in event["outcome_summary"]
    assert "private-prompt" not in json.dumps(event)


def test_explanation_is_bounded_and_invalid_intent_does_not_break_trace():
    execution = ChatExecution()
    execution.record("node_started", {"node": "orchestrator", "state_before": {}})
    execution.record("node_finished", {"node": "orchestrator", "state_delta": {"intent": []}})
    execution.record("node_started", {"node": "semantic_parse", "state_before": {}})
    execution.record(
        "node_finished",
        {"node": "semantic_parse", "state_delta": {"interpretation": {"rationale": "x" * 800}}},
    )
    assert len(execution.snapshot()["events"][-1]["outcome_summary"]) == 500


def test_failed_node_keeps_action_without_exposing_error_details():
    execution = ChatExecution()
    execution.record("node_started", {"node": "data_assistant", "state_before": {}})
    execution.record("node_failed", {"node": "data_assistant", "error_code": "ValueError", "state_delta": {}})
    events = [event for event in execution.snapshot()["events"] if event["kind"] == "step"]
    assert events[-1]["summary"] == "Tra cứu semantic layer và metric đã duyệt"
    assert events[-1]["status"] == "failed"
    assert "outcome_summary" not in events[-1]


def test_preclassified_orchestrator_is_not_another_inference():
    execution = ChatExecution()
    state = {"intent": "semantic_query"}
    execution.record("node_started", {"node": "orchestrator", "state_before": state})
    execution.record("node_finished", {"node": "orchestrator", "state_before": state, "state_delta": state})
    steps = [event for event in execution.snapshot()["events"] if event["kind"] == "step"]
    assert [event["status"] for event in steps] == ["started", "finished"]
    assert steps[0]["summary"] == "Điều phối yêu cầu đã phân loại"


def test_preclassified_graph_entry_does_not_duplicate_prior_classification():
    execution = ChatExecution()
    execution.record("node_started", {"node": "orchestrator", "state_before": {}})
    execution.record(
        "node_finished", {"node": "orchestrator", "state_before": {}, "state_delta": {"intent": "metric_query"}}
    )
    state = {"intent": "metric_query"}
    execution.record("node_started", {"node": "orchestrator", "state_before": state})
    execution.record("node_finished", {"node": "orchestrator", "state_before": state, "state_delta": state})
    assert len([event for event in execution.snapshot()["events"] if event["kind"] == "step"]) == 2


def test_repeated_invocations_have_distinct_ids_and_errors_are_safe():
    execution = ChatExecution()
    with execution_context(execution):
        with execution_step("sql_compile"):
            pass
        with pytest.raises(ValueError), execution_step("sql_compile"):
            raise ValueError("private SQL")
    events = [event for event in execution.finish("error")["events"] if event["kind"] == "step"]
    assert events[0]["step_id"] == events[1]["step_id"]
    assert events[2]["step_id"] != events[0]["step_id"]
    assert events[-1]["status"] == "failed"
    assert "private SQL" not in json.dumps(events)


@pytest.mark.asyncio
async def test_disconnect_reconnect_shares_task_and_replays_snapshot():
    release = asyncio.Event()
    entered = asyncio.Event()
    calls = 0

    @trace_node("data_assistant")
    async def agent(state):
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()
        return {"chat_response": "answer"}

    async def operation():
        await agent({"private": "never public"})
        return SimpleNamespace(model_dump=lambda **kwargs: {"answer": "ok"})

    key = (1, None, "test-db", "stream-client")
    task, execution = start_chat_task(key, operation)
    await entered.wait()
    first = stream_execution(task, execution)
    assert "event: snapshot" in await anext(first)
    await first.aclose()
    same_task, same_execution = start_chat_task(key, operation)
    assert same_task is task and same_execution is execution and not task.cancelled()
    release.set()
    frames = [frame async for frame in stream_execution(task, execution)]
    assert calls == 1
    assert "data_assistant" in frames[0]
    assert "event: result" in frames[-1]
    assert "never public" not in "".join(frames)


@pytest.mark.asyncio
async def test_stream_delivers_parser_explanation_on_node_completion():
    execution = ChatExecution()
    release = asyncio.Event()

    @trace_node("semantic_parse")
    async def parse(state):
        await release.wait()
        return {"interpretation": {"status": "resolved", "rationale": "Revenue by customer"}}

    async def operation():
        with execution_context(execution):
            await parse({})
        return SimpleNamespace(model_dump=lambda **kwargs: {})

    task = asyncio.create_task(operation())
    stream = stream_execution(task, execution)
    await anext(stream)
    release.set()
    frames = [frame async for frame in stream]
    assert any('"outcome_summary": "Revenue by customer"' in frame for frame in frames)


@pytest.mark.asyncio
async def test_parallel_runs_do_not_share_context():
    async def run(name):
        execution = ChatExecution()
        with execution_context(execution):
            with execution_step(name):
                await asyncio.sleep(0)
        return execution.snapshot()

    left, right = await asyncio.gather(run("context"), run("dedupe"))
    assert left["run_id"] != right["run_id"]
    assert {event["action"] for event in left["events"] if event["kind"] == "step"} == {"context"}
    assert {event["action"] for event in right["events"] if event["kind"] == "step"} == {"dedupe"}
