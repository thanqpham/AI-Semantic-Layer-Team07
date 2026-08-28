"""Run bootstrap: throwaway target DB, isolated metadata store, eval user."""

import asyncio
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from src.models.db import Base, UserModel
from src.services.database import get_async_engine

EVAL_USER_EMAIL = "agent-runner@eval.local"
EVAL_USERNAME = "agent-runner"
EVAL_PASSWORD_HASH = "eval-no-login"
SCHEMA_SCRIPT = "sources/sqlite/schema.sql"
SEED_SCRIPT = "sources/sqlite/seed_data.sql"


@dataclass(frozen=True)
class AgentRunContext:
    """Everything a collector needs for one isolated agent run."""

    run_dir: Path
    target_url: str
    session_maker: async_sessionmaker[AsyncSession]
    user_id: int
    domain_dir: Path
    engine: AsyncEngine

    async def aclose(self) -> None:
        """Dispose the metadata engine once the run is finished."""
        await self.engine.dispose()


def _apply_scripts(target_path: Path, domain_dir: Path) -> None:
    """Create the target sqlite file and run golden schema + seed scripts."""
    conn = sqlite3.connect(target_path)
    try:
        for script in (SCHEMA_SCRIPT, SEED_SCRIPT):
            sql = (domain_dir / script).read_text(encoding="utf-8")
            conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


async def _build_target(domain_dir: Path, run_dir: Path) -> str:
    """Build the throwaway target DB from golden sources; return its URL."""
    target_path = run_dir / "target.sqlite"
    await asyncio.to_thread(_apply_scripts, target_path, domain_dir)
    return f"sqlite:///{target_path.as_posix()}"


async def _init_metadata(run_dir: Path) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], int]:
    """Create a fresh metadata store with all ORM tables plus the eval user."""
    db_url = f"sqlite:///{(run_dir / 'metadata.sqlite').as_posix()}"
    engine = get_async_engine(db_url=db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as db:
        user = UserModel(
            email=EVAL_USER_EMAIL,
            username=EVAL_USERNAME,
            hashed_password=EVAL_PASSWORD_HASH,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    return engine, session_maker, user_id


def _require_fresh_run_dir(run_dir: Path) -> None:
    """Refuse a non-empty run dir before creating anything (no artifact mixing)."""
    if run_dir.exists() and (run_dir.is_file() or any(run_dir.iterdir())):
        raise FileExistsError(
            f"run dir already exists and is not empty: {run_dir} — pick a fresh --run-dir or remove it first"
        )


async def prepare_run(golden_root: Path, domain: str, run_dir: Path) -> AgentRunContext:
    """Build target sqlite from golden sources and a fresh metadata store."""
    _require_fresh_run_dir(run_dir)
    domain_dir = golden_root / domain
    if not domain_dir.is_dir():
        raise FileNotFoundError(f"unknown domain dir: {domain_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    target_url = await _build_target(domain_dir, run_dir)
    engine, session_maker, user_id = await _init_metadata(run_dir)
    return AgentRunContext(
        run_dir=run_dir,
        target_url=target_url,
        session_maker=session_maker,
        user_id=user_id,
        domain_dir=domain_dir,
        engine=engine,
    )
