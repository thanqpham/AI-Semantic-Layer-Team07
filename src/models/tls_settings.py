"""TLS mode enum and settings model for database connections."""

from enum import Enum

from pydantic import BaseModel


class TlsMode(str, Enum):  # noqa: UP042 — brief pins (str, Enum); StrEnum changes str() behavior
    """Supported TLS modes for target database connections."""

    PREFER = "prefer"
    DISABLE = "disable"
    REQUIRE = "require"
    VERIFY_CA = "verify_ca"
    VERIFY_FULL = "verify_full"


class TlsSettings(BaseModel):
    """TLS configuration attached to a database connection."""

    mode: TlsMode
    ca_cert: str | None = None
    client_cert: str | None = None
    client_key: str | None = None
