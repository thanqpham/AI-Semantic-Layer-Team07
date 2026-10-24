"""Shared state update for metric workflow failures."""

from typing import Any

from src.models.metric_review import MetricReview


def record_failure(item: dict[str, Any], error: Any) -> None:
    item["report"] = MetricReview(status="error", summary=error.message, execution_error=error)
    item["phase"] = "done"


