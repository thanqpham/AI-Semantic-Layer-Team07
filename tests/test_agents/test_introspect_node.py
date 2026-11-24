"""Unit tests for the Flow 1 introspection node."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.nodes.schema.introspect_node import introspect_node
from src.models.raw_schema import RawSchema
from src.services.introspection import InvalidCredentialError

RAW_SCHEMA: RawSchema = {
    "source": {
        "type": "live_connection",
        "db_engine": "sqlite",
        "connection_id": 1,
        "extracted_at": "2026-08-05T00:00:00Z",
    },
    "tables": [],
    "relationships": [],
}


async def _async_gen(val: object):
    """Yield a single value — helper for mocking get_db_session()."""
    yield val


def _patched_db(row: object) -> MagicMock:
    """Return a get_db_session mock whose session.scalar resolves to `row`."""
    session = AsyncMock()
    session.scalar.return_value = row
    return MagicMock(return_value=_async_gen(session))


@pytest.mark.asyncio
async def test_introspect_node_passes_persisted_connection_id() -> None:
    """Build the live request from typed graph state."""
    response = {"raw_schema": {**RAW_SCHEMA, "tables": [{"table_name": "orders"}]}, "warnings": ["partial"]}
    state = {"db_id": 9, "conn_url_enc": "ciphertext", "db_type": "sqlite"}
    with (
        patch("src.agents.nodes.schema.introspect_node.get_db_session", _patched_db(None)),
        patch(
            "src.agents.nodes.schema.introspect_node.extract_raw_schema",
            new_callable=AsyncMock,
            return_value=response,
        ) as extract,
    ):
        result = await introspect_node(state)
    request = {"conn_url_enc": "ciphertext", "db_type": "sqlite", "connection_id": 9, "tls": None}
    extract.assert_awaited_once_with(request)
    assert result["introspection_warnings"] == ["partial"]


@pytest.mark.asyncio
async def test_introspect_node_rejects_missing_connection_id() -> None:
    """Do not synthesize connection_id=0 when graph state is incomplete."""
    with patch(
        "src.agents.nodes.schema.introspect_node.extract_raw_schema",
        new_callable=AsyncMock,
    ) as extract:
        result = await introspect_node({"conn_url_enc": "ciphertext", "db_type": "sqlite"})
    extract.assert_not_awaited()
    assert result == {"error": "Database connection ID is required."}


@pytest.mark.asyncio
async def test_introspect_node_rejects_empty_table_list() -> None:
    """Stop the graph when live extraction finds no base tables."""
    response = {"raw_schema": RAW_SCHEMA, "warnings": []}
    with (
        patch("src.agents.nodes.schema.introspect_node.get_db_session", _patched_db(None)),
        patch(
            "src.agents.nodes.schema.introspect_node.extract_raw_schema",
            new_callable=AsyncMock,
            return_value=response,
        ),
    ):
        result = await introspect_node({"db_id": 1, "conn_url_enc": "ciphertext", "db_type": "sqlite"})
    assert result == {"error": "The target database does not contain any tables."}


@pytest.mark.asyncio
async def test_introspect_node_hides_plaintext_credentials() -> None:
    """Map internal failures without leaking their messages."""
    secret_url = "sqlite:///password-is-secret.db"
    with (
        patch("src.agents.nodes.schema.introspect_node.get_db_session", _patched_db(None)),
        patch(
            "src.agents.nodes.schema.introspect_node.extract_raw_schema",
            new_callable=AsyncMock,
            side_effect=InvalidCredentialError(secret_url),
        ),
    ):
        result = await introspect_node({"db_id": 1, "conn_url_enc": "ciphertext", "db_type": "sqlite"})
    assert result["error"] == "Invalid database credential."
    assert secret_url not in result["error"]


@pytest.mark.asyncio
async def test_introspect_node_injects_tls_from_row() -> None:
    """Attach the TLS settings persisted on the live-DB row to the extraction request."""
    row = SimpleNamespace(tls_mode="require", ca_cert=None, client_cert=None, client_key_enc=None)
    response = {"raw_schema": {**RAW_SCHEMA, "tables": [{"table_name": "orders"}]}, "warnings": []}
    with (
        patch("src.agents.nodes.schema.introspect_node.get_db_session", _patched_db(row)),
        patch(
            "src.agents.nodes.schema.introspect_node.extract_raw_schema",
            new_callable=AsyncMock,
            return_value=response,
        ) as extract,
    ):
        result = await introspect_node({"db_id": 9, "conn_url_enc": "ciphertext", "db_type": "postgresql"})
    req = extract.await_args.args[0]
    assert req["tls"] is not None
    assert req["tls"].mode.value == "require"
    assert result["raw_schema"]["tables"] == [{"table_name": "orders"}]


@pytest.mark.asyncio
async def test_introspect_node_without_row_tls_none() -> None:
    """Leave TLS unset when no live-DB row backs this run."""
    response = {"raw_schema": RAW_SCHEMA, "warnings": []}
    with (
        patch("src.agents.nodes.schema.introspect_node.get_db_session", _patched_db(None)),
        patch(
            "src.agents.nodes.schema.introspect_node.extract_raw_schema",
            new_callable=AsyncMock,
            return_value=response,
        ) as extract,
    ):
        result = await introspect_node({"db_id": 9, "conn_url_enc": "ciphertext", "db_type": "sqlite"})
    req = extract.await_args.args[0]
    assert req.get("tls") is None
    assert result == {"error": "The target database does not contain any tables."}


@pytest.mark.asyncio
async def test_introspect_node_degrades_when_metadata_db_fails() -> None:
    """Metadata-DB failure must degrade to no TLS, not crash the Flow 1 run."""
    session = AsyncMock()
    session.scalar.side_effect = RuntimeError("metadata database is down")
    response = {"raw_schema": {**RAW_SCHEMA, "tables": [{"table_name": "orders"}]}, "warnings": []}
    with (
        patch("src.agents.nodes.schema.introspect_node.get_db_session", MagicMock(return_value=_async_gen(session))),
        patch(
            "src.agents.nodes.schema.introspect_node.extract_raw_schema",
            new_callable=AsyncMock,
            return_value=response,
        ) as extract,
    ):
        result = await introspect_node({"db_id": 9, "conn_url_enc": "ciphertext", "db_type": "sqlite"})
    req = extract.await_args.args[0]
    assert req.get("tls") is None
    assert result["raw_schema"]["tables"] == [{"table_name": "orders"}]
