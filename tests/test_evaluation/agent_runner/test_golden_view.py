"""Golden views expose only leakage-safe case fields."""

from pathlib import Path

from eval.agent_runner.golden_view import (
    GuardrailCaseView,
    MetricCaseView,
    iter_discovery_ids,
    iter_guardrail_cases,
    iter_metric_cases,
    iter_query_cases,
)
from eval.dataset.loader import load_domain_dataset


async def test_views_cover_all_cases_without_expected_fields():
    dataset = await load_domain_dataset(Path("eval/golden_dataset"), "ecommerce")
    metric_cases = iter_metric_cases(dataset)
    query_cases = iter_query_cases(dataset)
    discovery_ids = iter_discovery_ids(dataset)
    guardrail_cases = iter_guardrail_cases(dataset)

    assert len(discovery_ids) == 4
    assert len(metric_cases) == 12
    assert len(query_cases) == 32
    assert len(guardrail_cases) == 13
    first = metric_cases[0]
    assert isinstance(first, MetricCaseView)
    assert first.request
    assert not hasattr(first, "expected_metric")
    assert not hasattr(iter_query_cases(dataset)[0], "expected")
    first_probe = guardrail_cases[0]
    assert isinstance(first_probe, GuardrailCaseView)
    assert first_probe.sql
    assert not hasattr(first_probe, "expected")
