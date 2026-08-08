from __future__ import annotations

import pytest

from src.worker.execution import execute_analysis_job


class MemoryStore:
    def __init__(self) -> None:
        self.cancelled = False
        self.state = {}
        self.events = []
        self.result = None

    def is_cancelled(self, job_id):
        return self.cancelled

    def update_job(self, job_id, **fields):
        self.state.update(fields)

    def append_event(self, job_id, event):
        self.events.append(event)

    def store_result(self, job_id, result):
        self.result = result


def test_completed_job_persists_progress_and_result() -> None:
    store = MemoryStore()

    def runner(payload, progress):
        progress({"phase": "routing", "step": 1, "total": 2})
        return {"analysis": payload["analysis"]}

    outcome = execute_analysis_job(
        store,
        "job-1",
        {"analysis": "design"},
        runner,
    )

    assert outcome == {"job_id": "job-1", "status": "completed"}
    assert store.state["status"] == "completed"
    assert store.state["progress"] == 100
    assert store.result == {"analysis": "design"}
    assert [event["type"] for event in store.events] == [
        "status",
        "progress",
        "complete",
    ]


def test_cancellation_during_progress_discards_result() -> None:
    store = MemoryStore()

    def runner(payload, progress):
        store.cancelled = True
        progress({"phase": "routing", "step": 1, "total": 2})
        return {"should_not": "persist"}

    outcome = execute_analysis_job(store, "job-2", {}, runner)

    assert outcome["status"] == "cancelled"
    assert store.state["status"] == "cancelled"
    assert store.result is None
    assert store.events[-1]["type"] == "cancelled"


def test_queued_cancellation_does_not_run_engine() -> None:
    store = MemoryStore()
    store.cancelled = True
    called = False

    def runner(payload, progress):
        nonlocal called
        called = True
        return {}

    outcome = execute_analysis_job(store, "job-3", {}, runner)

    assert outcome["status"] == "cancelled"
    assert called is False
    assert store.events[-1]["type"] == "cancelled"


def test_engine_failure_is_persisted_and_reraised() -> None:
    store = MemoryStore()

    def runner(payload, progress):
        raise RuntimeError("routing failed")

    with pytest.raises(RuntimeError, match="routing failed"):
        execute_analysis_job(store, "job-4", {}, runner)

    assert store.state["status"] == "failed"
    assert store.state["error"] == "routing failed"
    assert store.events[-1] == {
        "type": "error",
        "status": "failed",
        "message": "routing failed",
    }