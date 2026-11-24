import asyncio
import pathlib
import ssl
import tempfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from src.models.tls_settings import TlsMode, TlsSettings
from src.services.query_execution import execute_compiled_query
from src.services.tls import (
    build_async_ssl_args,
    build_sync_ssl_args,
    load_tls_settings,
    strip_tls_url_params,
    validate_tls_settings,
)


class TestValidateTlsSettings:
    def test_prefer_defaults_ok(self):
        s = validate_tls_settings("prefer", None, None, None)
        assert s.mode is TlsMode.PREFER and s.ca_cert is None

    def test_unknown_mode_raises(self):
        with pytest.raises(ValueError, match="Unsupported TLS mode"):
            validate_tls_settings("bogus", None, None, None)

    def test_verify_full_without_ca_raises(self):
        with pytest.raises(ValueError, match="CA certificate is required"):
            validate_tls_settings("verify_full", None, None, None)

    def test_verify_ca_with_ca_ok(self):
        s = validate_tls_settings("verify_ca", "-----BEGIN CERTIFICATE-----", None, None)
        assert s.mode is TlsMode.VERIFY_CA and s.ca_cert == "-----BEGIN CERTIFICATE-----"

    def test_client_cert_without_key_raises(self):
        with pytest.raises(ValueError, match="client certificate and key"):
            validate_tls_settings("prefer", None, "-----BEGIN CERTIFICATE-----", None)

    def test_client_key_without_cert_raises(self):
        with pytest.raises(ValueError, match="client certificate and key"):
            validate_tls_settings("prefer", None, None, "-----BEGIN PRIVATE KEY-----")

    def test_encrypted_client_key_raises(self):
        with pytest.raises(ValueError, match="unencrypted"):
            validate_tls_settings(
                "prefer",
                None,
                "-----BEGIN CERTIFICATE-----",
                "-----BEGIN ENCRYPTED PRIVATE KEY-----",
            )


class TestStripTlsUrlParams:
    def test_strips_sslmode_and_keeps_rest(self):
        url = "postgresql://u:p%40ss@h:5432/db?sslmode=require&sslrootcert=x&application_name=app"
        out = strip_tls_url_params(url)
        assert "sslmode" not in out and "sslrootcert" not in out and "application_name=app" in out

    def test_plain_url_unchanged(self):
        url = "postgresql://u:p%40ss@h:5432/db"
        assert strip_tls_url_params(url) == url

    def test_mysql_ssl_params_stripped(self):
        out = strip_tls_url_params("mysql://u:p@h/db?ssl_ca=c.pem&charset=utf8")
        assert "ssl_ca" not in out and "charset=utf8" in out

    def test_password_preserved(self):
        out = strip_tls_url_params("postgresql://u:p%40ss@h:5432/db?sslmode=require")
        assert "p%40ss" in out


def _generate_test_pems() -> tuple[str, str, str]:
    """Build (ca_pem, cert_pem, key_pem) from one self-signed certificate."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "tls-test.local")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    return cert_pem, cert_pem, key_pem


CA, CERT, KEY = _generate_test_pems()


class TestBuildSyncSslArgs:
    def test_none_and_prefer_and_sqlite_noop(self):
        for settings, dialect in [
            (None, "postgresql"),
            (TlsSettings(mode=TlsMode.PREFER), "postgresql"),
            (TlsSettings(mode=TlsMode.VERIFY_FULL, ca_cert=CA), "sqlite"),
        ]:
            args, cleanup = build_sync_ssl_args(settings, dialect)
            assert args == {} and cleanup() is None

    def test_require_map(self):
        args, _ = build_sync_ssl_args(TlsSettings(mode=TlsMode.REQUIRE), "postgresql")
        assert args == {"sslmode": "require"}

    def test_disable_map(self):
        args, _ = build_sync_ssl_args(TlsSettings(mode=TlsMode.DISABLE), "postgresql")
        assert args == {"sslmode": "disable"}

    def test_verify_full_with_ca_and_client_cert(self):
        s = TlsSettings(mode=TlsMode.VERIFY_FULL, ca_cert=CA, client_cert=CERT, client_key=KEY)
        args, cleanup = build_sync_ssl_args(s, "postgresql")
        assert args["sslmode"] == "verify-full"
        assert args["sslrootcert"].endswith(".pem")
        assert args["sslcert"].endswith(".pem") and args["sslkey"].endswith(".pem")
        cleanup()  # xóa sạch temp file
        import pathlib

        for k in ("sslrootcert", "sslcert", "sslkey"):
            assert not pathlib.Path(args[k]).exists()

    def test_mysql_mode_map(self):
        # PyMySQL không có kwarg sslmode (2.x signature tường minh) → dùng ssl_disabled / SSLContext
        args, cleanup = build_sync_ssl_args(TlsSettings(mode=TlsMode.DISABLE), "mysql")
        assert args == {"ssl_disabled": True} and cleanup() is None
        args, _ = build_sync_ssl_args(TlsSettings(mode=TlsMode.REQUIRE), "mysql")
        ctx = args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False

    def test_mysql_verify_modes(self):
        args, _ = build_sync_ssl_args(TlsSettings(mode=TlsMode.VERIFY_CA, ca_cert=CA), "mysql")
        assert args["ssl"].verify_mode == ssl.CERT_REQUIRED and args["ssl"].check_hostname is False
        args, _ = build_sync_ssl_args(TlsSettings(mode=TlsMode.VERIFY_FULL, ca_cert=CA), "mysql")
        assert args["ssl"].verify_mode == ssl.CERT_REQUIRED and args["ssl"].check_hostname is True


class TestBuildAsyncSslArgs:
    def test_require_string(self):
        args, cleanup = build_async_ssl_args(TlsSettings(mode=TlsMode.REQUIRE), "postgresql")
        assert args == {"ssl": "require"} and cleanup() is None

    def test_verify_full_context(self):
        import ssl

        s = TlsSettings(mode=TlsMode.VERIFY_FULL, ca_cert=CA, client_cert=CERT, client_key=KEY)
        args, _ = build_async_ssl_args(s, "postgresql")
        ctx = args["ssl"]
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.check_hostname is True and ctx.verify_mode == ssl.CERT_REQUIRED

    def test_verify_ca_hostname_off(self):
        s = TlsSettings(mode=TlsMode.VERIFY_CA, ca_cert=CA)
        args, _ = build_async_ssl_args(s, "postgresql")
        assert args["ssl"].check_hostname is False
        assert args["ssl"].verify_mode == ssl.CERT_REQUIRED

    def test_client_key_tempfile_deleted_immediately(self):
        before = set(pathlib.Path(tempfile.gettempdir()).glob("*.pem"))
        s = TlsSettings(mode=TlsMode.REQUIRE, client_cert=CERT, client_key=KEY)
        args, _ = build_async_ssl_args(s, "postgresql")
        assert isinstance(args["ssl"], ssl.SSLContext)
        # builder xóa temp file ngay sau load_cert_chain — không còn file key nào sót
        after = set(pathlib.Path(tempfile.gettempdir()).glob("*.pem"))
        assert before == after


class TestLoadTlsSettings:
    def test_prefer_row(self):
        row = SimpleNamespace(tls_mode="prefer", ca_cert=None, client_cert=None, client_key_enc=None)
        s = load_tls_settings(row)  # type: ignore[arg-type]
        assert s.mode is TlsMode.PREFER and s.ca_cert is None

    def test_none_tls_mode_defaults_to_prefer(self):
        row = SimpleNamespace(tls_mode=None, ca_cert=None, client_cert=None, client_key_enc=None)
        s = load_tls_settings(row)  # type: ignore[arg-type]
        assert s.mode is TlsMode.PREFER

    def test_decrypts_client_key(self, monkeypatch):
        monkeypatch.setattr("src.services.tls.decrypt_conn_url", lambda enc: "PLAIN-KEY")
        row = SimpleNamespace(tls_mode="verify_ca", ca_cert=CA, client_cert=CERT, client_key_enc="ENC")
        s = load_tls_settings(row)  # type: ignore[arg-type]
        assert s.client_key == "PLAIN-KEY" and s.ca_cert == CA


def _patch_sync_engine(monkeypatch, module: str) -> dict:
    """Patch create_engine + inspect trong module; trả về dict ghi nhận engine kwargs."""
    captured: dict = {}
    inspector = SimpleNamespace(get_table_names=lambda: [])

    class FakeEngine:
        def __enter__(self) -> "FakeEngine":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def connect(self) -> "FakeEngine":
            return self

        def dispose(self) -> None:
            pass

    def fake_create_engine(url: str, **kw: object) -> FakeEngine:
        captured.update(kw)
        return FakeEngine()

    monkeypatch.setattr(f"{module}.create_engine", fake_create_engine)
    monkeypatch.setattr(f"{module}.inspect", lambda conn: inspector)
    return captured


class TestSyncSiteWiring:
    # introspect_live_database / fast_introspect_schema_fingerprint dùng engine.connect()
    # + inspect(); inspector.get_table_names()=[] → schema 0 bảng vẫn hợp lệ
    def test_introspect_passes_connect_args(self, monkeypatch):
        captured = _patch_sync_engine(monkeypatch, "src.services.live_db_service")
        from src.services.live_db_service import introspect_live_database

        introspect_live_database("postgresql://u:p@h/db", "postgresql", tls=TlsSettings(mode=TlsMode.REQUIRE))
        assert captured["connect_args"] == {"sslmode": "require"}

    def test_introspect_default_none_no_connect_args(self, monkeypatch):
        captured = _patch_sync_engine(monkeypatch, "src.services.live_db_service")
        from src.services.live_db_service import introspect_live_database

        introspect_live_database("postgresql://u:p@h/db", "postgresql", tls=None)
        assert captured["connect_args"] == {}

    def test_fingerprint_passes_connect_args(self, monkeypatch):
        captured = _patch_sync_engine(monkeypatch, "src.services.schema_fingerprint")
        from src.services.schema_fingerprint import fast_introspect_schema_fingerprint

        fast_introspect_schema_fingerprint("postgresql://u:p@h/db", "postgresql", tls=TlsSettings(mode=TlsMode.REQUIRE))
        assert captured["connect_args"] == {"sslmode": "require"}

    def test_fingerprint_no_tls_no_connect_args(self, monkeypatch):
        captured = _patch_sync_engine(monkeypatch, "src.services.schema_fingerprint")
        from src.services.schema_fingerprint import fast_introspect_schema_fingerprint

        fast_introspect_schema_fingerprint("postgresql://u:p@h/db", "postgresql", tls=None)
        assert captured["connect_args"] == {}


def _patch_async_engine(monkeypatch, module: str) -> dict:
    """Patch create_async_engine trong module; connection.run_sync trả về []."""
    captured: dict = {}
    connection = SimpleNamespace(run_sync=AsyncMock(return_value=[]))

    class FakeEngine:
        def connect(self):
            return self

        async def __aenter__(self):
            return connection

        async def __aexit__(self, *args):
            return None

        async def dispose(self):
            pass

    def fake_create_async_engine(url, **kw):
        captured.update(kw)
        return FakeEngine()

    monkeypatch.setattr(f"{module}.create_async_engine", fake_create_async_engine)
    return captured


class TestAttachUniqueKeysSiteWiring:
    async def _run(self, monkeypatch, tls_mode: str) -> dict:
        captured = _patch_async_engine(monkeypatch, "src.services.relationship_unique_evidence")
        row = SimpleNamespace(
            tls_mode=tls_mode,
            ca_cert=None,
            client_cert=None,
            client_key_enc=None,
            conn_url_enc="ENC",
            dialect="postgresql",
        )

        class FakeDb:
            async def scalar(self, stmt):
                return row

        monkeypatch.setattr(
            "src.services.relationship_unique_evidence.decrypt_conn_url", lambda enc: "postgresql://u:p@h/db"
        )
        from src.services.relationship_unique_evidence import attach_unique_keys

        await attach_unique_keys(FakeDb(), 1, [])  # type: ignore[arg-type]
        return captured

    async def test_require_tls_connect_args(self, monkeypatch):
        captured = await self._run(monkeypatch, "require")
        assert captured["connect_args"] == {"ssl": "require"}

    async def test_prefer_tls_no_connect_args(self, monkeypatch):
        captured = await self._run(monkeypatch, "prefer")
        assert captured["connect_args"] == {}


class TestExtractLiveSchemaSiteWiring:
    def _request(self, tls: TlsSettings | None) -> dict:
        return {"conn_url_enc": "ENC", "db_type": "postgresql", "connection_id": 1, "tls": tls}

    async def test_require_tls_connect_args(self, monkeypatch):
        captured = _patch_async_engine(monkeypatch, "src.services.introspection")
        monkeypatch.setattr("src.services.introspection._decrypt_url", lambda enc: "postgresql://u:p@h/db")
        from src.services.introspection import _extract_live_schema

        await _extract_live_schema(self._request(TlsSettings(mode=TlsMode.REQUIRE)))  # type: ignore[arg-type]
        assert captured["connect_args"] == {"ssl": "require"}

    async def test_no_tls_no_connect_args(self, monkeypatch):
        captured = _patch_async_engine(monkeypatch, "src.services.introspection")
        monkeypatch.setattr("src.services.introspection._decrypt_url", lambda enc: "postgresql://u:p@h/db")
        from src.services.introspection import _extract_live_schema

        await _extract_live_schema(self._request(None))  # type: ignore[arg-type]
        assert captured["connect_args"] == {}


def _patch_query_engine(monkeypatch) -> dict:
    """Patch create_async_engine + validate_read_only; return captured engine kwargs."""
    captured: dict = {}
    transaction = AsyncMock()
    result = SimpleNamespace(fetchall=lambda: [], keys=lambda: [])
    connection = AsyncMock()
    connection.begin.return_value = transaction
    connection.execute.return_value = result

    class FakeEngine:
        async def __aenter__(self):
            return connection

        async def __aexit__(self, *args):
            return None

        def connect(self):
            return self

        async def dispose(self):
            pass

    def fake_create_async_engine(url, **kw):
        captured.update(kw)
        return FakeEngine()

    monkeypatch.setattr("src.services.query_execution.create_async_engine", fake_create_async_engine)
    monkeypatch.setattr("src.services.query_execution.validate_read_only", lambda *a, **k: None)
    return captured


class TestAsyncSiteWiring:
    def test_execute_compiled_query_passes_ssl_args(self, monkeypatch):
        captured = _patch_query_engine(monkeypatch)
        compiled = SimpleNamespace(sql="SELECT 1", parameters={})
        asyncio.run(
            execute_compiled_query(
                "postgresql://u:p@h/db", "postgresql", compiled, tls=TlsSettings(mode=TlsMode.REQUIRE)
            )
        )
        assert captured["connect_args"] == {"ssl": "require"}

    def test_execute_compiled_query_no_tls_no_connect_args(self, monkeypatch):
        captured = _patch_query_engine(monkeypatch)
        compiled = SimpleNamespace(sql="SELECT 1", parameters={})
        asyncio.run(execute_compiled_query("postgresql://u:p@h/db", "postgresql", compiled))
        assert captured["connect_args"] == {}
