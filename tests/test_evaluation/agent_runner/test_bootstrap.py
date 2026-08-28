"""Bootstrap: target sqlite, metadata store, and eval user."""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import select

from eval.agent_runner.bootstrap import EVAL_USER_EMAIL, prepare_run
from src.models.db import UserModel

GOLDEN_ROOT = Path("eval/golden_dataset")


async def test_prepare_run_creates_target_metadata_and_user(tmp_path):
    ctx = await prepare_run(GOLDEN_ROOT, "ecommerce", tmp_path / "run")

    target = sqlite3.connect(ctx.run_dir / "target.sqlite")
    tables = {row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    target.close()
    assert "fact_orders" in tables

    assert (ctx.run_dir / "metadata.sqlite").exists()
    async with ctx.session_maker() as db:
        user = (await db.execute(select(UserModel).where(UserModel.id == ctx.user_id))).scalar_one()
    assert user.email == EVAL_USER_EMAIL
    assert ctx.domain_dir == GOLDEN_ROOT / "ecommerce"


async def test_prepare_run_rejects_missing_domain(tmp_path):
    from eval.dataset.validator import DatasetValidationError

    with pytest.raises((DatasetValidationError, FileNotFoundError)):
        await prepare_run(GOLDEN_ROOT, "no-such-domain", tmp_path / "run")


async def test_prepare_run_rejects_non_empty_run_dir(tmp_path):
    """A non-empty run dir fails fast before any artifact is created."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    stale = run_dir / "stale.txt"
    stale.write_text("previous run artifact", encoding="utf-8")

    with pytest.raises(FileExistsError, match="run dir"):
        await prepare_run(GOLDEN_ROOT, "ecommerce", run_dir)

    assert list(run_dir.iterdir()) == [stale]  # nothing was added or removed


async def test_prepare_run_accepts_empty_existing_run_dir(tmp_path):
    """An existing but empty run dir is fine; only stale content is refused."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    ctx = await prepare_run(GOLDEN_ROOT, "ecommerce", run_dir)
    assert (ctx.run_dir / "target.sqlite").exists()


async def test_context_aclose_disposes_engine(tmp_path, monkeypatch):
    """aclose() must dispose the metadata engine exactly once per run."""
    from sqlalchemy.ext.asyncio import AsyncEngine

    ctx = await prepare_run(GOLDEN_ROOT, "ecommerce", tmp_path / "run")
    disposed: list[bool] = []
    original = AsyncEngine.dispose

    async def spy(self: AsyncEngine) -> None:
        disposed.append(True)
        await original(self)

    monkeypatch.setattr(AsyncEngine, "dispose", spy)
    await ctx.aclose()
    assert disposed == [True]
