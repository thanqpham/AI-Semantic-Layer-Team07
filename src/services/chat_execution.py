"""Public, allowlisted execution progress, independent of raw observability data."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from src.models.metric_review import MetricOutputIssue
from src.observability import activate_trace

LABELS = {
    "orchestrator": "Phân loại yêu cầu",
    "chitchat": "Soạn phản hồi hội thoại",
    "data_assistant": "Tra cứu semantic layer và metric đã duyệt",
    "metric_suggest": "Đề xuất định nghĩa metric",
    "metric_coordinator": "Điều phối các agent metric",
    "metric_validate": "Kiểm tra kỹ thuật bằng code",
    "metric_conclude": "Coordinator chốt kết quả thẩm định",
    "metric_provider_wait": "Đợi nhà cung cấp cho phép thử lại",
    "metric_review": "Thẩm định metric trước HITL",
    "metric_review_decision": "Đối chiếu yêu cầu và kiểm tra nghiệp vụ",
    "metric_output_validation": "Phản hồi AI sai cấu trúc",
    "metric_repair": "Sửa metric theo kết quả thẩm định",
    "semantic_parse": "Phân tích câu hỏi theo danh mục metric",
    "context": "Chuẩn bị ngữ cảnh dữ liệu",
    "dedupe": "Kiểm tra metric trùng lặp",
    "metric_generation": "Sinh định nghĩa metric",
    "metric_generation_retry": "Thử lại với các cột hợp lệ",
    "sql_compile": "Biên dịch và kiểm tra truy vấn",
    "sql_execute": "Thực thi truy vấn chỉ đọc",
    "out_of_scope": "Yêu cầu ngoài phạm vi hỗ trợ",
    "clarification": "Yêu cầu làm rõ câu hỏi",
    "response": "Hoàn tất phản hồi",
}
AGENTS = {
    "orchestrator",
    "chitchat",
    "data_assistant",
    "metric_suggest",
    "metric_review",
    "semantic_parse",
}
SAFE_ERROR = "Không thể hoàn tất xử lý. Vui lòng thử lại."
_CURRENT: ContextVar[ChatExecution | None] = ContextVar("chat_execution", default=None)


def current_execution() -> ChatExecution | None:
    """Return the execution belonging to this task only."""
    return _CURRENT.get()


@contextmanager
def execution_context(execution: ChatExecution) -> Iterator[None]:
    """Collect public progress while retaining the existing node instrumentation."""
    token = _CURRENT.set(execution)
    try:
        with activate_trace(execution):
            yield
    finally:
        _CURRENT.reset(token)


@contextmanager
def execution_step(name: str) -> Iterator[None]:
    """Measure a system step without capturing its inputs or results."""
    execution = current_execution()
    step_id = execution.start(name, name) if execution else None
    try:
        yield
    except Exception:
        if execution and step_id:
            execution.end(step_id, "failed")
        raise
    else:
        if execution and step_id:
            execution.end(step_id, "finished")


class ChatExecution:
    """Keep a bounded chat run's public events available to reconnecting clients."""

    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.trace: dict[str, Any] = {
            "run_id": str(uuid.uuid4()),
            "status": "running",
            "started_at": self.now(),
            "finished_at": None,
            "elapsed_ms": 0,
            "events": [],
        }
        self.changed = asyncio.Event()
        self.active: dict[tuple[str, str], list[str]] = {}
        self.steps: dict[str, dict[str, Any]] = {}
        self.last_node = "request"
        self.user_message_id: str | None = None
        self.replayed = False

    @staticmethod
    def now() -> str:
        """Return an unambiguous UTC timestamp."""
        return datetime.now(UTC).isoformat()

    def elapsed(self) -> int:
        """Measure elapsed time independently of wall-clock changes."""
        return round((time.perf_counter() - self.started) * 1000)

    def snapshot(self) -> dict[str, Any]:
        """Copy public state so later updates cannot mutate a transmitted snapshot."""
        return {
            **self.trace,
            "elapsed_ms": self.elapsed() if self.trace["status"] == "running" else self.trace["elapsed_ms"],
            "events": list(self.trace["events"]),
        }

    def emit(self, **fields: Any) -> dict[str, Any]:
        """Append an event made exclusively from server-owned identifiers and labels."""
        event = {"seq": len(self.trace["events"]) + 1, "at": self.now(), "elapsed_ms": self.elapsed(), **fields}
        self.trace["events"].append(event)
        self.changed.set()
        return event

    def transition(self, source: str, target: str) -> None:
        """Record an actual control-flow edge, including non-agent terminal steps."""
        if source == target:
            return
        self.emit(
            kind="transition",
            source=source,
            target=target,
            node=target,
            step_id=str(uuid.uuid4()),
            status="finished",
            summary=LABELS.get(target, ""),
        )

    def start(self, node: str, action: str, summary: str | None = None) -> str:
        """Start one uniquely identified invocation, retaining repeated invocations."""
        flow_node = "sql" if action == "sql_compile" else node
        self.transition(self.last_node, flow_node)
        self.last_node = flow_node
        step_id = str(uuid.uuid4())
        event = self.emit(
            kind="step", node=node, action=action, step_id=step_id, status="started", summary=summary or LABELS[action]
        )
        self.steps[step_id] = event
        self.active.setdefault((node, action), []).append(step_id)
        return step_id

    def end(self, step_id: str, status: str, outcome: str | None = None) -> None:
        """Finish a particular invocation using monotonic elapsed time."""
        event = self.steps.pop(step_id, None)
        if event is None:
            return
        self.active[(event["node"], event["action"])].remove(step_id)
        fields = {"outcome_summary": outcome} if outcome else {}
        self.emit(
            kind="step",
            node=event["node"],
            action=event["action"],
            step_id=step_id,
            status=status,
            summary=event["summary"],
            duration_ms=self.elapsed() - event["elapsed_ms"],
            **fields,
        )

    def record(self, kind: str, payload: Mapping[str, Any]) -> None:
        """Project raw trace events onto an explicit public allowlist."""
        if kind == "metric_output_error":
            self._metric_output_error(payload)
            return
        if kind == "transition":
            self._graph_transition(payload)
            return
        node = payload.get("node")
        action = node if kind.startswith("node_") else payload.get("action")
        if kind.startswith("action_") and action == node:
            return
        preclassified = node == "orchestrator" and bool(payload.get("state_before", {}).get("intent"))
        if (
            preclassified
            and kind.endswith("_started")
            and any(
                event.get("kind") == "step" and event.get("node") == "orchestrator" for event in self.trace["events"]
            )
        ):
            return
        if action not in LABELS or not kind.startswith(("node_", "action_")):
            return
        safe_node = node if node in AGENTS else action
        if kind.endswith("_started"):
            self.start(safe_node, action, "Điều phối yêu cầu đã phân loại" if preclassified else None)
        elif kind.endswith(("_finished", "_failed")):
            pending = self.active.get((safe_node, action), [])
            if pending:
                outcome = (
                    _safe_outcome(safe_node, payload.get("state_delta", {})) if kind.endswith("_finished") else None
                )
                self.end(pending[-1], "failed" if kind.endswith("_failed") else "finished", outcome)

    def _metric_output_error(self, payload: Mapping[str, Any]) -> None:
        issues = [MetricOutputIssue.model_validate(item) for item in payload.get("validation_errors", [])]
        if not issues:
            return
        stage = payload.get("stage")
        node = {"reviewer": "metric_review", "builder": "metric_suggest", "repair": "metric_repair"}.get(
            stage, "metric_validate"
        )
        summary = "; ".join(f"{item.field} ({item.type})" for item in issues)
        self.emit(
            kind="step",
            node=node,
            action="metric_output_validation",
            step_id=str(uuid.uuid4()),
            status="failed",
            summary=f"Phản hồi {stage} sai cấu trúc: {summary}",
            candidate_id=payload.get("candidate_id"),
            attempt=payload.get("attempt"),
            validation_errors=[item.model_dump() for item in issues],
        )

    def _graph_transition(self, payload: Mapping[str, Any]) -> None:
        source = payload.get("node")
        target = {
            "metric_query": "metric_coordinator",
            "data_question": "data_assistant",
            "semantic_query": "semantic_parse",
            "chitchat_done": "response",
        }.get(payload.get("action"), payload.get("action"))
        if source not in AGENTS or target not in LABELS:
            return
        if self.last_node == "request":
            self.transition("request", source)
        self.transition(source, target)
        self.last_node = target

    def finish(self, status: str, intent: str | None = None) -> dict[str, Any]:
        """Close unfinished steps and add only the terminal edges actually taken."""
        if self.trace["status"] != "running":
            return self.snapshot()
        for step_id in list(self.steps):
            self.end(step_id, "failed" if status == "error" else "finished")
        if status != "error":
            terminal = (
                "clarification"
                if status == "needs_clarification"
                else ("out_of_scope" if intent == "out_of_scope" else "response")
            )
            self.transition(self.last_node, terminal)
            if terminal != "response":
                self.transition(terminal, "response")
        self.trace.update(status=status, finished_at=self.now(), elapsed_ms=self.elapsed())
        self.changed.set()
        return self.snapshot()


def _safe_outcome(node: str, output: Any) -> str | None:
    """Return bounded, user-facing explanations and approved output facts."""
    if not isinstance(output, Mapping):
        return None
    if node == "orchestrator":
        intent = output.get("intent")
        if not isinstance(intent, str):
            return None
        return {
            "semantic_query": "Truy vấn dữ liệu theo metric",
            "metric_query": "Đề xuất hoặc định nghĩa metric",
            "data_question": "Tìm hiểu cấu trúc dữ liệu và metric",
            "chitchat": "Trả lời hội thoại",
            "out_of_scope": "Yêu cầu ngoài phạm vi hỗ trợ",
        }.get(intent)
    if node == "semantic_parse":
        interpretation = output.get("interpretation")
        if isinstance(interpretation, Mapping):
            rationale = interpretation.get("rationale")
            if isinstance(rationale, str) and rationale.strip():
                return _bounded(rationale.strip())
            status = interpretation.get("status")
            if isinstance(status, str):
                return {"resolved": "Đã phân tích yêu cầu", "needs_clarification": "Cần làm rõ yêu cầu"}.get(status)
    if node == "metric_review" and isinstance(output.get("items"), list):
        summaries = [getattr(item.get("report"), "summary", None) for item in output["items"] if isinstance(item, dict)]
        text = "; ".join(summary.strip() for summary in summaries[:5] if isinstance(summary, str) and summary.strip())
        if text:
            return _bounded(text)
    metrics = output.get("suggested_metrics")
    if isinstance(metrics, list):
        return _bounded(f"Đề xuất {len(metrics)} metric")
    return None


def _bounded(value: str) -> str:
    return value[:500]


def sse(event: str, payload: Any) -> str:
    """Encode one SSE frame without placing untrusted content in its headers."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def stream_execution(task: asyncio.Task, execution: ChatExecution) -> AsyncIterator[str]:
    """Replay a snapshot, follow progress, and leave the shared task alive on disconnect."""
    snapshot = execution.snapshot()
    cursor = len(snapshot["events"])
    yield sse("snapshot", snapshot)
    while not task.done():
        execution.changed.clear()
        events = execution.trace["events"][cursor:]
        for event in events:
            yield sse("progress", event)
        cursor += len(events)
        try:
            await asyncio.wait_for(execution.changed.wait(), timeout=10)
        except TimeoutError:
            yield ": heartbeat\n\n"
    for event in execution.trace["events"][cursor:]:
        yield sse("progress", event)
    try:
        result = task.result()
    except Exception:
        yield sse("error", {"message": SAFE_ERROR, "execution_trace": execution.finish("error")})
    else:
        yield sse("result", result.model_dump(mode="json"))
