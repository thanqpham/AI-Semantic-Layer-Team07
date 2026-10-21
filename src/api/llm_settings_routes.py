"""Authenticated account AI settings and request context."""

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.auth import get_current_user
from src.models.db import UserModel
from src.models.llm_settings import LLMKeyRequest, LLMSettingsRequest, LLMSettingsResponse
from src.services.database import get_db_session
from src.services.llm import account_llm_config
from src.services.llm_settings_service import (
    list_provider_models,
    load_account_llm_config,
    read_llm_settings,
    save_llm_settings,
)

router = APIRouter(prefix="/settings/llm", tags=["AI Settings"])


async def use_account_llm(
    user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)
) -> AsyncIterator[None]:
    """Bind account settings through streaming and inherited background tasks."""
    try:
        config = await load_account_llm_config(db, user.id)
    except ValueError as exc:
        raise HTTPException(503, detail=str(exc)) from exc
    token = account_llm_config.set(config)
    try:
        yield
    finally:
        account_llm_config.reset(token)


@router.get("", response_model=LLMSettingsResponse)
async def get_ai_settings(
    user: UserModel = Depends(get_current_user), db: AsyncSession = Depends(get_db_session)
) -> LLMSettingsResponse:
    """Read the signed-in account's settings without returning API keys."""
    try:
        return await read_llm_settings(db, user.id)
    except ValueError as exc:
        raise HTTPException(503, detail=str(exc)) from exc


@router.put("", response_model=LLMSettingsResponse)
async def update_ai_settings(
    body: LLMSettingsRequest,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> LLMSettingsResponse:
    """Save encrypted credentials and activate a provider for the account."""
    try:
        return await save_llm_settings(db, user.id, body)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/models", response_model=list[str])
async def get_ai_models(
    body: LLMKeyRequest,
    user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> list[str]:
    """Fetch current model IDs without exposing provider errors or credentials."""
    try:
        return await list_provider_models(db, user.id, body)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, detail="Could not load models. Check your API key and provider availability.") from exc
