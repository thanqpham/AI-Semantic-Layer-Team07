"""Enrichment collector: real services + replay, readback, canonical adapter."""

from pathlib import Path

from eval.agent_runner.adapters import to_enrichment_candidate
from eval.agent_runner.canonical_resolver import CanonicalResolver
from eval.agent_runner.enrichment import collect_enrichment, load_enrichment_state
from eval.dataset.loader import load_domain_dataset

GOLDEN_ROOT = Path("eval/golden_dataset")


async def _resolver() -> CanonicalResolver:
    dataset = await load_domain_dataset(GOLDEN_ROOT, "ecommerce")
    return CanonicalResolver.from_dataset(dataset, {})


async def test_enrichment_persists_and_readback(enriched):
    ctx, conn_id, _raw = enriched
    async with ctx.session_maker() as db:
        state = await load_enrichment_state(db, conn_id)
    assert {t.table_name for t in state.tables} >= {"fact_orders", "customers"}
    assert state.relationships


async def test_to_enrichment_candidate_emits_canonical_names(enriched):
    ctx, conn_id, _raw = enriched
    async with ctx.session_maker() as db:
        state = await load_enrichment_state(db, conn_id)
    candidate = to_enrichment_candidate(state, resolver=await _resolver())

    entities = {e.entity: e for e in candidate.entities}
    assert "order" in entities  # physical fact_orders -> canonical order
    assert "fact_orders" not in entities
    dimension_names = {d.name for d in entities["order"].dimensions}
    assert "order_status" in dimension_names
    assert "order_id" not in dimension_names  # primary key never a dimension
    assert "order_date" not in dimension_names  # time column never a dimension

    relationships = [r for e in candidate.entities for r in e.relationships]
    assert any(
        r.source_entity == "order"
        and r.target_entity == "customer"
        and r.source_field == "customer_id"
        and r.relation_type == "BELONGS_TO"
        for r in relationships
    )


async def test_collect_enrichment_shares_candidate(enriched):
    ctx, conn_id, _raw = enriched
    candidates = await collect_enrichment(ctx, conn_id, ["d1", "d2"], await _resolver())
    assert set(candidates) == {"d1", "d2"}
    assert candidates["d1"] == candidates["d2"]
