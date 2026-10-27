import pytest

from src.models.db import CanonicalRelationshipModel
from src.services.query_compiler_metadata import _safe_join_path
from src.services.semantic_compile_error import SemanticCompileError


def edge(id, start, end, kind="many_to_one"):
    return CanonicalRelationshipModel(
        id=id,
        from_entity_id=start,
        to_entity_id=end,
        relationship_type=kind,
        review_status="approved",
        validation_status="valid",
        column_pairs=[{"from_column_id": start, "to_column_id": end}],
    )


@pytest.mark.parametrize(
    "edges",
    [
        [edge(1, 1, 2), edge(2, 1, 2)],
        [edge(1, 1, 2), edge(2, 1, 3), edge(3, 3, 2)],
        [edge(1, 1, 3), edge(2, 3, 2), edge(3, 1, 4), edge(4, 4, 2)],
    ],
)
def test_all_safe_paths_are_ambiguous(edges):
    with pytest.raises(SemanticCompileError) as error:
        _safe_join_path(edges, 1, 2)
    assert error.value.code == "AMBIGUOUS_JOIN_PATH"
    assert len(error.value.context["paths"]) == 2


def test_reverse_one_to_one_and_cycles():
    path = _safe_join_path([edge(1, 2, 1, "one_to_one"), edge(2, 2, 3), edge(3, 3, 2)], 1, 2)
    assert path[0].id == 1
    assert path[0].to_entity_id == 2
    assert path[0].column_pairs == [{"from_column_id": 1, "to_column_id": 2}]


@pytest.mark.parametrize("kind", ["many_to_one", "many_to_many", "one_to_many"])
def test_unsafe_fanout(kind):
    start, end = (2, 1) if kind == "many_to_one" else (1, 2)
    with pytest.raises(SemanticCompileError) as error:
        _safe_join_path([edge(1, start, end, kind)], 1, 2)
    assert error.value.code == "UNSAFE_FANOUT"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("review", "validation", "expected"),
    [
        ("approved", "valid", True),
        ("pending", "valid", False),
        ("rejected", "valid", False),
        ("disabled", "valid", False),
        ("needs_review", "valid", False),
        ("approved", "invalid", False),
        ("approved", None, False),
    ],
)
async def test_strict_runtime_predicate(review, validation, expected):
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import create_async_engine

    from src.services.relationship_runtime import active_relationship_filters

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE canonical_relationships (id INTEGER, review_status TEXT, validation_status TEXT)")
        )
        await conn.execute(
            text("INSERT INTO canonical_relationships VALUES (1,:review,:validation)"),
            {"review": review, "validation": validation},
        )
        result = await conn.execute(select(CanonicalRelationshipModel.id).where(*active_relationship_filters()))
        assert bool(result.all()) is expected
    await engine.dispose()


async def _seed_runtime_tables(async_session):
    from src.models.db import SemanticColumnModel, SemanticDatabaseModel, SemanticTableModel

    db = SemanticDatabaseModel(display_name="runtime gate", db_type="sqlite", conn_url_enc="enc", created_by=1)
    async_session.add(db)
    await async_session.flush()
    tables = [SemanticTableModel(db_id=db.id, table_name=name, business_name=name) for name in ["orders", "customers"]]
    async_session.add_all(tables)
    await async_session.flush()
    columns = [
        SemanticColumnModel(table_id=t.id, column_name="region", data_type="TEXT", business_name="Region")
        for t in tables
    ]
    async_session.add_all(columns)
    await async_session.flush()
    return db, tables, columns


async def _seed_runtime_relationship(async_session, db, tables, columns, source, review, validation):
    from src.models.db_relationships import RelationshipCandidateModel

    fields = dict(
        connection_id=db.id,
        from_entity_id=tables[0].id,
        to_entity_id=tables[1].id,
        relationship_type="many_to_one",
        source=source,
        column_pairs=[{"from_column_id": columns[0].id, "to_column_id": columns[1].id}],
    )
    if review in {"pending_review", "rejected"}:
        rel = RelationshipCandidateModel(**fields, status=review, fingerprint=review)
    else:
        rel = CanonicalRelationshipModel(
            **fields,
            join_condition="orders.region = customers.region",
            review_status=review,
            validation_status=validation,
        )
    async_session.add(rel)
    return rel


async def _seed_runtime_metric(async_session, db, tables):
    from src.models.db import SemanticMetricModel

    metric = SemanticMetricModel(
        db_id=db.id,
        base_entity_id=tables[0].id,
        name="count",
        description="Count",
        sql_template="SELECT COUNT(*) FROM orders",
        status="approved",
    )
    async_session.add(metric)
    await async_session.commit()
    return metric


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source", "review", "validation", "active"),
    [
        ("fk", "approved", "valid", True),
        ("manual", "approved", "valid", True),
        ("ai", "approved", "valid", True),
        ("ai", "pending_review", "valid", False),
        ("ai", "rejected", "valid", False),
        ("ai", "disabled", "valid", False),
        ("ai", "needs_review", "valid", False),
        ("fk", "approved", "invalid", False),
    ],
)
async def test_runtime_consumers_share_gate(async_session, source, review, validation, active):
    from src.api.routes import _catalog_relationships
    from src.services.dimension_recommender import get_dimensions_for_metric, get_filter_columns_for_metric
    from src.services.export_service import _load_relationships
    from src.services.metric_context import _load_metadata
    from src.services.query_compiler_metadata import QueryCompilerMetadata

    db, tables, columns = await _seed_runtime_tables(async_session)
    rel = await _seed_runtime_relationship(async_session, db, tables, columns, source, review, validation)
    metric = await _seed_runtime_metric(async_session, db, tables)
    compiler = QueryCompilerMetadata(async_session)
    assert bool((await compiler.load_metric_plan_metadata(db.id)).relationships) is active
    assert bool((await _load_metadata(async_session, db.id))[1]) is active
    assert bool(await _load_relationships(async_session, db.id)) is active
    assert bool(await _catalog_relationships(async_session, db.id)) is active
    dimensions = await get_dimensions_for_metric(async_session, db.id, metric.id)
    filters = await get_filter_columns_for_metric(async_session, db.id, metric.id)
    assert any(item.table_id == tables[1].id for item in dimensions) is active
    assert any(item.table_id == tables[1].id for item in filters) is active
    if active:
        joins = await compiler.resolve_joins(db.id, tables[0], [{"table_id": tables[1].id}], {t.id: t for t in tables})
        assert joins[0]["relationship_id"] == rel.id
    else:
        with pytest.raises(SemanticCompileError, match="not reachable"):
            await compiler.resolve_joins(db.id, tables[0], [{"table_id": tables[1].id}], {t.id: t for t in tables})


@pytest.mark.parametrize("reverse", [False, True])
def test_composite_one_to_one_predicate_keeps_all_pairs(reverse):
    from src.services.query_compiler_metadata import _relationship_condition

    rel = edge(7, 1, 2, "one_to_one")
    rel.column_pairs = [
        {"from_column_id": 10, "to_column_id": 20},
        {"from_column_id": 11, "to_column_id": 21},
    ]
    path = _safe_join_path([rel], 2 if reverse else 1, 1 if reverse else 2)
    columns = {
        10: (None, "orders", "tenant_id"),
        11: (None, "orders", "customer_id"),
        20: (None, "customers", "tenant_id"),
        21: (None, "customers", "id"),
    }
    condition = _relationship_condition(path[0], columns)
    assert condition.count(" = ") == 2
    assert " AND " in condition
    assert all(
        name in condition
        for name in ['"orders"."tenant_id"', '"orders"."customer_id"', '"customers"."tenant_id"', '"customers"."id"']
    )
    assert path[0].id == 7


@pytest.mark.parametrize("reachable", [False, True])
def test_dense_cycles_use_bounded_reachability(monkeypatch, reachable):
    from collections import deque

    import src.services.relationship_runtime as runtime

    class BoundedDeque(deque):
        pushes = 0

        def append(self, value):
            type(self).pushes += 1
            assert type(self).pushes < 500, "Traversal enumerated cyclic path prefixes"
            return super().append(value)

    monkeypatch.setattr(runtime, "deque", BoundedDeque)
    edges = [edge(a * 20 + b, a, b) for a in range(1, 13) for b in range(1, 13) if a != b]
    if reachable:
        edges.append(edge(999, 1, 99))
    paths = runtime.relationship_paths(edges, 1, 99)
    assert bool(paths) is reachable
    if reachable:
        assert [[step.id for step in path] for path in paths] == [[999]]


@pytest.mark.asyncio
@pytest.mark.parametrize("diamond", [False, True])
async def test_review_detail_reuses_ambiguous_path_ids(async_session, diamond):
    from src.services.relationship_review_service import review_item

    db, tables, columns = await _seed_runtime_tables(async_session)
    first = await _seed_runtime_relationship(async_session, db, tables, columns, "manual", "approved", "valid")
    second = await _seed_runtime_relationship(async_session, db, tables, columns, "manual", "approved", "valid")
    second.relationship_key = "alternative"
    if diamond:
        from src.models.db import SemanticTableModel

        middle = SemanticTableModel(db_id=db.id, table_name="middle", business_name="Middle")
        async_session.add(middle)
        await async_session.flush()
        second.to_entity_id = middle.id
        third = edge(999, middle.id, tables[1].id)
        third.connection_id, third.relationship_key, third.join_condition = db.id, "third", "preview"
        async_session.add(third)
    await async_session.commit()
    detail = await review_item(async_session, db.id, first, "active")
    warning = next(item for item in detail.warnings if item["code"] == "AMBIGUOUS_JOIN_PATH")
    assert warning["context"]["paths"] == [[first.id], [second.id, 999] if diamond else [second.id]]
    assert detail.model_dump()["warnings"] == detail.warnings
