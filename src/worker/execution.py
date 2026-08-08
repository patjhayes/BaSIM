"""Analysis job lifecycle shared by Celery tasks and tests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


AnalysisRunner = Callable[..., dict[str, Any]]


class JobCancelled(RuntimeError):
    pass


def _progress_value(event: dict[str, Any]) -> int:
    step = int(event.get("step", 0))
    total = int(event.get("total", 0))
    if total <= 0:
        return 5
    return min(99, max(1, round(step / total * 100)))


def execute_analysis_job(
    store: Any,
    job_id: str,
    payload: dict[str, Any],
    runner: AnalysisRunner,
) -> dict[str, Any]:
    get_job = getattr(store, "get_job", None)
    if get_job is not None:
        existing = get_job(job_id)
        if existing is None:
            raise RuntimeError(f"Job state not found or expired: {job_id}")
        if existing.get("status") == "completed" and existing.get(
            "result_available"
        ):
            return {"job_id": job_id, "status": "completed"}

    def report_progress(event: dict[str, Any]) -> None:
        if store.is_cancelled(job_id):
            raise JobCancelled("Analysis cancelled by user")
        progress = _progress_value(event)
        store.update_job(job_id, status="running", progress=progress)
        store.append_event(
            job_id,
            {
                "type": "progress",
                "status": "running",
                "progress": progress,
                **event,
            },
        )

    if store.is_cancelled(job_id):
        store.update_job(
            job_id,
            status="cancelled",
            error="Analysis cancelled by user",
        )
        store.append_event(
            job_id,
            {
                "type": "cancelled",
                "status": "cancelled",
                "message": "Analysis cancelled by user",
            },
        )
        return {"job_id": job_id, "status": "cancelled"}

    store.update_job(job_id, status="running", progress=0, error=None)
    store.append_event(
        job_id,
        {"type": "status", "status": "running", "progress": 0},
    )

    try:
        result = runner(payload, progress=report_progress)
        if store.is_cancelled(job_id):
            raise JobCancelled("Analysis cancelled by user")
        store.store_result(job_id, result)
        store.update_job(job_id, status="completed", progress=100)
        store.append_event(
            job_id,
            {"type": "complete", "status": "completed", "progress": 100},
        )
        return {"job_id": job_id, "status": "completed"}
    except JobCancelled as exc:
        store.update_job(job_id, status="cancelled", error=str(exc))
        store.append_event(
            job_id,
            {"type": "cancelled", "status": "cancelled", "message": str(exc)},
        )
        return {"job_id": job_id, "status": "cancelled"}
    except Exception as exc:
        store.update_job(job_id, status="failed", error=str(exc))
        store.append_event(
            job_id,
            {"type": "error", "status": "failed", "message": str(exc)},
        )
        raise