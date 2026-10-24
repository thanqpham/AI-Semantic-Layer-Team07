"""Shared state update for metric workflow failures."""

from typing import Any

from src.models.metric_review import MetricReview
from src.observability.agent_trace import trace_metric_output_error


def record_failure(item: dict[str, Any], error: Any) -> None:
    error = error.model_copy(update={"candidate_id": item["id"], "attempt": item["attempt"]})
    if error.validation_errors:
        trace_metric_output_error(error.model_dump(mode="json"))
    item["report"] = MetricReview(status="error", summary=error.message, execution_error=error)
    item["phase"] = "done"
