"""Encrypted account LLM preferences and public settings contracts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.db_base import Base

Provider = Literal["openrouter", "gemini", "openai", "anthropic", "deepseek", "groq", "mimo"]


class UserLLMSettingsModel(Base):
    """Keep provider credentials encrypted and isolated by account."""

    __tablename__ = "user_llm_settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    credentials_enc: Mapped[str] = mapped_column(Text, nullable=False)


class LLMKeyRequest(BaseModel):
    """Use a supplied key or reuse the account's saved provider key."""

    model_config = ConfigDict(extra="forbid")
    provider: Provider
    api_key: SecretStr | None = Field(default=None, max_length=4096)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        """Reject control characters without echoing credentials in errors."""
        if value is None:
            return None
        key = value.get_secret_value().strip()
        if any(ord(char) < 32 or ord(char) == 127 for char in key):
            raise ValueError("API key contains invalid characters")
        return SecretStr(key) if key else None


class LLMSettingsRequest(LLMKeyRequest):
    """Select a provider and model for all account AI requests."""

    model: str = Field(min_length=1, max_length=200, pattern=r"^\S+$")


class LLMProviderResponse(BaseModel):
    """Describe a supported provider without exposing credentials."""

    id: str
    name: str


class LLMSettingsResponse(BaseModel):
    """Expose active settings and remembered models, never API keys."""

    provider: str
    model: str
    source: Literal["account", "environment"]
    saved_models: dict[str, str]
    providers: list[LLMProviderResponse]
