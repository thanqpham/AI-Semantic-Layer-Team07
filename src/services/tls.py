"""TLS validation, URL TLS-parameter stripping and SSL connect-args builders."""

import contextlib
import os
import ssl
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.engine import make_url

from src.models.tls_settings import TlsMode, TlsSettings
from src.services.database import decrypt_conn_url

if TYPE_CHECKING:
    from src.models.db import LiveTargetDbModel

_CA_REQUIRED_MODES = (TlsMode.VERIFY_CA, TlsMode.VERIFY_FULL)
_ENCRYPTED_KEY_MARKERS = ("ENCRYPTED PRIVATE KEY", "Proc-Type: 4,ENCRYPTED")


def validate_tls_settings(
    mode: str,
    ca_cert: str | None,
    client_cert: str | None,
    client_key: str | None,
) -> TlsSettings:
    """Validate a TLS configuration and return it as a TlsSettings model.

    Raises ValueError with a user-facing message on any invalid combination.
    """
    try:
        tls_mode = TlsMode(mode)
    except ValueError as exc:
        raise ValueError(f"Unsupported TLS mode: {mode}") from exc

    if tls_mode in _CA_REQUIRED_MODES and not ca_cert:
        raise ValueError("CA certificate is required for verify_ca/verify_full modes")

    if bool(client_cert) != bool(client_key):
        raise ValueError("client certificate and key must be provided together")

    if client_key and any(marker in client_key for marker in _ENCRYPTED_KEY_MARKERS):
        raise ValueError("client key must be an unencrypted PEM (remove the passphrase first)")

    return TlsSettings(
        mode=tls_mode,
        ca_cert=ca_cert,
        client_cert=client_cert,
        client_key=client_key,
    )


def strip_tls_url_params(conn_url: str) -> str:
    """Remove TLS-related query parameters (keys starting with "ssl") from a URL."""
    url = make_url(conn_url)
    cleaned = {k: v for k, v in url.query.items() if not k.lower().startswith("ssl")}
    return url.set(query=cleaned).render_as_string(hide_password=False)


_PG_MODES: dict[TlsMode, str] = {
    TlsMode.DISABLE: "disable",
    TlsMode.REQUIRE: "require",
    TlsMode.VERIFY_CA: "verify-ca",
    TlsMode.VERIFY_FULL: "verify-full",
}
_PG_SYNC_KEYS = ("sslrootcert", "sslcert", "sslkey")


def _noop() -> None:
    """Cleanup for builders that keep no temp files."""


def _write_temp_pem(pem: str) -> Path:
    """Write PEM content to a private temp .pem file and return its path."""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w", encoding="utf-8") as fh:
        fh.write(pem)
    path = Path(fh.name)
    with contextlib.suppress(OSError):  # best-effort hardening; chmod is limited on Windows
        os.chmod(path, 0o600)
    return path


def _cleanup_paths(*paths: Path) -> Callable[[], None]:
    """Return a callable that deletes the given temp paths when present."""

    def cleanup() -> None:
        for path in paths:
            path.unlink(missing_ok=True)

    return cleanup


def _dialect_family(dialect: str) -> Literal["postgresql", "mysql", "sqlite"]:
    """Map a SQLAlchemy dialect name to its TLS-args family."""
    backend = dialect.lower().split("+", 1)[0]
    if backend in ("postgresql", "postgres"):
        return "postgresql"
    if backend in ("mysql", "mariadb"):
        return "mysql"
    return "sqlite"


def _add_client_cert_files(
    settings: TlsSettings,
    args: dict[str, Any],
    cert_key: str,
    key_key: str,
) -> list[Path]:
    """Write client cert/key temp files into args and return their paths."""
    if not (settings.client_cert and settings.client_key):
        return []
    cert = _write_temp_pem(settings.client_cert)
    key = _write_temp_pem(settings.client_key)
    args[cert_key] = str(cert)
    args[key_key] = str(key)
    return [cert, key]


def _pg_sync_args(settings: TlsSettings) -> tuple[dict[str, Any], Callable[[], None]]:
    """Build sync connect_args (libpq sslmode plus temp PEM files) for PostgreSQL."""
    args: dict[str, Any] = {"sslmode": _PG_MODES[settings.mode]}
    paths: list[Path] = []
    if settings.mode in _CA_REQUIRED_MODES and settings.ca_cert:
        ca = _write_temp_pem(settings.ca_cert)
        paths.append(ca)
        args["sslrootcert"] = str(ca)
    paths += _add_client_cert_files(settings, args, "sslcert", "sslkey")
    return args, _cleanup_paths(*paths)


def _mysql_sync_args(settings: TlsSettings) -> tuple[dict[str, Any], Callable[[], None]]:
    """Build sync connect_args for MySQL/MariaDB (PyMySQL has no sslmode kwarg in 2.x)."""
    if settings.mode is TlsMode.DISABLE:
        return {"ssl_disabled": True}, _noop
    return {"ssl": _build_ssl_context(settings)}, _noop


def build_sync_ssl_args(
    settings: TlsSettings | None,
    dialect: str,
) -> tuple[dict[str, Any], Callable[[], None]]:
    """Build sync connect_args for TLS plus a cleanup callable for its temp files.

    Returns empty args and a no-op cleanup when TLS is not configured (no
    settings or prefer mode) or the target is sqlite (no TLS support).
    """
    family = _dialect_family(dialect)
    if settings is None or family == "sqlite" or settings.mode is TlsMode.PREFER:
        return {}, _noop
    if family == "mysql":
        return _mysql_sync_args(settings)
    return _pg_sync_args(settings)


def _build_ssl_context(settings: TlsSettings) -> ssl.SSLContext:
    """Build an SSLContext for async drivers; temp cert/key files are removed at once.

    verify_ca/verify_full pin the supplied CA and verify the server (hostname
    check only for verify_full).
    """
    ctx = ssl.create_default_context()
    ctx.check_hostname = settings.mode is TlsMode.VERIFY_FULL
    # require mode = encrypt without verifying the server; client cert still sent on request
    ctx.verify_mode = ssl.CERT_REQUIRED if settings.mode in _CA_REQUIRED_MODES else ssl.CERT_NONE
    # VERIFY_* without a CA is off the validated path (validate_tls_settings enforces one)
    if settings.mode in _CA_REQUIRED_MODES and settings.ca_cert:
        ctx.load_verify_locations(cadata=settings.ca_cert)
    if settings.client_cert and settings.client_key:
        cert = _write_temp_pem(settings.client_cert)
        key = _write_temp_pem(settings.client_key)
        try:
            ctx.load_cert_chain(str(cert), str(key))
        finally:
            cert.unlink(missing_ok=True)
            key.unlink(missing_ok=True)
    return ctx


def _async_pg_args(settings: TlsSettings) -> tuple[dict[str, Any], Callable[[], None]]:
    """Build asyncpg ssl connect_args for a PostgreSQL target."""
    if settings.mode is TlsMode.DISABLE:
        return {"ssl": "disable"}, _noop
    if settings.mode is TlsMode.REQUIRE and not settings.client_cert:
        return {"ssl": "require"}, _noop
    return {"ssl": _build_ssl_context(settings)}, _noop


def _async_mysql_args(settings: TlsSettings) -> tuple[dict[str, Any], Callable[[], None]]:
    """Build aiomysql/asyncmy ssl connect_args for a MySQL/MariaDB target."""
    if settings.mode is TlsMode.DISABLE:
        return {"ssl": None}, _noop
    return {"ssl": _build_ssl_context(settings)}, _noop


def build_async_ssl_args(
    settings: TlsSettings | None,
    dialect: str,
) -> tuple[dict[str, Any], Callable[[], None]]:
    """Build async-driver ssl connect_args; any temp file is deleted eagerly.

    Returns empty args and a no-op cleanup when TLS is not configured (no
    settings or prefer mode) or the target is sqlite (no TLS support).
    """
    family = _dialect_family(dialect)
    if settings is None or family == "sqlite" or settings.mode is TlsMode.PREFER:
        return {}, _noop
    if family == "mysql":
        return _async_mysql_args(settings)
    return _async_pg_args(settings)


def load_tls_settings(live_db: "LiveTargetDbModel") -> TlsSettings:
    """Load TLS settings from a persisted live-DB row.

    Always returns settings; the encrypted client key is decrypted to
    plaintext in RAM only and never persisted or logged.
    """
    return TlsSettings(
        # server_default only applies at DB level; Python-constructed rows may carry None
        mode=TlsMode(live_db.tls_mode or "prefer"),
        ca_cert=live_db.ca_cert,
        client_cert=live_db.client_cert,
        client_key=decrypt_conn_url(live_db.client_key_enc) if live_db.client_key_enc else None,
    )
