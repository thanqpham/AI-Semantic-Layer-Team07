"""Reject-flow storage: proposal rejection_reason column + 'rejected' metric status."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.db import Base, SemanticDatabaseModel, SemanticMetricModel, UserModel
from src.models.db_metric_proposals import MetricProposalModel

_NOW = datetime(2026, 1, 1)
_MIGRATION_GLOB = "*_add_metric_rejection_reason_and_status.py"
_CONSTRAINT_NAME = "ck_semantic_metrics_status"
_OLD_STATUSES = "('draft', 'pending_approval', 'needs_review', 'approved', 'unverified')"
_NEW_STATUSES = "('draft', 'pending_approval', 'needs_review', 'approved', 'unverified', 'rejected')"


# ---------------------------------------------------------------------------
# Model-level behavior
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def async_db_session():
    """Provide an async in-memory SQLite session with the full model schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
    await engine.dispose()


async def _seed_user_and_db(session: AsyncSession) -> tuple[int, int]:
    """Seed one user + one semantic database, returning (user_id, db_id)."""
    user = UserModel(
        email="reject@test.com",
        username="rejecter",
        hashed_password="hash",
        full_name="Reject Tester",
        status="active",
    )
    session.add(user)
    await session.flush()
    db_rec = SemanticDatabaseModel(
        created_by=user.id,
        display_name="Reject DB",
        db_type="postgresql",
        conn_url_enc="dummy_enc",
        status="draft",
    )
    session.add(db_rec)
    await session.flush()
    return user.id, db_rec.id


async def test_proposal_model_persists_rejection_reason(async_db_session: AsyncSession) -> None:
    """MetricProposalModel stores and reloads the rejection reason."""
    user_id, db_id = await _seed_user_and_db(async_db_session)
    proposal = MetricProposalModel(
        db_id=db_id,
        created_by=user_id,
        context={},
        review={"status": "pass"},
        status="pass",
        schema_fingerprint="0" * 64,
        rejection_reason="Thiếu căn cứ nghiệp vụ",
    )
    async_db_session.add(proposal)
    await async_db_session.commit()

    stored = await async_db_session.get(MetricProposalModel, proposal.id)
    assert stored is not None
    assert stored.rejection_reason == "Thiếu căn cứ nghiệp vụ"


async def test_proposal_model_rejection_reason_defaults_to_none(async_db_session: AsyncSession) -> None:
    """Existing proposals (created without a reason) persist NULL rejection_reason."""
    user_id, db_id = await _seed_user_and_db(async_db_session)
    proposal = MetricProposalModel(
        db_id=db_id,
        created_by=user_id,
        context={},
        review={"status": "pass"},
        status="pass",
        schema_fingerprint="0" * 64,
    )
    async_db_session.add(proposal)
    await async_db_session.commit()

    stored = await async_db_session.get(MetricProposalModel, proposal.id)
    assert stored is not None
    assert stored.rejection_reason is None


async def test_metric_model_accepts_rejected_status(async_db_session: AsyncSession) -> None:
    """semantic_metrics CHECK constraint allows the new 'rejected' status."""
    _user_id, db_id = await _seed_user_and_db(async_db_session)
    metric = SemanticMetricModel(
        db_id=db_id,
        name="Doanh thu bị từ chối",
        description="test",
        sql_template="SELECT 1",
        status="rejected",
        formula="SUM(x)",
    )
    async_db_session.add(metric)
    await async_db_session.commit()

    stored = await async_db_session.get(SemanticMetricModel, metric.id)
    assert stored is not None
    assert stored.status == "rejected"


# ---------------------------------------------------------------------------
# Migration round-trip (pattern of test_metric_proposals.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    """Fresh in-memory SQLite engine for migration testing."""
    eng = create_engine("sqlite:///:memory:")
    yield eng
    eng.dispose()


def _create_pre_migration_schema(engine) -> None:
    """Create tables as they look at the current head, before this migration."""
    with engine.begin() as conn:
        conn.execute(
            text(f"""
            CREATE TABLE semantic_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                db_id INTEGER NOT NULL,
                created_by INTEGER,
                name VARCHAR(200) NOT NULL,
                description TEXT NOT NULL,
                sql_template TEXT NOT NULL,
                source VARCHAR(20) NOT NULL DEFAULT 'manual',
                status VARCHAR(20) NOT NULL DEFAULT 'draft',
                formula TEXT NOT NULL DEFAULT '',
                aggregation_type VARCHAR(50),
                definition JSON,
                version INTEGER NOT NULL DEFAULT 1,
                approved_by INTEGER,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                CONSTRAINT {_CONSTRAINT_NAME} CHECK (status IN {_OLD_STATUSES})
            )
        """)
        )
        conn.execute(
            text("""
            CREATE TABLE metric_proposals (
                id VARCHAR(36) PRIMARY KEY,
                db_id INTEGER NOT NULL,
                created_by INTEGER NOT NULL,
                parent_id VARCHAR(36),
                context JSON NOT NULL,
                original_definition JSON,
                final_definition JSON,
                review JSON NOT NULL,
                status VARCHAR(24) NOT NULL,
                schema_fingerprint VARCHAR(64) NOT NULL,
                metric_id INTEGER,
                metric_version INTEGER,
                request_id INTEGER,
                created_at DATETIME NOT NULL
            )
        """)
        )


def _import_migration():
    """Import the new migration module from alembic/versions/."""
    versions_dir = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    migration_files = list(versions_dir.glob(_MIGRATION_GLOB))
    if not migration_files:
        pytest.fail(f"Migration file '{_MIGRATION_GLOB}' not found in alembic/versions/.")
    spec = importlib.util.spec_from_file_location("_add_metric_rejection_reason_migration", migration_files[0])
    module = importlib.util.module_from_spec(spec)
    sys.modules["_add_metric_rejection_reason_migration"] = module
    spec.loader.exec_module(module)
    return module


def _run(engine, direction: str) -> None:
    """Run the migration's upgrade()/downgrade() against the given engine."""
    module = _import_migration()
    with engine.connect() as conn:
        operations = Operations(MigrationContext.configure(conn))
        with patch.object(module, "op", operations):
            getattr(module, direction)()
        conn.commit()


def _insert_metric(conn, name: str, status: str) -> None:
    conn.execute(
        text(
            "INSERT INTO semantic_metrics (db_id, name, description, sql_template, status, created_at, updated_at) "
            "VALUES (1, :name, 'd', 's', :status, :now, :now)"
        ),
        {"name": name, "status": status, "now": _NOW},
    )


def _insert_proposal(conn, proposal_id: str, reason: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO metric_proposals (id, db_id, created_by, context, review, status, schema_fingerprint, "
            "rejection_reason, created_at) VALUES (:id, 1, 1, '{}', '{}', 'pass', 'fp', :reason, :now)"
        ),
        {"id": proposal_id, "reason": reason, "now": _NOW},
    )


def test_upgrade_adds_column_and_allows_rejected_status(engine) -> None:
    """upgrade() adds rejection_reason and widens the status constraint."""
    _create_pre_migration_schema(engine)
    _run(engine, "upgrade")

    columns = {c["name"] for c in sa.inspect(engine).get_columns("metric_proposals")}
    assert "rejection_reason" in columns

    with engine.begin() as conn:
        _insert_proposal(conn, "p1", "Thiếu căn cứ nghiệp vụ")
        _insert_metric(conn, "m_rejected", "rejected")

    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        with engine.begin() as conn:
            _insert_metric(conn, "m_bogus", "bogus")


def test_upgrade_keeps_existing_proposal_rows(engine) -> None:
    """upgrade() preserves proposal rows created before the column existed."""
    _create_pre_migration_schema(engine)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO metric_proposals (id, db_id, created_by, context, review, status, schema_fingerprint, "
                "created_at) VALUES ('legacy', 1, 1, '{}', '{}', 'pass', 'fp', :now)"
            ),
            {"now": _NOW},
        )
    _run(engine, "upgrade")

    with engine.connect() as conn:
        reason = conn.execute(text("SELECT rejection_reason FROM metric_proposals WHERE id = 'legacy'")).scalar_one()
    assert reason is None


def test_downgrade_drops_column_and_reverts_constraint(engine) -> None:
    """downgrade() removes rejection_reason and restores the old status set."""
    _create_pre_migration_schema(engine)
    _run(engine, "upgrade")
    _run(engine, "downgrade")

    columns = {c["name"] for c in sa.inspect(engine).get_columns("metric_proposals")}
    assert "rejection_reason" not in columns

    with pytest.raises(IntegrityError, match="CHECK constraint failed"):
        with engine.begin() as conn:
            _insert_metric(conn, "m_rejected_after_downgrade", "rejected")
