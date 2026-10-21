"""Runtime account configuration stays isolated across async AI requests."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from httpx import ASGITransport, AsyncClient

from src.api.auth import create_access_token
from src.api.llm_settings_routes import use_account_llm
from src.config import Settings
from src.models.db import SemanticDatabaseModel, UserModel
from src.models.llm_settings import LLMSettingsRequest
from src.services import llm
from src.services.database import get_db_session
from src.services.llm_settings_service import save_llm_settings
from src.services.schema_cron_service import _sync_with_owner_llm


@pytest.mark.asyncio
async def test_concurrent_requests_and_background_tasks_keep_their_own_config(monkeypatch):
    monkeypatch.setattr(llm, "_client_cache", {})
    monkeypatch.setitem(llm._CLIENT_BUILDERS, "openai", lambda config: SimpleNamespace(model=config.model))
    monkeypatch.setattr(llm, "_settings_with_hot_reload", lambda: Settings(_env_file=None, llm_model_metric="old-env-model"))

    async def request(model):
        config = llm.LLMConfig("openai", "openai", model, "https://api.openai.com/v1", model, 0.0)
        token = llm.account_llm_config.set(config)
        try:
            task = asyncio.create_task(asyncio.to_thread(llm.get_llm, "metric"))
            await asyncio.sleep(0)
            return llm.get_llm("enrich").model, (await task).model
        finally:
            llm.account_llm_config.reset(token)

    results = await asyncio.gather(request("account-one"), request("account-two"))
    assert results == [("account-one", "account-one"), ("account-two", "account-two")]
    assert llm.account_llm_config.get() is None


@pytest.mark.asyncio
async def test_dependency_keeps_config_during_stream_and_resets_it(async_session, monkeypatch):
    await save_llm_settings(async_session, 1, LLMSettingsRequest(provider="openai", model="stream-model", api_key="key"))
    probe = FastAPI(dependencies=[Depends(use_account_llm)])

    async def database():
        yield async_session

    probe.dependency_overrides[get_db_session] = database

    @probe.get("/stream")
    async def stream():
        async def chunks():
            await asyncio.sleep(0)
            yield json.dumps({"model": llm.get_llm("metric").model})

        return StreamingResponse(chunks())

    monkeypatch.setattr(llm, "_client_cache", {})
    monkeypatch.setitem(llm._CLIENT_BUILDERS, "openai", lambda config: SimpleNamespace(model=config.model))
    user = await async_session.get(UserModel, 1)
    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://test") as client:
        result = await client.get("/stream", headers={"Authorization": f"Bearer {create_access_token(user)}"})
    assert result.json() == {"model": "stream-model"}
    assert llm.account_llm_config.get() is None


@pytest.mark.asyncio
async def test_cron_uses_database_creator_settings_and_restores_context(async_session, monkeypatch):
    await save_llm_settings(async_session, 1, LLMSettingsRequest(provider="deepseek", model="owner-model", api_key="key"))
    row = SemanticDatabaseModel(created_by=1, display_name="Test", db_type="postgresql", conn_url_enc="encrypted")
    async_session.add(row)
    await async_session.commit()

    async def heal(*args, **kwargs):
        assert llm.account_llm_config.get().model == "owner-model"
        raise RuntimeError("sync failed")

    monkeypatch.setattr("src.services.schema_cron_service.execute_self_healing", AsyncMock(side_effect=heal))
    with pytest.raises(RuntimeError, match="sync failed"):
        await _sync_with_owner_llm(async_session, row.id)
    assert llm.account_llm_config.get() is None
