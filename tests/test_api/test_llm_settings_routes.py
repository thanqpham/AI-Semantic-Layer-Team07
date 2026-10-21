"""Account AI settings persist encrypted keys without exposing them over HTTP."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.api.auth import create_access_token
from src.models.db import UserModel
from src.models.llm_settings import UserLLMSettingsModel
from src.services import llm_settings_service as service
from src.services.database import decrypt_conn_url


async def _headers(session, user_id=1):
    user = await session.get(UserModel, user_id)
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [("get", ""), ("put", ""), ("post", "/models")])
async def test_requires_authentication(client, method, path):
    response = await getattr(client, method)(f"/api/v1/settings/llm{path}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_encrypts_key_and_remembers_models_when_switching(client, async_session):
    headers = await _headers(async_session)
    path = "/api/v1/settings/llm"
    body = {"provider": "openrouter", "model": "vendor/model", "api_key": "sk-private-router"}
    saved = await client.put(path, headers=headers, json=body)
    assert saved.status_code == 200
    row = await async_session.get(UserLLMSettingsModel, 1)
    assert body["api_key"] not in row.credentials_enc
    assert json.loads(decrypt_conn_url(row.credentials_enc))["openrouter"]["api_key"] == body["api_key"]
    assert body["api_key"] not in saved.text
    assert "api_key" not in saved.text

    switched = await client.put(path, headers=headers, json={"provider": "deepseek", "model": "deepseek-chat"})
    assert switched.status_code == 400
    assert row.provider == "openrouter"
    switched = await client.put(path, headers=headers, json={
        "provider": "deepseek", "model": "deepseek-chat", "api_key": "sk-private-deepseek",
    })
    assert switched.status_code == 200
    restored = await client.put(path, headers=headers, json={"provider": "openrouter", "model": "vendor/new-model"})
    assert restored.status_code == 200
    assert restored.json()["saved_models"] == {"openrouter": "vendor/new-model", "deepseek": "deepseek-chat"}
    async_session.expire_all()
    loaded = await client.get(path, headers=headers)
    assert loaded.json() == restored.json()
    config = await service.load_account_llm_config(async_session, 1)
    assert config.api_key == body["api_key"]
    assert config.model == "vendor/new-model"
    assert config.base_url == "https://openrouter.ai/api/v1"


@pytest.mark.asyncio
async def test_settings_are_isolated_by_account(client, async_session):
    async_session.add(UserModel(id=2, email="other@test.com", username="other", hashed_password="hash"))
    await async_session.commit()
    first = await _headers(async_session)
    second = await _headers(async_session, 2)
    path = "/api/v1/settings/llm"
    await client.put(path, headers=first, json={"provider": "openai", "model": "model-one", "api_key": "key-one"})
    other = await client.get(path, headers=second)
    assert other.json()["source"] == "environment"
    assert other.json()["saved_models"] == {}
    assert await service.load_account_llm_config(async_session, 2) is None
    no_key = await client.put(path, headers=second, json={"provider": "openai", "model": "model-two"})
    assert no_key.status_code == 400
    await client.put(path, headers=second, json={"provider": "anthropic", "model": "model-two", "api_key": "key-two"})
    assert (await service.load_account_llm_config(async_session, 1)).model == "model-one"
    assert (await service.load_account_llm_config(async_session, 2)).protocol == "anthropic"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openrouter", "gemini", "openai", "anthropic", "deepseek"])
async def test_all_requested_providers_resolve_to_official_endpoints(client, async_session, provider):
    saved = await client.put("/api/v1/settings/llm", headers=await _headers(async_session), json={
        "provider": provider, "model": "chosen-model", "api_key": "chosen-key",
    })
    assert saved.status_code == 200
    config = await service.load_account_llm_config(async_session, 1)
    assert config.provider == provider
    assert config.base_url == service.PROVIDERS[provider][1]
    assert config.model == "chosen-model"
    assert config.temperature == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [
    {"provider": "custom"}, {"model": " "}, {"model": ""},
    {"api_key": "private\nkey"}, {"api_key": "private" * 600},
    {"base_url": "https://untrusted.example"},
])
async def test_rejects_invalid_input_without_echoing_key(client, async_session, override):
    body = {"provider": "openai", "model": "test-model", "api_key": "private-key", **override}
    response = await client.put("/api/v1/settings/llm", headers=await _headers(async_session), json=body)
    assert response.status_code == 422
    assert "private" not in response.text
    assert await async_session.get(UserLLMSettingsModel, 1) is None


class ModelClient:
    def __init__(self):
        self.models = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def list(self):
        for name in ("model-b", "model-a", "model-b"):
            yield SimpleNamespace(id=name)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openrouter", "gemini", "openai", "anthropic", "deepseek"])
async def test_loads_models_with_provider_specific_protocol(client, async_session, monkeypatch, provider):
    factory = Mock(return_value=ModelClient())
    target = "anthropic.AsyncAnthropic" if provider == "anthropic" else "src.services.llm_settings_service.AsyncOpenAI"
    monkeypatch.setattr(target, factory)
    response = await client.post("/api/v1/settings/llm/models", headers=await _headers(async_session), json={
        "provider": provider, "api_key": "private-new-key",
    })
    assert response.status_code == 200
    assert response.json() == ["model-a", "model-b"]
    assert factory.call_args.kwargs["api_key"] == "private-new-key"
    assert factory.call_args.kwargs["base_url"] == service.PROVIDERS[provider][1]
    assert await async_session.get(UserLLMSettingsModel, 1) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_load_models_reuses_saved_key_and_hides_provider_errors(client, async_session, monkeypatch, error_type):
    headers = await _headers(async_session)
    await client.put("/api/v1/settings/llm", headers=headers, json={
        "provider": "openai", "model": "model-one", "api_key": "private-saved-key",
    })
    factory = Mock(return_value=ModelClient())
    monkeypatch.setattr(service, "AsyncOpenAI", factory)
    loaded = await client.post("/api/v1/settings/llm/models", headers=headers, json={"provider": "openai"})
    assert loaded.status_code == 200
    assert factory.call_args.kwargs["api_key"] == "private-saved-key"
    factory.side_effect = error_type("upstream leaked private-saved-key")
    failed = await client.post("/api/v1/settings/llm/models", headers=headers, json={"provider": "openai"})
    assert failed.status_code == 502
    assert "private-saved-key" not in failed.text


@pytest.mark.asyncio
async def test_replaces_key_and_reports_unreadable_credentials_without_overwriting(client, async_session, monkeypatch):
    from cryptography.fernet import InvalidToken

    headers = await _headers(async_session)
    body = {"provider": "openai", "model": "model-one", "api_key": "original-key"}
    assert (await client.put("/api/v1/settings/llm", headers=headers, json=body)).status_code == 200
    body["api_key"] = "replacement-key"
    assert (await client.put("/api/v1/settings/llm", headers=headers, json=body)).status_code == 200
    assert (await service.load_account_llm_config(async_session, 1)).api_key == "replacement-key"
    encrypted = (await async_session.get(UserLLMSettingsModel, 1)).credentials_enc
    monkeypatch.setattr(service, "decrypt_conn_url", Mock(side_effect=InvalidToken))
    unreadable = await client.get("/api/v1/settings/llm", headers=headers)
    assert unreadable.status_code == 503
    assert "replacement-key" not in unreadable.text
    failed = await client.put("/api/v1/settings/llm", headers=headers, json=body)
    assert failed.status_code == 400
    assert (await async_session.get(UserLLMSettingsModel, 1)).credentials_enc == encrypted
