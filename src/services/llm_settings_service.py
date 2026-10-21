"""Persist encrypted account credentials and resolve request-scoped LLM clients."""

import json

from cryptography.fernet import InvalidToken
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.llm_settings import LLMKeyRequest, LLMSettingsRequest, LLMSettingsResponse, UserLLMSettingsModel
from src.services.database import decrypt_conn_url, encrypt_conn_url
from src.services.llm import LLMConfig, _resolve_model, _resolve_provider
from src.services.llm_providers import PROVIDERS


def _credentials(row: UserLLMSettingsModel | None) -> dict[str, dict[str, str]]:
    if row is None:
        return {}
    try:
        return json.loads(decrypt_conn_url(row.credentials_enc))
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Cannot decrypt saved AI credentials. Check the server ENCRYPTION_KEY.") from exc


async def read_llm_settings(db: AsyncSession, user_id: int) -> LLMSettingsResponse:
    """Return public account settings, falling back to environment metadata."""
    row = await db.get(UserLLMSettingsModel, user_id)
    credentials = _credentials(row)
    settings = get_settings()
    provider = row.provider if row else _resolve_provider(settings)
    return LLMSettingsResponse(
        provider=provider,
        model=credentials[provider]["model"] if row else _resolve_model(settings, provider),
        source="account" if row else "environment",
        saved_models={name: values["model"] for name, values in credentials.items()},
        providers=[{"id": name, "name": values[0]} for name, values in PROVIDERS.items()],
    )


async def save_llm_settings(db: AsyncSession, user_id: int, body: LLMSettingsRequest) -> LLMSettingsResponse:
    """Save a provider selection and remember keys when switching providers."""
    row = await db.get(UserLLMSettingsModel, user_id, with_for_update=True)
    credentials = _credentials(row)
    key = body.api_key.get_secret_value() if body.api_key else credentials.get(body.provider, {}).get("api_key", "")
    if not key:
        raise ValueError("Enter an API key for this provider before saving.")
    credentials[body.provider] = {"api_key": key, "model": body.model}
    encrypted = encrypt_conn_url(json.dumps(credentials))
    if row is None:
        row = UserLLMSettingsModel(user_id=user_id, provider=body.provider, credentials_enc=encrypted)
        db.add(row)
    else:
        row.provider, row.credentials_enc = body.provider, encrypted
    await db.commit()
    return await read_llm_settings(db, user_id)


async def load_account_llm_config(db: AsyncSession, user_id: int) -> LLMConfig | None:
    """Resolve an account override using only official provider endpoints."""
    row = await db.get(UserLLMSettingsModel, user_id)
    if row is None:
        return None
    saved = _credentials(row)[row.provider]
    _, base_url, protocol = PROVIDERS[row.provider]
    return LLMConfig(row.provider, protocol, saved["api_key"], base_url, saved["model"], 0.0)


async def list_provider_models(db: AsyncSession, user_id: int, body: LLMKeyRequest) -> list[str]:
    """List provider models with a supplied or saved key, without generating text."""
    row = await db.get(UserLLMSettingsModel, user_id)
    saved = _credentials(row).get(body.provider, {})
    key = body.api_key.get_secret_value() if body.api_key else saved.get("api_key", "")
    if not key:
        raise ValueError("Enter an API key for this provider to load models.")
    _, base_url, protocol = PROVIDERS[body.provider]
    try:
        if protocol == "anthropic":
            from anthropic import AsyncAnthropic

            async with AsyncAnthropic(api_key=key, base_url=base_url, timeout=15.0, max_retries=0) as client:
                return sorted({model.id async for model in client.models.list()})
        async with AsyncOpenAI(api_key=key, base_url=base_url, timeout=15.0, max_retries=0) as client:
            return sorted({model.id async for model in client.models.list()})
    except Exception as exc:
        raise RuntimeError("Could not load provider models.") from exc
