"""Judge LLM adapter and bounded-retry runner (spec §8.2)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import ValidationError

from eval.evaluator.hybrid.judge.cache import JudgeCache
from eval.evaluator.hybrid.judge.output import JudgeVerdict

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_REASONING = re.compile(r"<think>.*?</think>", re.DOTALL)


class JudgeLLM(Protocol):
    """Invoke one judge completion with system and user prompts."""

    async def invoke(self, system: str, user: str) -> str: ...


class LangChainJudgeLLM:
    """Adapt the product LLM client for judge use (get_llm, temperature 0.0)."""

    def __init__(self) -> None:
        from langchain_core.messages import HumanMessage, SystemMessage

        from src.services.llm import get_llm

        self._llm = get_llm(role="judge")
        self._message_types = (SystemMessage, HumanMessage)
        self.model_name = str(getattr(self._llm, "model_name", getattr(self._llm, "model", "configured-model")))

    async def invoke(self, system: str, user: str) -> str:
        system_type, human_type = self._message_types
        message = await self._llm.ainvoke([system_type(content=system), human_type(content=user)])
        return str(message.content)


@dataclass(frozen=True)
class JudgeRequest:
    """Carry one fully rendered judge call and its provenance."""

    system_prompt: str
    user_prompt: str
    prompt_version: str
    rubric_version: str
    model: str
    cache_key: str


class JudgeEvaluationError(RuntimeError):
    """Report judge exhaustion together with every attempt's failure cause."""


class TruncatedJudgeOutputError(ValueError):
    """A judge completion cut off before a parsable verdict existed."""


class JudgeRunner:
    """Run judge calls with caching, timeout, and bounded retries."""

    def __init__(
        self,
        llm: JudgeLLM,
        cache: JudgeCache,
        timeout_seconds: float = 45.0,
        max_attempts: int = 3,
    ) -> None:
        self.llm = llm
        self.cache = cache
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts

    async def evaluate(self, request: JudgeRequest) -> JudgeVerdict:
        """Return the cached or freshly computed verdict; raise when exhausted.

        Raising (instead of returning None) keeps the failure cause — every
        attempt's exception type and message — attached to the error result
        instead of collapsing it into an unexplained ``None``.
        """
        cached = await self.cache.get(request.cache_key)
        if cached is not None:
            return cached
        notes: list[str] = []
        for attempt in range(1, self.max_attempts + 1):
            verdict, failure = await self._attempt(request)
            if verdict is not None:
                await self.cache.set(request.cache_key, verdict)
                return verdict
            notes.append(f"{attempt}) {failure}")
        raise JudgeEvaluationError(f"judge failed after {self.max_attempts} attempts: " + "; ".join(notes))

    async def _attempt(self, request: JudgeRequest) -> tuple[JudgeVerdict | None, str | None]:
        """Try one judge call; on failure return a clipped cause note."""
        try:
            raw = await asyncio.wait_for(
                self.llm.invoke(request.system_prompt, request.user_prompt), self.timeout_seconds
            )
            return _parse_verdict(raw), None
        except (TimeoutError, ValidationError, ValueError) as exc:
            detail = " ".join(str(exc).split()) or "no detail"
            return None, f"{type(exc).__name__}: {detail[:200]}"


def _parse_verdict(raw: str) -> JudgeVerdict:
    """Validate one completion, naming truncation when no verdict arrived.

    Every truncation shape maps to :class:`TruncatedJudgeOutputError` so
    reports say what actually happened instead of a generic ValidationError:
    an unclosed ``<think>`` (reasoning cut before the verdict), an unclosed
    markdown fence, and a JSON body cut mid-token (``EOF while parsing``).
    Retries cannot fix any of them at temperature 0 — the same output is
    regenerated — so the label matters more than the retry.
    """
    cleaned = extract_json(raw)
    stripped = cleaned.lstrip()
    if stripped.startswith("<think"):
        raise TruncatedJudgeOutputError("unclosed <think> reasoning — output cut before the verdict JSON")
    if stripped.startswith("```"):
        raise TruncatedJudgeOutputError("unclosed markdown fence — output cut before the verdict JSON")
    try:
        return JudgeVerdict.model_validate_json(cleaned)
    except ValidationError as exc:
        if "EOF while parsing" in str(exc):
            raise TruncatedJudgeOutputError("JSON cut mid-token — output hit the model token limit") from exc
        raise


def extract_json(raw: str) -> str:
    """Strip reasoning blocks and markdown fences from a judge completion.

    Reasoning-capable judge models (qwen via Groq) emit ``<think>...</think>``
    before the verdict — the block may itself contain JSON-like braces, so it
    is removed before fence extraction rather than parsed around. An unclosed
    ``<think>`` does not match and parses (and fails) honestly downstream.
    """
    without_reasoning = _REASONING.sub("", raw).strip()
    match = _FENCE.search(without_reasoning)
    return match.group(1) if match else without_reasoning
