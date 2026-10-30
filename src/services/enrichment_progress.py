"""In-memory progress registry for AI schema enrichment runs.

Keyed by semantic db id; the API runs a single uvicorn process (no ``--workers``)
on one event loop, so a plain dict needs no locking. Records are lost on restart,
which is fine: they only describe in-flight runs for the Schema Review banner.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class _Record:
    status: str
    phase: str
    total_tables: int
    completed_tables: int = 0
    current_table: str | None = None
    error: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None


_progress: dict[int, _Record] = {}


def start(db_id: int, total_tables: int) -> None:
    """Begin tracking an enrichment run for *db_id* in the analyzing phase.

    Updates a record already claimed by ``try_start`` in place so the claim's
    timestamp survives to the point the LLM table count is known.
    """
    record = _progress.get(db_id)
    if record is not None and record.status == "running":
        record.total_tables = total_tables
        return
    _progress[db_id] = _Record(status="running", phase="analyzing", total_tables=total_tables)


def try_start(db_id: int) -> bool:
    """Claim *db_id* for a run synchronously; False while one is in flight.

    Callers must claim BEFORE dispatching the background task: the task only
    reaches ``start`` after a DB roundtrip, which would leave a dispatchable
    window for a second concurrent run.
    """
    record = _progress.get(db_id)
    if record is not None and record.status == "running":
        return False
    _progress[db_id] = _Record(status="running", phase="analyzing", total_tables=0)
    return True


def mark_generating(db_id: int, completed: int, total: int, current_table: str | None) -> None:
    """Record LLM generation progress (tables completed so far, current focus)."""
    record = _progress.get(db_id)
    if record is None or record.status != "running":
        return
    record.phase = "generating"
    record.completed_tables = completed
    record.total_tables = total
    record.current_table = current_table


def mark_saving(db_id: int) -> None:
    """Move a running record into the saving (DB write) phase."""
    record = _progress.get(db_id)
    if record is None or record.status != "running":
        return
    record.phase = "saving"


def finish(db_id: int) -> None:
    """Mark the run as succeeded."""
    record = _progress.get(db_id)
    if record is None:
        return
    record.status = "succeeded"
    record.finished_at = datetime.now(UTC)


def fail(db_id: int, error: str) -> None:
    """Mark the run as failed with the error message to surface in the UI.

    Creates the record even when the run died before ``start`` was reached,
    so the banner never stays silent about a crashed enrichment.
    """
    record = _progress.setdefault(db_id, _Record(status="running", phase="analyzing", total_tables=0))
    record.status = "failed"
    record.error = error
    record.finished_at = datetime.now(UTC)


def is_running(db_id: int) -> bool:
    """Return True while an enrichment run is in flight for *db_id*."""
    record = _progress.get(db_id)
    return record is not None and record.status == "running"


def reset_all() -> None:
    """Clear every record; used by tests to isolate the module-global registry."""
    _progress.clear()


def get(db_id: int) -> dict[str, Any]:
    """Return a JSON-ready snapshot, or ``{"status": "idle"}`` when no run is known."""
    record = _progress.get(db_id)
    if record is None:
        return {"status": "idle"}
    return {
        "status": record.status,
        "phase": record.phase,
        "total_tables": record.total_tables,
        "completed_tables": record.completed_tables,
        "current_table": record.current_table,
        "error": record.error,
        "started_at": record.started_at.isoformat(),
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
    }
