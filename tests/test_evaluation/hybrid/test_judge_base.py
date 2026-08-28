"""Tests for the judge runner: caching, retry, timeout, structured parsing."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eval.evaluator.hybrid.judge.base import (
    JudgeEvaluationError,
    JudgeRequest,
    JudgeRunner,
    LangChainJudgeLLM,
)
from eval.evaluator.hybrid.judge.cache import MemoryJudgeCache, judge_cache_key
from src.config import Settings

_GOOD = """```json
{"criteria": [{"name": "clarity", "score": 1.0}], "overall": 1.0, "summary": "fine"}
```"""


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def invoke(self, system: str, user: str) -> str:
        self.calls += 1
        return self.responses.pop(0)


def _request() -> JudgeRequest:
    return JudgeRequest(
        system_prompt="sys",
        user_prompt="usr",
        prompt_version="v1",
        rubric_version="1.0.0",
        model="fake",
        cache_key=judge_cache_key("s1", "h", "1.0.0", "v1", "fake"),
    )


async def test_parses_fenced_json_and_caches() -> None:
    llm = FakeLLM([_GOOD])
    cache = MemoryJudgeCache()
    runner = JudgeRunner(llm, cache)
    verdict = await runner.evaluate(_request())
    assert verdict is not None and verdict.overall == 1.0
    again = await runner.evaluate(_request())
    assert again == verdict
    assert llm.calls == 1  # second call served from cache


async def test_retries_then_succeeds() -> None:
    llm = FakeLLM(["not json at all", _GOOD])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=3)
    verdict = await runner.evaluate(_request())
    assert verdict is not None
    assert llm.calls == 2


async def test_raises_with_attempt_causes_after_exhausted_retries() -> None:
    llm = FakeLLM(["nope", "nope", "nope"])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=3)
    with pytest.raises(JudgeEvaluationError, match=r"3 attempts.*1\).*2\).*3\)"):
        await runner.evaluate(_request())
    assert llm.calls == 3


async def test_exhaustion_message_names_each_failure_cause() -> None:
    llm = FakeLLM(["not json"])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=1)
    with pytest.raises(JudgeEvaluationError, match="ValidationError"):
        await runner.evaluate(_request())


async def test_schema_mismatch_is_retried_not_accepted() -> None:
    llm = FakeLLM(['{"criteria": [], "overall": 0.5}', _GOOD])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=2)
    verdict = await runner.evaluate(_request())
    assert verdict is not None and verdict.overall == 1.0


def test_langchain_judge_uses_isolated_model() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="openai",
        openai_api_key="agent-secret",
        model_name="agent-model",
        judge_llm_provider="groq",
        judge_api_key="judge-secret",
        judge_model_name="judge-model",
    )

    def _client(**kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(model_name=kwargs["model"])

    with (
        patch("src.services.llm.get_settings", return_value=settings),
        patch("src.services.llm.ChatOpenAI", side_effect=_client),
    ):
        judge = LangChainJudgeLLM()
    assert judge.model_name == "judge-model"


def test_langchain_judge_accepts_native_protocol_model_attribute() -> None:
    client = SimpleNamespace(model="native-judge-model")
    with patch("src.services.llm.get_llm", return_value=client):
        judge = LangChainJudgeLLM()
    assert judge.model_name == "native-judge-model"


# ---------------------------------------------------------------------------
# reasoning-capable judge models emit <think> blocks before the verdict
# ---------------------------------------------------------------------------

_THINK_THEN_FENCE = (
    '<think>\nReasoning about clarity... may contain {"criteria": "fake"} braces inside.\n</think>\n'
    '```json\n{"criteria": [{"name": "clarity", "score": 1.0}], "overall": 1.0, "summary": "fine"}\n```'
)

_THINK_THEN_BARE = (
    '<think>reasoning first</think>\n{"criteria": [{"name": "clarity", "score": 0.5}], "overall": 0.5, "summary": "ok"}'
)


async def test_strips_think_block_before_fenced_json() -> None:
    llm = FakeLLM([_THINK_THEN_FENCE])
    runner = JudgeRunner(llm, MemoryJudgeCache())
    verdict = await runner.evaluate(_request())
    assert verdict is not None and verdict.overall == 1.0
    assert llm.calls == 1  # parsed on the first attempt, no retry burned


async def test_strips_think_block_before_bare_json() -> None:
    llm = FakeLLM([_THINK_THEN_BARE])
    verdict = await JudgeRunner(llm, MemoryJudgeCache()).evaluate(_request())
    assert verdict is not None and verdict.overall == 0.5


async def test_think_without_json_still_fails_honestly() -> None:
    llm = FakeLLM(["<think>only reasoning, never a verdict</think>"])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=1)
    with pytest.raises(JudgeEvaluationError):
        await runner.evaluate(_request())


# ---------------------------------------------------------------------------
# truncated completions are labeled as truncation, not generic invalid JSON
# ---------------------------------------------------------------------------

_UNCLOSED_THINK = '<think>\ndrafting {"criteria": ...} but the output never finishes'


async def test_unclosed_think_is_labeled_truncated() -> None:
    llm = FakeLLM([_UNCLOSED_THINK])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=1)
    with pytest.raises(JudgeEvaluationError, match=r"TruncatedJudgeOutputError.*unclosed <think>"):
        await runner.evaluate(_request())


async def test_unterminated_fence_is_labeled_truncated() -> None:
    """A fenced body cut mid-string loses its closing fence — still truncation."""
    cut = '```json\n{"criteria": [{"name": "clarity", "score": 1.0}], "overall": 1.0, "summary": "sai lệch'
    llm = FakeLLM([cut])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=1)
    with pytest.raises(JudgeEvaluationError, match=r"TruncatedJudgeOutputError.*unclosed markdown fence"):
        await runner.evaluate(_request())


async def test_bare_json_cut_mid_token_is_labeled_truncated() -> None:
    """A bare JSON body cut mid-string (token limit) gets the truncation label."""
    cut = '{"criteria": [{"name": "clarity", "score": 1.0}], "overall": 1.0, "summary": "sai lệch'
    llm = FakeLLM([cut])
    runner = JudgeRunner(llm, MemoryJudgeCache(), max_attempts=1)
    with pytest.raises(JudgeEvaluationError, match=r"TruncatedJudgeOutputError.*token limit"):
        await runner.evaluate(_request())
