"""Tests for target database least-privilege checks."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import get_settings
from src.models.db import LiveTargetDbModel
from src.models.schema_metadata import SchemaDialect
from src.services.live_db_service import create_live_target_db
from src.services.target_db_privileges import (
    PrivilegeReport,
    WritablePrivilegeError,
    check_read_only_privileges,
    ensure_read_only_account,
    mysql_report_from_grants,
    read_only_connect_args,
)

PG_URL = "postgresql://owner:secret@localhost:5432/shop"


@pytest.mark.parametrize(
    "grants",
    [
        ["GRANT USAGE ON *.* TO `r`@`%`", "GRANT SELECT, SHOW VIEW ON `shop`.* TO `r`@`%`"],
        ["GRANT SELECT (id, name) ON `shop`.`users` TO `r`@`%`"],
    ],
)
def test_mysql_read_only_grants_pass(grants: list[str]) -> None:
    assert mysql_report_from_grants(grants).violations == []


@pytest.mark.parametrize(
    "grant",
    [
        "GRANT ALL PRIVILEGES ON *.* TO `root`@`%` WITH GRANT OPTION",
        "GRANT SELECT, INSERT ON `shop`.* TO `w`@`%`",
        "GRANT SELECT ON `shop`.* TO `w`@`%` WITH GRANT OPTION",
    ],
)
def test_mysql_write_grants_are_violations(grant: str) -> None:
    assert mysql_report_from_grants([grant]).violations


def test_mysql_role_grant_is_warning_only() -> None:
    report = mysql_report_from_grants(["GRANT `analyst`@`%` TO `r`@`%`"])
    assert report.violations == [] and report.warnings


def test_read_only_connect_args_per_driver() -> None:
    assert read_only_connect_args("postgresql+asyncpg://u@h/d") == {
        "server_settings": {"default_transaction_read_only": "on"}
    }
    assert read_only_connect_args("postgresql+psycopg2://u@h/d") == {"options": "-c default_transaction_read_only=on"}
    assert read_only_connect_args("sqlite:///x.db") == {}


@pytest.mark.asyncio
async def test_sqlite_has_no_accounts_to_check() -> None:
    assert await check_read_only_privileges("sqlite:///x.db", SchemaDialect.SQLITE) == PrivilegeReport()


@pytest.mark.asyncio
async def test_violation_blocks_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    report = PrivilegeReport(violations=["role có thuộc tính rolsuper"])
    with patch("src.services.target_db_privileges.check_read_only_privileges", AsyncMock(return_value=report)):
        with pytest.raises(WritablePrivilegeError, match="rolsuper"):
            await ensure_read_only_account(PG_URL, SchemaDialect.POSTGRESQL)
        monkeypatch.setattr(get_settings(), "target_db_require_read_only", False)
        assert await ensure_read_only_account(PG_URL, SchemaDialect.POSTGRESQL) is report


@pytest.mark.asyncio
async def test_create_live_db_rejects_writable_account_without_saving(async_session: AsyncSession) -> None:
    report = PrivilegeReport(violations=["có quyền ghi hoặc là chủ sở hữu bảng: public.orders"])
    introspect = AsyncMock()
    with (
        patch("src.services.target_db_privileges.check_read_only_privileges", AsyncMock(return_value=report)),
        patch("src.services.live_db_service.introspect_live_database", introspect),
        pytest.raises(WritablePrivilegeError),
    ):
        await create_live_target_db(async_session, 1, "Shop", SchemaDialect.POSTGRESQL, PG_URL)
    introspect.assert_not_called()
    assert await async_session.scalar(select(func.count()).select_from(LiveTargetDbModel)) == 0
