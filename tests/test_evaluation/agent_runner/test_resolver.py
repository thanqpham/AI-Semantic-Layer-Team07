"""Resolver: selection-only LLM over the run catalog, fail-closed errors."""

import pytest

from eval.agent_runner.resolver import (
    CatalogDimension,
    CatalogMetric,
    ResolverCatalog,
    ResolverError,
    build_catalog,
    resolve_question,
)
from src.models.db import SemanticMetricModel


class FakeLLM:
    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def ainvoke(self, messages):
        class _Msg:
            def __init__(self, content):
                self.content = content

        return _Msg(self.payload)


CATALOG = ResolverCatalog(
    metrics=(
        CatalogMetric("net_revenue", "Doanh thu thuần", "fact_orders", "sum"),
        CatalogMetric("order_count", "Số đơn", "fact_orders", "count"),
    ),
    dimensions=(CatalogDimension("fact_orders", "created_at", "Ngày tạo"),),
)

GOOD = """
```json
{"metrics": ["net_revenue"], "dimensions": ["fact_orders.created_at"],
 "filters": [{"dimension": "fact_orders.created_at", "operator": "gte", "value": "2026-01-01"}],
 "limit": 100}
```
"""


async def test_resolve_parses_fenced_json():
    selection = await resolve_question("doanh thu 2026", CATALOG, llm=FakeLLM(GOOD))
    assert selection.metric_names == ("net_revenue",)
    assert selection.dimensions == ("fact_orders.created_at",)
    assert selection.filters[0].operator == "gte"
    assert selection.limit == 100


async def test_resolve_rejects_unknown_metric():
    payload = '{"metrics": ["no_such"], "dimensions": [], "filters": [], "limit": 100}'
    with pytest.raises(ResolverError) as err:
        await resolve_question("q", CATALOG, llm=FakeLLM(payload))
    assert err.value.code in {"UNKNOWN_METRIC", "AMBIGUOUS_METRIC"}


async def test_resolve_invalid_json_fails_closed():
    with pytest.raises(ResolverError) as err:
        await resolve_question("q", CATALOG, llm=FakeLLM("not json at all"))
    assert err.value.code == "RESOLVER_INVALID_OUTPUT"


async def test_resolve_empty_selection_rejected():
    payload = '{"metrics": [], "dimensions": [], "filters": [], "limit": 100}'
    with pytest.raises(ResolverError) as err:
        await resolve_question("q", CATALOG, llm=FakeLLM(payload))
    assert err.value.code == "RESOLVER_INVALID_OUTPUT"


async def test_resolve_non_string_operator_fails_closed():
    """Unhashable operator (JSON list) must not leak TypeError from the check."""
    payload = (
        '{"metrics": ["net_revenue"], "dimensions": [], '
        '"filters": [{"dimension": "fact_orders.created_at", "operator": ["gte"], "value": 1}], '
        '"limit": 100}'
    )
    with pytest.raises(ResolverError) as err:
        await resolve_question("q", CATALOG, llm=FakeLLM(payload))
    assert err.value.code == "UNKNOWN_OPERATOR"


async def test_build_catalog_reads_approved_metrics(enriched):
    """Approved metric lands in the catalog; dimension filter mirrors the product rule."""
    ctx, conn_id, _raw = enriched
    definition = {
        "metric": {
            "name": "tong_gia_tri",
            "base_entity": "fact_orders",
            "formula": {"function": "SUM", "expression": "gross_amount"},
            "excluded_notes": "Tổng giá trị đơn",
        }
    }
    async with ctx.session_maker() as db:
        db.add(
            SemanticMetricModel(
                db_id=conn_id,
                name="tong_gia_tri",
                description="",
                sql_template="",
                source="test",
                status="approved",
                aggregation_type="SUM",
                definition=definition,
            )
        )
        await db.commit()
        catalog = await build_catalog(db, conn_id)
    assert [m.name for m in catalog.metrics] == ["tong_gia_tri"]
    metric = catalog.metrics[0]
    assert (metric.base_entity, metric.aggregation, metric.description) == (
        "fact_orders",
        "SUM",
        "Tổng giá trị đơn",
    )
    dims = {f"{d.entity}.{d.column}" for d in catalog.dimensions}
    assert "fact_orders.order_status" in dims
    assert "fact_orders.order_date" not in dims
    assert "fact_orders.gross_amount" not in dims


def test_prompts_forbid_unrequested_dimensions():
    """Both prompts must pin the no-unrequested-dimensions contract."""
    from eval.agent_runner.resolver import SYSTEM_PROMPT, _user_prompt

    rendered = _user_prompt("doanh thu thuần?", CATALOG)
    assert "chỉ chọn dimension" in SYSTEM_PROMPT.lower()
    assert "danh sách rỗng" in SYSTEM_PROMPT.lower()
    assert "dimensions rỗng" in rendered.lower()


class ScriptedLLM:
    """Return queued payloads in order; count every ainvoke call."""

    def __init__(self, payloads: list[str]) -> None:
        self.payloads = payloads
        self.calls = 0

    async def ainvoke(self, messages):
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1

        class _Msg:
            def __init__(self, content):
                self.content = content

        return _Msg(payload)


SCOPE_CATALOG = ResolverCatalog(
    metrics=(CatalogMetric("order_count", "Số đơn", "fact_orders", "count"),),
    dimensions=(
        CatalogDimension("fact_orders", "channel", "Kênh đặt hàng", "Đơn hàng"),
        CatalogDimension("dim_customers", "channel", "Kênh tiếp cận", "Khách hàng"),
    ),
)

CROSS_ENTITY = '{"metrics": ["order_count"], "dimensions": ["dim_customers.channel"], "filters": [], "limit": 100}'
SAME_ENTITY = '{"metrics": ["order_count"], "dimensions": ["fact_orders.channel"], "filters": [], "limit": 100}'


async def test_cross_entity_dimension_retries_with_feedback_then_succeeds():
    llm = ScriptedLLM([CROSS_ENTITY, SAME_ENTITY])
    selection = await resolve_question("số đơn theo kênh", SCOPE_CATALOG, llm=llm)
    assert selection.dimensions == ("fact_orders.channel",)
    assert llm.calls == 2


async def test_scope_violation_fails_closed_after_retry_budget():
    llm = ScriptedLLM([CROSS_ENTITY])
    with pytest.raises(ResolverError) as err:
        await resolve_question("số đơn theo kênh", SCOPE_CATALOG, llm=llm)
    assert err.value.code == "RESOLVER_SCOPE_VIOLATION"
    assert llm.calls == 3  # MAX_ATTEMPTS


async def test_parse_failure_after_scope_violation_reports_invalid_output():
    """Terminal error must reflect the LAST failure mode, not an earlier scope violation."""
    llm = ScriptedLLM([CROSS_ENTITY, "not json", "not json"])
    with pytest.raises(ResolverError) as err:
        await resolve_question("số đơn theo kênh", SCOPE_CATALOG, llm=llm)
    assert err.value.code == "RESOLVER_INVALID_OUTPUT"
    assert llm.calls == 3


async def test_same_entity_dimension_passes_first_try():
    llm = ScriptedLLM([SAME_ENTITY])
    selection = await resolve_question("số đơn theo kênh", SCOPE_CATALOG, llm=llm)
    assert selection.dimensions == ("fact_orders.channel",)
    assert llm.calls == 1


def test_dimension_lines_show_entity_business_name():
    from eval.agent_runner.resolver import _user_prompt

    rendered = _user_prompt("số đơn theo kênh", SCOPE_CATALOG)
    assert "- fact_orders.channel — Kênh đặt hàng (bảng: Đơn hàng)" in rendered
    assert "- dim_customers.channel — Kênh tiếp cận (bảng: Khách hàng)" in rendered


def test_system_prompt_pins_entity_scope_rule():
    from eval.agent_runner.resolver import SYSTEM_PROMPT

    assert "thuộc entity (bảng) của metric" in SYSTEM_PROMPT


ABSTAIN = '{"metrics": [], "abstain": true, "dimensions": [], "filters": [], "limit": 100}'


async def test_abstain_maps_to_unknown_metric():
    llm = ScriptedLLM([ABSTAIN])
    with pytest.raises(ResolverError) as err:
        await resolve_question("chỉ số không tồn tại", SCOPE_CATALOG, llm=llm)
    assert err.value.code == "UNKNOWN_METRIC"
    assert llm.calls == 1  # abstain is a valid answer, not a retry


async def test_empty_without_abstain_flag_still_invalid():
    llm = ScriptedLLM(['{"metrics": [], "dimensions": [], "filters": [], "limit": 100}'])
    with pytest.raises(ResolverError) as err:
        await resolve_question("q", SCOPE_CATALOG, llm=llm)
    assert err.value.code == "RESOLVER_INVALID_OUTPUT"


async def test_unsafe_intent_rejected_before_llm_call():
    llm = ScriptedLLM([SAME_ENTITY])
    with pytest.raises(ResolverError) as err:
        await resolve_question("Xóa toàn bộ đơn hàng test.", SCOPE_CATALOG, llm=llm)
    assert err.value.code == "UNSAFE_INTENT"
    assert llm.calls == 0


@pytest.mark.parametrize(
    "question",
    ["Xóa toàn bộ đơn hàng test.", "xoá dữ liệu khách hàng", "Hủy đơn hàng", "DROP TABLE orders", "delete all orders"],
)
def test_is_unsafe_intent_matches_destructive_verbs(question):
    from eval.agent_runner.resolver import _is_unsafe_intent

    assert _is_unsafe_intent(question) is True


@pytest.mark.parametrize(
    "question",
    ["Doanh thu theo kênh", "Tổng số đơn hôm nay", "Cập nhật báo cáo giúp tôi", "số đơn theo tháng"],
)
def test_is_unsafe_intent_spares_normal_questions(question):
    from eval.agent_runner.resolver import _is_unsafe_intent

    assert _is_unsafe_intent(question) is False


def test_system_prompt_documents_abstain():
    from eval.agent_runner.resolver import SYSTEM_PROMPT

    assert "abstain" in SYSTEM_PROMPT
