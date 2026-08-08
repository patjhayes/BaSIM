"""Durable analysis job status, result, event, and cancellation routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.api.auth_utils import get_current_user
from src.billing.credits import refund_analysis_credit
from src.jobs.store import JobStore

from .analyses import _billing_error, job_store_dependency


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def get_owned_job(store: JobStore, job_id: str, user: dict) -> dict:
    job = store.get_job(job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )
    if job.get("user_id") != str(user["id"]) and not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this analysis job",
        )
    return job


@router.get("/{job_id}")
def get_job_status(
    job_id: str,
    user: dict = Depends(get_current_user),
    store: JobStore = Depends(job_store_dependency),
) -> dict:
    return get_owned_job(store, job_id, user)


@router.get("/{job_id}/events")
def get_job_events(
    job_id: str,
    after: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
    store: JobStore = Depends(job_store_dependency),
) -> dict:
    get_owned_job(store, job_id, user)
    events = store.get_events(job_id, start=after)
    return {"events": events, "next": after + len(events)}


@router.get("/{job_id}/result")
def get_job_result(
    job_id: str,
    user: dict = Depends(get_current_user),
    store: JobStore = Depends(job_store_dependency),
) -> dict:
    job = get_owned_job(store, job_id, user)
    if job["status"] != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis job is {job['status']}",
        )
    result = store.get_result(job_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis result has expired",
        )
    return result


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    user: dict = Depends(get_current_user),
    store: JobStore = Depends(job_store_dependency),
) -> dict:
    job = get_owned_job(store, job_id, user)
    if job["status"] not in ("queued", "running", "cancelling"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Analysis job cannot be cancelled from {job['status']}",
        )
    if not store.request_cancellation(job_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Analysis job not found",
        )

    refunded = bool(job.get("refunded"))
    if job.get("cost", 0) > 0 and job.get("project_code") and not refunded:
        try:
            refund_analysis_credit(
                str(job["project_code"]),
                str(job["user_id"]),
                job_id,
            )
            refunded = True
        except Exception as exc:
            raise _billing_error(exc) from exc

    store.update_job(
        job_id,
        status="cancelling",
        refunded=refunded,
        error="Cancellation requested",
    )
    store.append_event(
        job_id,
        {
            "type": "status",
            "status": "cancelling",
            "message": "Cancellation requested",
            "refunded": refunded,
        },
    )
    return {"job_id": job_id, "status": "cancelling", "refunded": refunded}