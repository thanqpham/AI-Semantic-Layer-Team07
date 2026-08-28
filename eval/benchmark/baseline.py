"""Compare benchmark evidence only when provenance is compatible."""

from __future__ import annotations

from eval.benchmark.contracts import BaselineComparison, BenchmarkRunResult


def compare_baseline(current: BenchmarkRunResult, baseline: BenchmarkRunResult | None) -> BaselineComparison | None:
    """Compare score, latency, and cost with a pinned compatible release artifact."""
    if baseline is None:
        return None
    if not _compatible(current, baseline):
        return BaselineComparison(compatible=False, detail="profile model/provider or contract version differs")
    return BaselineComparison(
        compatible=True,
        score_delta=_delta(current.overall_score, baseline.overall_score),
        latency_delta=_delta(_mean_latency(current), _mean_latency(baseline)),
        cost_delta=_delta(_total_cost(current), _total_cost(baseline)),
        detail="compatible pinned baseline",
    )


def _compatible(current: BenchmarkRunResult, baseline: BenchmarkRunResult) -> bool:
    return (
        current.contract_version == baseline.contract_version
        and current.profile.model == baseline.profile.model
        and current.profile.provider == baseline.profile.provider
    )


def _delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return (current - baseline) / baseline


def _mean_latency(result: BenchmarkRunResult) -> float | None:
    values = [item.latency_ms for item in result.events if item.latency_ms is not None]
    return sum(values) / len(values) if values else None


def _total_cost(result: BenchmarkRunResult) -> float:
    return sum(item.estimated_cost_usd for item in result.events)
