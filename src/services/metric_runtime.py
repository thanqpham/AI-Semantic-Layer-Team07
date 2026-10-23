"""One bounded provider policy for metric agents, without nested SDK retries."""

from __future__ import annotations

import asyncio
import hashlib
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

from pydantic import BaseModel

from src.models.metric_review import MetricExecutionError
from src.observability import trace_action
from src.services.llm import get_llm
from src.services.llm_json import extract_json, response_text

_ModelT = TypeVar("_ModelT", bound=BaseModel)
# shortcut: limits live in one worker; use a shared limiter before scaling workers.
_locks: dict[tuple[Any, str], asyncio.Semaphore] = {}


class MetricCallError(Exception):
    """Carry a safe error without retaining provider response text in reports."""

    def __init__(self, error: MetricExecutionError) -> None:
        super().__init__(error.code)
        self.error = error


def execution_failure(
    code: str, stage: str, retryable: bool = False, delay: float | None = None
) -> MetricExecutionError:
    """Build allowlisted, user-facing failure details."""
    messages = {
        "INVALID_AGENT_OUTPUT": "AI chưa tạo được định nghĩa hoặc phản hồi có cấu trúc hợp lệ.",
        "RATE_LIMITED": "Nhà cung cấp đang giới hạn lượt gọi. Hãy thử lại sau.",
        "QUOTA_EXHAUSTED": "Tài khoản LLM đã hết quota hoặc hạn mức thanh toán.",
        "PROVIDER_ERROR": "Không thể hoàn tất lời gọi tới nhà cung cấp LLM.",
        "LLM_BUSY": "Tài khoản LLM đang xử lý yêu cầu khác. Hãy thử lại sau.",
    }
    return MetricExecutionError(
        code=code, stage=stage, message=messages[code], retryable=retryable, retry_after_seconds=delay
    )


async def invoke_metric_json(contract: type[_ModelT], messages: Any, stage: str = "builder") -> _ModelT:
    """Serialize credential use and make at most two provider submissions."""
    try:
        llm = get_llm(role="metric", max_retries=0)
    except Exception:
        raise MetricCallError(execution_failure("PROVIDER_ERROR", stage)) from None
    lock = _credential_lock(llm)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=10)
    except TimeoutError:
        raise MetricCallError(execution_failure("LLM_BUSY", stage, True, 10)) from None
    try:
        return await _invoke_bounded(llm, contract, messages, stage)
    finally:
        lock.release()


def _credential_lock(llm: Any) -> asyncio.Semaphore:
    key = getattr(llm, "openai_api_key", None) or getattr(llm, "anthropic_api_key", None)
    secret = key.get_secret_value() if hasattr(key, "get_secret_value") else str(key or id(llm))
    endpoint = str(
        getattr(llm, "openai_api_base", None) or getattr(llm, "anthropic_api_url", None) or type(llm).__name__
    )
    digest = hashlib.sha256(f"{endpoint}:{secret}".encode()).hexdigest()
    identity = (asyncio.get_running_loop(), digest)
    return _locks.setdefault(identity, asyncio.Semaphore(1))


async def _invoke_bounded(llm: Any, contract: type[_ModelT], messages: Any, stage: str) -> _ModelT:
    structured = True
    for attempt in range(2):
        try:
            result = await _submit(llm, contract, messages, structured)
        except Exception as exc:
            if structured and _unsupported_structured(exc) and attempt == 0:
                structured = False
                continue
            error = _provider_error(exc, stage)
            if attempt == 0 and error.code == "RATE_LIMITED" and error.retry_after_seconds <= 10:
                await trace_action("metric_provider_wait", {}, asyncio.sleep(error.retry_after_seconds))
                continue
            raise MetricCallError(error) from None
        try:
            return result if isinstance(result, contract) else contract.model_validate(result)
        except (ValueError, TypeError):
            raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", stage)) from None
    raise MetricCallError(execution_failure("PROVIDER_ERROR", stage))


async def _submit(llm: Any, contract: type[BaseModel], messages: Any, structured: bool) -> Any:
    if structured:
        return await llm.with_structured_output(contract, method="function_calling").ainvoke(messages, temperature=0.0)
    raw = await llm.ainvoke(messages, temperature=0.0)
    try:
        return extract_json(response_text(raw))
    except (ValueError, TypeError):
        raise MetricCallError(execution_failure("INVALID_AGENT_OUTPUT", "output")) from None


def _unsupported_structured(exc: Exception) -> bool:
    if isinstance(exc, NotImplementedError):
        return True
    if getattr(exc, "status_code", None) != 400:
        return False
    body = str(getattr(exc, "body", "")).lower()
    return any(word in body for word in ("unsupported", "not supported", "unknown parameter")) and any(
        word in body for word in ("tool", "function", "response_format", "structured")
    )


def _provider_error(exc: Exception, stage: str) -> MetricExecutionError:
    if isinstance(exc, MetricCallError):
        return exc.error.model_copy(update={"stage": stage})
    body = getattr(exc, "body", {}) or {}
    nested = body.get("error", body) if isinstance(body, dict) else {}
    code = str(nested.get("code", "") or nested.get("type", "")).lower() if isinstance(nested, dict) else ""
    if code in {"insufficient_quota", "quota_exceeded", "billing_hard_limit_reached", "credits_exhausted"}:
        return execution_failure("QUOTA_EXHAUSTED", stage)
    if getattr(exc, "status_code", None) == 429 or "ratelimit" in type(exc).__name__.lower():
        headers = getattr(getattr(exc, "response", None), "headers", {}) or {}
        return execution_failure("RATE_LIMITED", stage, True, _retry_after(headers.get("retry-after")))
    return execution_failure("PROVIDER_ERROR", stage)


def _retry_after(value: str | None) -> float:
    if value is None:
        return 2
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            seconds = (date.replace(tzinfo=date.tzinfo or UTC) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return 2
    return max(0, seconds) if math.isfinite(seconds) else 2
