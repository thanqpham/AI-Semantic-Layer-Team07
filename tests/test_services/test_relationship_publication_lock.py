"""Interleaved publication and relationship mutation transaction regressions."""

import pytest
from fastapi import HTTPException

from src.models.db import CanonicalRelationshipModel, SemanticMetricModel
from src.services.relationship_review_service import (
    decide_relationship,
    preview_relationship_change,
    save_relationship_candidate,
)
from tests.test_services.test_relationship_review import approve, seed


@pytest.mark.asyncio
async def test_publication_and_graph_decision_share_transaction_lock(tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.models.db import Base
    from src.services.metric_definition_resolver import MetricDefinitionResolver
    from src.services.metric_service import approve_metric, create_metric

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publication.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db_id, _, _, draft = await seed(db)
        approved = await approve(db, db_id, await save_relationship_candidate(db, db_id, 1, draft))
        active_id = approved.active_relationship_id
        metric = await create_metric(
            db,
            db_id,
            {
                "definition": {
                    "metric": {
                        "name": "Count",
                        "formula": {"function": "COUNT", "expression": "id"},
                        "base_entity": "same",
                        "filters": [],
                        "status": "pending_approval",
                        "confidence": "high",
                        "excluded_notes": "",
                    }
                }
            },
            1,
        )
        metric_id = metric.id
        impact = await preview_relationship_change(db, db_id, active_id, kind="active", action="disable")
        assert impact.metric_ids == []
        await db.commit()
    resolving, release, decision_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    publication_ready, allow_commit = asyncio.Event(), asyncio.Event()
    original = MetricDefinitionResolver.resolve

    async def paused_resolve(resolver, *args, **kwargs):
        result = await original(resolver, *args, **kwargs)
        resolving.set()
        await release.wait()
        return result

    monkeypatch.setattr(MetricDefinitionResolver, "resolve", paused_resolve)

    async def publish():
        async with factory() as db:
            await approve_metric(db, metric_id, 1)
            publication_ready.set()
            await allow_commit.wait()
            await db.commit()

    async def disable():
        async with factory() as db:
            decision_started.set()
            try:
                await decide_relationship(
                    db,
                    db_id,
                    1,
                    active_id,
                    kind="active",
                    action="disable",
                    expected_revision=1,
                    impact_token=impact.token,
                    acknowledge_impact=True,
                )
                await db.commit()
                return 200
            except HTTPException as error:
                await db.rollback()
                return error.status_code

    publication = asyncio.create_task(publish())
    decision = None
    try:
        await asyncio.wait_for(resolving.wait(), 2)
        decision = asyncio.create_task(disable())
        await decision_started.wait()
        await asyncio.sleep(0.05)
        assert not decision.done(), "Graph mutation must wait for the publication transaction"
        release.set()
        await asyncio.wait_for(publication_ready.wait(), 3)
        assert not decision.done(), "Service return must not release the publication lock"
        allow_commit.set()
        await asyncio.wait_for(publication, 3)
        assert await asyncio.wait_for(decision, 3) == 409
        async with factory() as db:
            updated = await preview_relationship_change(db, db_id, active_id, kind="active", action="disable")
            assert updated.metric_ids == [metric_id]
            await decide_relationship(
                db,
                db_id,
                1,
                active_id,
                kind="active",
                action="disable",
                expected_revision=1,
                impact_token=updated.token,
                acknowledge_impact=True,
            )
            await db.commit()
        async with factory() as db:
            assert (await db.get(SemanticMetricModel, metric_id)).status == "needs_review"
    finally:
        release.set()
        allow_commit.set()
        await asyncio.gather(publication, *([decision] if decision else []), return_exceptions=True)
        await engine.dispose()


@pytest.mark.asyncio
async def test_publication_resolves_after_uncommitted_graph_change(tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from src.models.db import Base
    from src.services.metric_definition_resolver import MetricDefinitionResolver
    from src.services.metric_service import approve_metric, create_metric

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'graph-first.sqlite'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        db_id, _, _, draft = await seed(db)
        approved = await approve(db, db_id, await save_relationship_candidate(db, db_id, 1, draft))
        active_id = approved.active_relationship_id
        metric = await create_metric(
            db,
            db_id,
            {
                "definition": {
                    "metric": {
                        "name": "Count",
                        "formula": {"function": "COUNT", "expression": "id"},
                        "base_entity": "same",
                        "filters": [],
                        "status": "pending_approval",
                        "confidence": "high",
                        "excluded_notes": "",
                    }
                }
            },
            1,
        )
        metric_id = metric.id
        impact = await preview_relationship_change(db, db_id, active_id, kind="active", action="disable")
        await db.commit()
    resolving, started = asyncio.Event(), asyncio.Event()
    original = MetricDefinitionResolver.resolve

    async def observe_resolve(resolver, *args, **kwargs):
        row = await resolver._db.get(CanonicalRelationshipModel, active_id)
        assert row.review_status == "disabled"
        resolving.set()
        return await original(resolver, *args, **kwargs)

    monkeypatch.setattr(MetricDefinitionResolver, "resolve", observe_resolve)

    async def publish():
        async with factory() as db:
            started.set()
            await approve_metric(db, metric_id, 1)
            await db.commit()

    task = None
    try:
        async with factory() as graph_db:
            await decide_relationship(
                graph_db,
                db_id,
                1,
                active_id,
                kind="active",
                action="disable",
                expected_revision=1,
                impact_token=impact.token,
                acknowledge_impact=True,
            )
            task = asyncio.create_task(publish())
            await started.wait()
            await asyncio.sleep(0.05)
            assert not resolving.is_set(), "Publication must not resolve an uncommitted graph snapshot"
            await graph_db.commit()
        await asyncio.wait_for(task, 3)
        assert resolving.is_set()
    finally:
        if task:
            await asyncio.gather(task, return_exceptions=True)
        await engine.dispose()
