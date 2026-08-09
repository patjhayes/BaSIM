"""Authenticated submission of design and clogging analysis jobs."""

from __future__ import annotations

from functools import lru_cache
import logging
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from src.api.auth_utils import get_current_user
from src.api.schemas import (
    CloggingAnalysisRequest,
    DesignAnalysisRequest,
    JobSubmissionResponse,
)
from src.billing.credits import (
    debit_analysis_credit,
    normalize_project_code,
    refund_analysis_credit,
)
from src.jobs.store import JobStore, get_job_store
from src.worker.celery_app import celery_app


LOGGER = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@lru_cache(maxsize=1)
def job_store_dependency() -> JobStore:
    return get_job_store()


def _is_free_tier(email: str) -> bool:
    normalized = email.strip().lower()
    return normalized.endswith(".gov.au") or normalized.endswith(
        "@innealta.com.au"
    )


def _billing_error(exc: Exception) -> HTTPException:
    message = str(exc).upper()
    if "INSUFFICIENT_CREDITS" in message:
        return HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail="Insufficient credits")
    if "PROJECT_FORBIDDEN" in message:
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Project does not belong to this company")
    if "PROJECT_NOT_FOUND" in message:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Billing service unavailable")


def _refund_after_dispatch_failure(
    project_code: Optional[str],
    user_id: str,
    job_id: str,
    charged: bool,
) -> None:
    if not charged or project_code is None:
        return
    try:
        refund_analysis_credit(project_code, user_id, job_id)
    except Exception:
        LOGGER.exception("Failed to refund analysis job %s after dispatch failure", job_id)


def submit_analysis_job(
    *,
    analysis_type: str,
    payload: dict[str, Any],
    project_code: Optional[str],
    user: dict[str, Any],
    store: JobStore,
) -> JobSubmissionResponse:
    job_id = str(uuid.uuid4())
    user_id = str(user["id"])
    email = str(user.get("email") or "")
    free_tier = _is_free_tier(email)
    cost = 0 if free_tier else 1
    charged = False

    if not free_tier:
        if not project_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="project_code is required for commercial users",
            )
        try:
            project_code = normalize_project_code(project_code)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc
        company_id = user.get("company_id")
        if not company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User is not assigned to a company",
            )
        try:
            debit_analysis_credit(project_code, str(company_id), user_id, job_id)
            charged = True
        except Exception as exc:
            raise _billing_error(exc) from exc

    try:
        store.create_job(
            job_id,
            analysis_type,
            payload,
            user_id=user_id,
            project_code=project_code,
            cost=cost,
        )
        celery_app.send_task(
            f"basim.analysis.{analysis_type}",
            args=[job_id, payload],
        )
    except Exception as exc:
        state = store.update_job(job_id, status="failed", error=str(exc))
        if state is not None:
            store.append_event(
                job_id,
                {
                    "type": "error",
                    "status": "failed",
                    "message": "Failed to enqueue analysis",
                },
            )
        _refund_after_dispatch_failure(project_code, user_id, job_id, charged)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue analysis",
        ) from exc

    return JobSubmissionResponse(job_id=job_id, status="queued", cost=cost)


@router.post("/design", response_model=JobSubmissionResponse, status_code=202)
def submit_design(
    request: DesignAnalysisRequest,
    user: dict = Depends(get_current_user),
    store: JobStore = Depends(job_store_dependency),
) -> JobSubmissionResponse:
    payload = request.model_dump(mode="json", exclude={"project_code"})
    return submit_analysis_job(
        analysis_type="design",
        payload=payload,
        project_code=request.project_code,
        user=user,
        store=store,
    )


@router.post("/clogging", response_model=JobSubmissionResponse, status_code=202)
def submit_clogging(
    request: CloggingAnalysisRequest,
    user: dict = Depends(get_current_user),
    store: JobStore = Depends(job_store_dependency),
) -> JobSubmissionResponse:
    payload = request.model_dump(mode="json", exclude={"project_code"})
    return submit_analysis_job(
        analysis_type="clogging",
        payload=payload,
        project_code=request.project_code,
        user=user,
        store=store,
    )