"""Least-privilege checks for target database accounts (catalog metadata only, never row data)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from src.config import get_settings
from src.models.schema_metadata import SchemaDialect
from src.models.tls_settings import TlsSettings
from src.services.tls import build_async_ssl_args

logger = logging.getLogger(__name__)

READ_ONLY_SETUP_HINT = (
    "Hãy tạo tài khoản chỉ đọc. PostgreSQL: CREATE ROLE semantic_reader LOGIN PASSWORD '...'; "
    "GRANT CONNECT ON DATABASE <db> TO semantic_reader; GRANT USAGE ON SCHEMA public TO semantic_reader; "
    "GRANT SELECT ON ALL TABLES IN SCHEMA public TO semantic_reader. "
    "MySQL: CREATE USER 'semantic_reader'@'%' IDENTIFIED BY '...'; "
    "GRANT SELECT, SHOW VIEW ON <db>.* TO 'semantic_reader'@'%'."
)

_PG_ROLE_SQL = "SELECT rolsuper, rolcreaterole, rolcreatedb, rolbypassrls FROM pg_roles WHERE rolname = current_user"
_PG_WRITABLE_TABLES_SQL = r"""
SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind IN ('r', 'p', 'v', 'm', 'f')
  AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\_%'
  AND (pg_has_role(c.relowner, 'USAGE')
       OR has_table_privilege(c.oid, 'INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER'))
ORDER BY 1 LIMIT 10
"""
_PG_CREATE_SCHEMAS_SQL = r"""
SELECT n.nspname FROM pg_namespace n
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname NOT LIKE 'pg\_%'
  AND has_schema_privilege(n.oid, 'CREATE')
ORDER BY 1
"""
_ASYNC_DRIVERS = {SchemaDialect.POSTGRESQL: "postgresql+asyncpg", SchemaDialect.MYSQL: "mysql+asyncmy"}
_MYSQL_READ_PRIVILEGES = {"SELECT", "SHOW VIEW", "USAGE", "SHOW DATABASES"}
_MYSQL_GRANT_RE = re.compile(r"^GRANT (?P<privs>.+?) ON .+? TO ", re.IGNORECASE)


@dataclass
class PrivilegeReport:
    """Write-capable privileges (violations) and softer risks (warnings) of one account."""

    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class WritablePrivilegeError(ValueError):
    """Raised when a target database account can modify data."""


def read_only_connect_args(conn_url: str | URL) -> dict[str, Any]:
    """Return driver options that make every PostgreSQL transaction read-only at session level."""
    driver = make_url(conn_url).drivername
    if driver == "postgresql+asyncpg":
        return {"server_settings": {"default_transaction_read_only": "on"}}
    if driver in {"postgresql", "postgresql+psycopg2", "postgresql+psycopg"}:
        return {"options": "-c default_transaction_read_only=on"}
    return {}


async def ensure_read_only_account(
    conn_url: str, dialect: SchemaDialect, tls: TlsSettings | None = None
) -> PrivilegeReport:
    """Reject write-capable accounts unless TARGET_DB_REQUIRE_READ_ONLY is disabled."""
    report = await check_read_only_privileges(conn_url, dialect, tls)
    for warning in report.warnings:
        logger.warning("Target DB privilege warning: %s", warning)
    if report.violations and get_settings().target_db_require_read_only:
        detail = "; ".join(report.violations)
        raise WritablePrivilegeError(f"Tài khoản database có quyền ghi/sửa dữ liệu: {detail}. {READ_ONLY_SETUP_HINT}")
    return report


async def check_read_only_privileges(
    conn_url: str, dialect: SchemaDialect, tls: TlsSettings | None = None
) -> PrivilegeReport:
    """Inspect the account's privileges; SQLite has no accounts and returns an empty report."""
    if dialect == SchemaDialect.SQLITE:
        return PrivilegeReport()
    url = make_url(conn_url).set(drivername=_ASYNC_DRIVERS[dialect])
    ssl_args, _ = build_async_ssl_args(tls, str(dialect))
    engine = create_async_engine(url, connect_args={**read_only_connect_args(url), **ssl_args})
    try:
        async with engine.connect() as connection:
            if dialect == SchemaDialect.POSTGRESQL:
                return await _postgres_report(connection)
            rows = (await connection.execute(text("SHOW GRANTS FOR CURRENT_USER()"))).scalars().all()
            return mysql_report_from_grants(list(rows))
    finally:
        await engine.dispose()


async def _postgres_report(connection: AsyncConnection) -> PrivilegeReport:
    report = PrivilegeReport()
    role = (await connection.execute(text(_PG_ROLE_SQL))).mappings().first() or {}
    report.violations += [f"role có thuộc tính {name}" for name, enabled in role.items() if enabled]
    tables = (await connection.execute(text(_PG_WRITABLE_TABLES_SQL))).scalars().all()
    if tables:
        report.violations.append(f"có quyền ghi hoặc là chủ sở hữu bảng: {', '.join(tables)}")
    schemas = (await connection.execute(text(_PG_CREATE_SCHEMAS_SQL))).scalars().all()
    if schemas:
        report.warnings.append(f"có quyền CREATE trên schema: {', '.join(schemas)}")
    return report


def mysql_report_from_grants(grants: list[str]) -> PrivilegeReport:
    """Classify SHOW GRANTS lines; role grants are only warned about.

    shortcut: privileges inherited through roles are not expanded; upgrade with SHOW GRANTS ... USING <roles>.
    """
    report = PrivilegeReport()
    for line in grants:
        match = _MYSQL_GRANT_RE.match(line.strip())
        if match is None:
            if line.strip().upper().startswith("GRANT "):
                report.warnings.append(f"quyền qua role chưa được kiểm tra: {line.strip()}")
            continue
        without_columns = re.sub(r"\s*\(.*?\)", "", match["privs"])  # "SELECT (a, b)" -> "SELECT"
        privileges = {p.strip().upper() for p in without_columns.split(",")}
        extra = sorted(privileges - _MYSQL_READ_PRIVILEGES)
        if extra or "WITH GRANT OPTION" in line.upper():
            report.violations.append(f"MySQL grant vượt quyền đọc: {', '.join(extra) or 'WITH GRANT OPTION'}")
    return report
