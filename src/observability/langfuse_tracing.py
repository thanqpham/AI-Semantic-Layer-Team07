"""Optional request, agent and LLM tracing; never export application state."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.config import get_settings

logger = logging.getLogger(__name__)


def _mask_content(*, data: Any, **_kwargs: Any) -> str:
    """Hide SDK inputs, outputs and metadata while preserving model usage."""
    return "[REDACTED]"


@lru_cache(maxsize=1)
def get_tracing_client() -> Any:
    """Initialize once per process; configuration changes require a restart."""
    settings = get_settings()
    if not settings.langfuse_tracing_enabled:
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.warning("Langfuse tracing disabled: public/secret key is missing")
        return None
    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            base_url=settings.langfuse_base_url,
            environment=settings.app_env,
            mask=None if settings.langfuse_capture_content else _mask_content,
        )
    except Exception:
        logger.warning("Langfuse initialization failed; tracing disabled")
        return None


def llm_trace_callbacks() -> list[BaseCallbackHandler]:
    """Attach the official integration to every provider used by get_llm()."""
    if get_tracing_client() is None:
        return []
    from langfuse.langchain import CallbackHandler

    class SafeCallbackHandler(CallbackHandler):
        def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
            # Provider error text can contain URLs, credentials or prompt content.
            super().on_llm_error(RuntimeError(type(error).__name__), **kwargs)

    return [SafeCallbackHandler(public_key=get_settings().langfuse_public_key)]


@contextmanager
def observation(name: str, *, session_id: str | None = None) -> Iterator[Any]:
    """Create a span without recording arguments, results or raw exceptions."""
    client = get_tracing_client()
    if client is None:
        yield None
        return
    from langfuse import propagate_attributes

    error = None
    with client.start_as_current_observation(name=name, as_type="span") as span:
        with propagate_attributes(session_id=session_id):
            try:
                yield span
            except BaseException as exc:
                span.update(level="ERROR", status_message=type(exc).__name__)
                error = exc
    if error is not None:
        raise error


def shutdown_tracing() -> None:
    """Drain queued observations when the application stops."""
    client = get_tracing_client()
    if client is not None:
        try:
            client.shutdown()
        except Exception:
            logger.warning("Langfuse shutdown failed")


class LangfuseMiddleware:
    """Keep a root span active through streaming responses and background tasks."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/"):
            await self.app(scope, receive, send)
            return
        with observation(f"{scope['method']} api") as span:

            async def traced_send(message: Message) -> None:
                if span is not None and message["type"] == "http.response.start":
                    route = scope.get("route")
                    span.update(
                        name=f"{scope['method']} {getattr(route, 'path', '/api')}",
                        level="ERROR" if message["status"] >= 500 else "DEFAULT",
                        status_message=f"HTTP {message['status']}",
                    )
                await send(message)

            await self.app(scope, receive, traced_send)
