"""Tests for the enrichment generate dispatch and progress status endpoints."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.api import routes
from src.models.db import LiveTargetDbModel, SemanticDatabaseModel
from src.services import enrichment_progress
from tests.test_api.test_canonical_routes import _raw_schema_metadata


async def _seed_live_source(async_session: AsyncSession, db_id: int, source_id: int) -> None:
    """Seed a semantic db with a linked live DB source."""
    async_session.add_all(
        [
            SemanticDatabaseModel(
                id=db_id,
                created_by=1,
                display_name="Live DB",
                db_type="postgresql",
                conn_url_enc=f"semantic:live_target_db:{source_id}",
                status="draft",
            ),
            LiveTargetDbModel(
                id=source_id,
                created_by=1,
                display_name="Live DB",
                dialect="postgresql",
                conn_url_enc="encrypted_url",
                semantic_db_id=db_id,
                schema_metadata=_raw_schema_metadata().model_dump(mode="json"),
            ),
        ]
    )
    await async_session.commit()


@pytest.fixture
def auth_headers():
    """Create a valid JWT header for the seeded test user (id=1)."""
    from src.api.auth import create_access_token
    from src.models.db import UserModel

    user = UserModel(
        id=1,
        email="test@company.com",
        username="tester",
        full_name="Tester",
        hashed_password="hash",
        status="active",
    )
    token = create_access_token(user)
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_generate_dispatches_background_when_idle(
    async_session: AsyncSession, client: AsyncClient, auth_headers: dict
) -> None:
    """POST /semantic/generate claims the registry, returns 202 and dispatches the task."""
    await _seed_live_source(async_session, 401, 71)
    with patch("src.api.routes._generate_background", new_callable=AsyncMock) as mock_bg:
        res = await client.post("/api/v1/semantic/generate", json={"db_id": 401}, headers=auth_headers)
    assert res.status_code == 202
    assert res.json() == {"db_id": 401, "status": "started"}
    assert mock_bg.await_count == 1
    assert mock_bg.call_args[0][1] == 401
    # The claim is synchronous: a second request (or a fast double-click) sees running.
    assert enrichment_progress.get(401)["status"] == "running"


@pytest.mark.asyncio
async def test_generate_conflicts_while_enrichment_running(
    async_session: AsyncSession, client: AsyncClient, auth_headers: dict
) -> None:
    """A second generate while a run is in flight gets 409 and no second dispatch."""
    await _seed_live_source(async_session, 402, 72)
    enrichment_progress.start(402, 3)
    with patch("src.api.routes._generate_background", new_callable=AsyncMock) as mock_bg:
        res = await client.post("/api/v1/semantic/generate", json={"db_id": 402}, headers=auth_headers)
    assert res.status_code == 409
    assert res.json()["detail"] == "Enrichment is already running"
    assert mock_bg.await_count == 0


@pytest.mark.asyncio
async def test_status_endpoint_idle_then_running(
    async_session: AsyncSession, client: AsyncClient, auth_headers: dict
) -> None:
    """GET enrich/status mirrors the registry snapshot."""
    async_session.add(
        SemanticDatabaseModel(
            id=403,
            created_by=1,
            display_name="Live DB",
            db_type="postgresql",
            conn_url_enc="dummy",
            status="draft",
        )
    )
    await async_session.commit()

    res = await client.get("/api/v1/semantic/403/enrich/status", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["db_id"] == 403
    assert body["status"] == "idle"
    assert body["phase"] is None

    enrichment_progress.start(403, 7)
    enrichment_progress.mark_generating(403, 3, 7, "orders")
    res = await client.get("/api/v1/semantic/403/enrich/status", headers=auth_headers)
    body = res.json()
    assert body["status"] == "running"
    assert body["phase"] == "generating"
    assert body["total_tables"] == 7
    assert body["completed_tables"] == 3
    assert body["current_table"] == "orders"
    assert body["started_at"] is not None


@pytest.mark.asyncio
async def test_status_hides_other_users_db(
    async_session: AsyncSession, client: AsyncClient, auth_headers: dict
) -> None:
    """A semantic db owned by someone else is invisible to the caller."""
    async_session.add(
        SemanticDatabaseModel(
            id=404,
            created_by=999,
            display_name="Not yours",
            db_type="postgresql",
            conn_url_enc="dummy",
            status="draft",
        )
    )
    await async_session.commit()

    res = await client.get("/api/v1/semantic/404/enrich/status", headers=auth_headers)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_generate_background_marks_registry_failed(async_session: AsyncSession) -> None:
    """A failing enrichment run records its error in the registry."""
    db_id = 405

    async def _fake_session():
        yield async_session

    with (
        patch("src.api.routes.get_db_session", _fake_session),
        patch(
            "src.api.routes.enrich_and_save_canonical_schema",
            AsyncMock(side_effect=RuntimeError("LLM down")),
        ),
    ):
        await routes._generate_background(1, db_id, _raw_schema_metadata(), "postgresql")

    snapshot = enrichment_progress.get(db_id)
    assert snapshot["status"] == "failed"
    assert "LLM down" in (snapshot["error"] or "")


@pytest.mark.asyncio
async def test_generate_background_marks_failed_on_cancel(async_session: AsyncSession) -> None:
    """A cancelled run cannot leave the registry stuck at running."""
    db_id = 406

    async def _hang(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(60)

    async def _fake_session():
        yield async_session

    with (
        patch("src.api.routes.get_db_session", _fake_session),
        patch("src.api.routes.enrich_and_save_canonical_schema", AsyncMock(side_effect=_hang)),
    ):
        task = asyncio.create_task(routes._generate_background(1, db_id, _raw_schema_metadata(), "postgresql"))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    snapshot = enrichment_progress.get(db_id)
    assert snapshot["status"] == "failed"
    assert snapshot["error"] is not None
