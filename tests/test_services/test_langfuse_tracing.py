"""Tracing must preserve application results and keep sensitive state local."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.config import Settings
from src.observability import activate_trace, trace_action, trace_node, trace_value
from src.observability import langfuse_tracing as tracing


@pytest.fixture(autouse=True)
def isolate_client():
    tracing.get_tracing_client.cache_clear()
    yield
    tracing.get_tracing_client.cache_clear()


def fake_client(monkeypatch):
    client, span = MagicMock(), MagicMock()
    client.start_as_current_observation.return_value.__enter__.return_value = span
    monkeypatch.setattr(tracing, "get_tracing_client", lambda: client)
    return client, span


def test_disabled_does_not_initialize_sdk(monkeypatch):
    monkeypatch.setattr(tracing, "get_settings", lambda: Settings(_env_file=None, langfuse_tracing_enabled=False))
    assert tracing.get_tracing_client() is None
    assert tracing.llm_trace_callbacks() == []
    with tracing.observation("disabled") as span:
        assert span is None


def test_missing_keys_disables_tracing(monkeypatch):
    settings = Settings(_env_file=None, langfuse_tracing_enabled=True, langfuse_public_key="", langfuse_secret_key="")
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    assert tracing.get_tracing_client() is None


def test_initialization_failure_does_not_break_app(monkeypatch):
    import langfuse

    settings = Settings(
        _env_file=None, langfuse_tracing_enabled=True, langfuse_public_key="pk", langfuse_secret_key="sk"
    )
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    monkeypatch.setattr(langfuse, "Langfuse", MagicMock(side_effect=RuntimeError("secret")))
    assert tracing.get_tracing_client() is None


def test_errors_keep_identity_but_do_not_export_message(monkeypatch):
    client, span = fake_client(monkeypatch)
    error = ValueError("postgresql://user:secret@host/db")
    with pytest.raises(ValueError) as raised, tracing.observation("guardrail"):
        raise error
    assert raised.value is error
    span.update.assert_called_once_with(level="ERROR", status_message="ValueError")
    client.start_as_current_observation.return_value.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.asyncio
async def test_node_and_action_preserve_benchmark_and_hide_state(monkeypatch):
    client, span = fake_client(monkeypatch)
    sink = MagicMock()

    @trace_node("test_node")
    async def node(state):
        return await trace_action("test_action", {"secret": state["secret"]}, AsyncMock(return_value={"answer": 42})())

    with activate_trace(sink):
        assert await node({"secret": "never export", "session_id": "session-1"}) == {"answer": 42}
    assert [call.args[0] for call in sink.record.call_args_list] == [
        "node_started",
        "action_started",
        "action_finished",
        "node_finished",
    ]
    assert "never export" not in str(client.mock_calls)
    assert client.start_as_current_observation.call_count == 2
    assert "never export" not in str(span.update.mock_calls)
    assert any(
        call.kwargs.get("output", {}).get("trace_summary", {}).get("status") == "finished"
        for call in span.update.call_args_list
    )


@pytest.mark.asyncio
async def test_returned_node_error_is_marked_without_content(monkeypatch):
    _, span = fake_client(monkeypatch)

    @trace_node("test_node")
    async def node(state):
        return {"error": "secret"}

    assert await node({}) == {"error": "secret"}
    span.update.assert_any_call(level="ERROR", status_message="node_error")
    assert "secret" not in str(span.update.mock_calls)


def test_sync_action_preserves_result(monkeypatch):
    fake_client(monkeypatch)
    assert trace_value("guardrail", {}, lambda: 123) == 123
    assert tracing._mask_content(data={"secret": "value"}) == "[REDACTED]"
    assert tracing._mask_content(
        data={"trace_summary": {"intent": "metric_query", "proposal_count": 2, "family_count": 1}}
    ) == {
        "trace_summary": {"intent": "metric_query", "proposal_count": 2, "family_count": 1}
    }
    assert tracing._mask_content(data={"trace_summary": {"intent": "private", "sql_length": -1}}) == "[REDACTED]"
    assert tracing._mask_content(
        data={"trace_summary": {"reason_unresolved_assumption_count": 2, "reason_code": "PRIVATE"}}
    ) == {"trace_summary": {"reason_unresolved_assumption_count": 2}}


def test_api_no_longer_has_langfuse_request_middleware():
    from src.main import app

    assert "LangfuseMiddleware" not in {item.cls.__name__ for item in app.user_middleware}


@pytest.fixture
def sdk_exporter(monkeypatch):
    import langfuse
    from langfuse._client import span_processor
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter, provider = InMemorySpanExporter(), TracerProvider()
    original = langfuse.Langfuse
    monkeypatch.setattr(span_processor, "OTLPSpanExporter", lambda **kwargs: exporter)
    monkeypatch.setattr(langfuse, "Langfuse", lambda **kwargs: original(tracer_provider=provider, **kwargs))
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_CAPTURE_CONTENT", "true")
    settings = Settings(
        _env_file=None,
        langfuse_tracing_enabled=True,
        langfuse_public_key=f"pk-test-{uuid4()}",
        langfuse_secret_key="sk-test",
    )
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    yield exporter
    tracing.shutdown_tracing()
    provider.shutdown()


@pytest.mark.asyncio
async def test_real_sdk_keeps_agent_hierarchy_usage_and_safe_summary(sdk_exporter):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from langgraph.graph import StateGraph

    model = FakeMessagesListChatModel(
        responses=[
            AIMessage(
                content="private-answer", usage_metadata={"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
            )
        ],
        callbacks=tracing.llm_trace_callbacks(),
    )

    @trace_node("sdk-node")
    async def node(state):
        response = await trace_action("sdk-action", {}, model.ainvoke("private-prompt"))
        return {"answer": response.content}

    graph = StateGraph(dict)
    graph.add_node("sdk-node", node)
    graph.set_entry_point("sdk-node")
    graph.set_finish_point("sdk-node")
    with tracing.observation("sdk-request", agent=True):
        await graph.compile().ainvoke({"session_id": "session-sdk", "connection_url": "private-connection"})
    tracing.get_tracing_client().flush()
    spans = sdk_exporter.get_finished_spans()
    assert len(spans) == 4
    assert len({span.context.trace_id for span in spans}) == 1
    assert all(span.attributes["session.id"] == "session-sdk" for span in spans)
    generation = next(span for span in spans if span.attributes.get("langfuse.observation.type") == "generation")
    action = next(span for span in spans if span.name == "sdk-action")
    assert generation.parent.span_id == action.context.span_id
    assert json.loads(generation.attributes["langfuse.observation.usage_details"]) == {
        "input": 10,
        "output": 3,
        "total": 13,
    }
    exported = str([dict(span.attributes) for span in spans])
    assert "private-connection" not in exported
    assert "private-prompt" not in exported and "private-answer" not in exported
    assert spans[-1].attributes["langfuse.observation.type"] == "agent"
    assert any("finished" in str(span.attributes.get("langfuse.observation.output", "")) for span in spans)


def test_real_sdk_provider_error_does_not_export_secret(sdk_exporter):
    from langchain_core.messages import HumanMessage

    handler = tracing.llm_trace_callbacks()[0]
    run_id = uuid4()
    with tracing.observation("sdk-error", agent=True):
        handler.on_chat_model_start({}, [[HumanMessage("private-prompt")]], run_id=run_id, invocation_params={})
        handler.on_llm_error(ValueError("private-credential"), run_id=run_id)
    tracing.get_tracing_client().flush()
    spans = sdk_exporter.get_finished_spans()
    generation = next(span for span in spans if span.attributes.get("langfuse.observation.type") == "generation")
    assert generation.attributes["langfuse.observation.level"] == "ERROR"
    assert generation.attributes["langfuse.observation.status_message"] == "ValueError"
    assert "private-credential" not in str([dict(span.attributes) for span in spans])


def test_chain_error_does_not_export_exception_text(sdk_exporter):
    handler = tracing.llm_trace_callbacks()[0]
    run_id = uuid4()
    with tracing.observation("chat_agent", agent=True):
        handler.on_chain_start({}, {"prompt": "private-prompt"}, run_id=run_id)
        handler.on_chain_error(ValueError("private-credential"), run_id=run_id)
    tracing.get_tracing_client().flush()
    exported = str([dict(span.attributes) for span in sdk_exporter.get_finished_spans()])
    assert "private-prompt" not in exported and "private-credential" not in exported


@pytest.mark.asyncio
async def test_non_agent_llm_is_not_exported(sdk_exporter):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage

    model = FakeMessagesListChatModel(
        responses=[AIMessage(content="private-answer")], callbacks=tracing.llm_trace_callbacks()
    )
    with tracing.observation("ordinary-service"):
        await model.ainvoke("private-prompt")
    tracing.get_tracing_client().flush()
    assert sdk_exporter.get_finished_spans() == ()


@pytest.mark.asyncio
async def test_non_agent_api_request_is_not_exported(sdk_exporter):
    from httpx import ASGITransport, AsyncClient

    from src.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/docs")
    assert response.status_code == 200
    tracing.get_tracing_client().flush()
    assert sdk_exporter.get_finished_spans() == ()


@pytest.mark.asyncio
async def test_background_chat_task_keeps_agent_root(sdk_exporter, monkeypatch):
    from src.api import routes

    @trace_node("orchestrator")
    async def node(state):
        return {"intent": "metric_query"}

    async def run_inner(*_args):
        await node({"session_id": "chat-session", "user_message": "private-prompt"})
        return SimpleNamespace(intent="metric_query", run_status="completed", suggestions=[])

    monkeypatch.setattr(routes, "_process_standard_chat_inner", run_inner)
    session = SimpleNamespace(id="chat-session")
    await asyncio.create_task(routes._process_standard_chat(None, session, None, 1, None, True))
    tracing.get_tracing_client().flush()
    spans = sdk_exporter.get_finished_spans()
    assert [span.name for span in spans] == ["orchestrator", "chat_agent"]
    assert spans[0].parent.span_id == spans[1].context.span_id
    assert all(span.attributes["session.id"] == "chat-session" for span in spans)
    assert "private-prompt" not in str([dict(span.attributes) for span in spans])


@pytest.mark.asyncio
async def test_standalone_metric_workflow_creates_root(sdk_exporter, monkeypatch):
    from src.agents.workflows import metric_proposal_workflow as workflow

    graph = SimpleNamespace(ainvoke=AsyncMock(side_effect=lambda state: state))
    monkeypatch.setattr(workflow, "_graph", lambda: graph)
    assert await workflow.run_metric_workflow({"proposal_mode": "requested", "question": "private"}, drafts=[]) == []
    tracing.get_tracing_client().flush()
    spans = sdk_exporter.get_finished_spans()
    assert len(spans) == 1 and spans[0].name == "metric_workflow"
    assert spans[0].attributes["langfuse.observation.type"] == "agent"
    assert "private" not in str(dict(spans[0].attributes))


@pytest.mark.asyncio
async def test_standalone_schema_node_and_sql_action_hide_raw_data(sdk_exporter):
    from src.agents.nodes.schema.enrich_node import enrich_node

    await enrich_node({"raw_schema": {}, "conn_url_enc": "private-connection"})
    with tracing.observation("query_agent", agent=True):
        await trace_action("sql_execute", {"sql": "private-sql"}, AsyncMock(return_value=[{"email": "private-row"}])())
    tracing.get_tracing_client().flush()
    spans = sdk_exporter.get_finished_spans()
    assert {span.name for span in spans} == {"enrich", "query_agent", "sql_execute"}
    assert next(span for span in spans if span.name == "enrich").parent is None
    exported = str([dict(span.attributes) for span in spans])
    assert all(secret not in exported for secret in ("private-connection", "private-sql", "private-row"))
