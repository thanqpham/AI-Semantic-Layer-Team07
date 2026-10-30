"""Unit tests for the in-memory enrichment progress registry."""

from src.services import enrichment_progress


def test_full_lifecycle_running_to_succeeded() -> None:
    start = enrichment_progress.start(101, 10)
    assert start is None
    snapshot = enrichment_progress.get(101)
    assert snapshot["status"] == "running"
    assert snapshot["phase"] == "analyzing"
    assert snapshot["total_tables"] == 10
    assert snapshot["completed_tables"] == 0
    assert snapshot["current_table"] is None
    assert snapshot["error"] is None
    assert snapshot["started_at"] is not None
    assert snapshot["finished_at"] is None
    assert enrichment_progress.is_running(101) is True

    enrichment_progress.mark_generating(101, 3, 10, "orders")
    snapshot = enrichment_progress.get(101)
    assert snapshot["phase"] == "generating"
    assert snapshot["completed_tables"] == 3
    assert snapshot["current_table"] == "orders"

    enrichment_progress.mark_saving(101)
    snapshot = enrichment_progress.get(101)
    assert snapshot["phase"] == "saving"
    assert snapshot["completed_tables"] == 3

    enrichment_progress.finish(101)
    snapshot = enrichment_progress.get(101)
    assert snapshot["status"] == "succeeded"
    assert snapshot["finished_at"] is not None
    assert enrichment_progress.is_running(101) is False


def test_fail_path_records_error_and_stops_running() -> None:
    enrichment_progress.start(202, 5)
    enrichment_progress.fail(202, "LLM 400")
    snapshot = enrichment_progress.get(202)
    assert snapshot["status"] == "failed"
    assert snapshot["error"] == "LLM 400"
    assert snapshot["finished_at"] is not None
    assert enrichment_progress.is_running(202) is False


def test_unknown_db_returns_idle() -> None:
    assert enrichment_progress.get(999) == {"status": "idle"}
    assert enrichment_progress.is_running(999) is False


def test_restart_after_finish_overwrites_old_record() -> None:
    enrichment_progress.start(303, 4)
    enrichment_progress.mark_generating(303, 2, 4, "orders")
    enrichment_progress.finish(303)
    enrichment_progress.start(303, 7)
    snapshot = enrichment_progress.get(303)
    assert snapshot["status"] == "running"
    assert snapshot["phase"] == "analyzing"
    assert snapshot["total_tables"] == 7
    assert snapshot["completed_tables"] == 0
    assert snapshot["error"] is None
    assert snapshot["finished_at"] is None


def test_try_start_claims_atomically_and_rejects_while_running() -> None:
    assert enrichment_progress.try_start(304) is True
    assert enrichment_progress.get(304)["status"] == "running"
    assert enrichment_progress.try_start(304) is False
    enrichment_progress.start(304, 9)  # service start() updates the claimed record in place
    assert enrichment_progress.get(304)["total_tables"] == 9
    assert enrichment_progress.get(304)["completed_tables"] == 0
    enrichment_progress.finish(304)
    assert enrichment_progress.try_start(304) is True
