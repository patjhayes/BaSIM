"""Celery task adapters for framework-neutral GAH-3D services."""

from __future__ import annotations

import logging
from typing import Any

from src.billing.credits import refund_analysis_credit
from src.jobs.store import get_job_store
from src.soakhydro.application.clogging import run_clogging_analysis
from src.soakhydro.application.design import run_design_analysis

from .celery_app import celery_app
from .execution import execute_analysis_job


LOGGER = logging.getLogger(__name__)


def refund_job_if_needed(store: Any, job_id: str) -> bool:
    state = store.get_job(job_id)
    if (
        state is None
        or state.get("cost", 0) <= 0
        or state.get("refunded")
        or not state.get("project_code")
        or not state.get("user_id")
    ):
        return False
    try:
        refund_analysis_credit(
            str(state["project_code"]),
            str(state["user_id"]),
            job_id,
        )
    except Exception as exc:
        LOGGER.exception("Failed to refund terminal analysis job %s", job_id)
        store.append_event(
            job_id,
            {
                "type": "billing_error",
                "message": f"Automatic refund failed: {exc}",
            },
        )
        return False
    store.update_job(job_id, refunded=True)
    store.append_event(
        job_id,
        {"type": "refund", "amount": 1, "message": "Analysis credit refunded"},
    )
    return True


def execute_with_terminal_refund(
    store: Any,
    job_id: str,
    payload: dict[str, Any],
    runner: Any,
) -> dict[str, Any]:
    try:
        outcome = execute_analysis_job(store, job_id, payload, runner)
    except Exception:
        refund_job_if_needed(store, job_id)
        raise
    if outcome["status"] == "cancelled":
        refund_job_if_needed(store, job_id)
    return outcome


@celery_app.task(
    name="basim.analysis.design",
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_design_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = get_job_store()
    return execute_with_terminal_refund(
        store,
        job_id,
        payload,
        run_design_analysis,
    )


@celery_app.task(
    name="basim.analysis.clogging",
    acks_late=True,
    reject_on_worker_lost=True,
)
def run_clogging_job(job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = get_job_store()
    return execute_with_terminal_refund(
        store,
        job_id,
        payload,
        run_clogging_analysis,
    )