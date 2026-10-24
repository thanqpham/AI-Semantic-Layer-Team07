"""Provider retry limits, quota classification and credential serialization."""

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, SecretStr

from src.services.metric_runtime import MetricCallError, _credential_lock, _retry_after, invoke_metric_json


class Answer(BaseModel):
    value: int


class ProviderTestError(Exception):
    def __init__(self, status=429, code="rate_limit_exceeded", retry_after="0"):
        super().__init__("do-not-leak-provider-key")
        self.status_code = status
        self.body = {"error": {"code": code}}
        self.response = SimpleNamespace(headers={"retry-after": retry_after} if retry_after is not None else {})


def _client(responses):
    client = MagicMock()
    client._llm_type = "openai-chat"
    client.openai_api_key = SecretStr("private-test-key")
    client.openai_api_base = "https://model.invalid/"
    client.with_structured_output.return_value.ainvoke = AsyncMock(side_effect=responses)
    client.ainvoke = AsyncMock()
    return client


async def test_rate_limit_retries_same_operation_once_without_plain_fallback():
    client = _client([ProviderTestError(), {"value": 3}])
    with patch("src.services.metric_runtime.get_llm", return_value=client) as get_llm:
        result = await invoke_metric_json(Answer, "payload")
    assert result.value == 3
    assert client.with_structured_output.return_value.ainvoke.await_count == 2
    client.with_structured_output.assert_called_with(Answer, method="json_mode")
    messages = client.with_structured_output.return_value.ainvoke.call_args.args[0]
    assert messages[-1] == ("user", "payload")
    assert "Answer" in messages[0][1] and "schema" in messages[0][1]
    client.ainvoke.assert_not_awaited()
    get_llm.assert_called_once_with(role="metric", max_retries=0)


@pytest.mark.parametrize(
    "failure,code",
    [
        (ProviderTestError(retry_after="60"), "RATE_LIMITED"),
        (ProviderTestError(code="insufficient_quota"), "QUOTA_EXHAUSTED"),
        (ProviderTestError(status=401, code="invalid_api_key"), "PROVIDER_ERROR"),
    ],
)
async def test_long_wait_quota_and_auth_fail_without_retry_or_secret_leak(failure, code):
    client = _client([failure])
    with patch("src.services.metric_runtime.get_llm", return_value=client):
        with pytest.raises(MetricCallError) as raised:
            await invoke_metric_json(Answer, "payload")
    assert raised.value.error.code == code
    assert client.with_structured_output.return_value.ainvoke.await_count == 1
    client.ainvoke.assert_not_awaited()
    assert "do-not-leak" not in raised.value.error.model_dump_json()


async def test_exhausted_transient_retry_stops_after_two_submissions():
    client = _client([ProviderTestError(), ProviderTestError()])
    with patch("src.services.metric_runtime.get_llm", return_value=client):
        with pytest.raises(MetricCallError):
            await invoke_metric_json(Answer, "payload")
    assert client.with_structured_output.return_value.ainvoke.await_count == 2


async def test_unsupported_structured_output_has_exactly_one_plain_attempt():
    client = _client([])
    client.with_structured_output.side_effect = NotImplementedError
    client.ainvoke.return_value = SimpleNamespace(content='{"value":7}')
    with patch("src.services.metric_runtime.get_llm", return_value=client):
        assert (await invoke_metric_json(Answer, "payload")).value == 7
    client.ainvoke.assert_awaited_once_with("payload", temperature=0.0, max_tokens=4096)


async def test_invalid_json_is_not_transport_retried():
    client = _client([{"value": "wrong"}])
    with patch("src.services.metric_runtime.get_llm", return_value=client):
        with pytest.raises(MetricCallError) as raised:
            await invoke_metric_json(Answer, "payload")
    assert raised.value.error.code == "INVALID_AGENT_OUTPUT"
    assert raised.value.error.validation_errors[0].field == "value"
    assert client.with_structured_output.return_value.ainvoke.await_count == 1


async def test_sdk_wrapped_validation_error_keeps_field_without_provider_response():
    try:
        Answer.model_validate({"value": "private-provider-response"})
    except ValueError as validation:
        failure = RuntimeError("private-parser-response")
        failure.__cause__ = validation
    client = _client([failure])
    with patch("src.services.metric_runtime.get_llm", return_value=client):
        with pytest.raises(MetricCallError) as raised:
            await invoke_metric_json(Answer, "payload", "reviewer")
    assert raised.value.error.validation_errors[0].field == "value"
    assert raised.value.error.code == "INVALID_AGENT_OUTPUT"
    assert "private" not in raised.value.error.model_dump_json()


async def test_same_credential_models_share_a_limiter_and_busy_never_calls_provider():
    first, second = _client([]), _client([])
    assert _credential_lock(first) is _credential_lock(second)

    async def timeout(coroutine, timeout):
        coroutine.close()
        raise TimeoutError

    with (
        patch("src.services.metric_runtime.get_llm", return_value=first),
        patch("src.services.metric_runtime.asyncio.wait_for", AsyncMock(side_effect=timeout)),
    ):
        with pytest.raises(MetricCallError) as raised:
            await invoke_metric_json(Answer, "payload")
    assert raised.value.error.code == "LLM_BUSY"
    first.with_structured_output.assert_not_called()


def test_retry_after_supports_seconds_dates_and_invalid_headers():
    assert _retry_after(None) == _retry_after("invalid") == 2
    assert _retry_after("-1") == 0 and _retry_after("10") == 10
    delay = _retry_after(format_datetime(datetime.now(UTC) + timedelta(seconds=60)))
    assert 58 <= delay <= 60
