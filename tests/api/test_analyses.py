from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.api.routes import analyses


class SubmissionStore:
    def __init__(self) -> None:
        self.created = None
        self.state = None
        self.events = []

    def create_job(
        self,
        job_id,
        analysis_type,
        payload,
        *,
        user_id,
        project_code,
        cost,
    ):
        self.created = {
            "job_id": job_id,
            "analysis_type": analysis_type,
            "payload": payload,
            "user_id": user_id,
            "project_code": project_code,
            "cost": cost,
        }

    def update_job(self, job_id, **fields):
        self.state = fields
        return fields if self.created is not None else None

    def append_event(self, job_id, event):
        self.events.append(event)


def test_free_tier_job_bypasses_billing(monkeypatch) -> None:
    store = SubmissionStore()
    debit = Mock()
    send_task = Mock()
    monkeypatch.setattr(analyses, "debit_analysis_credit", debit)
    monkeypatch.setattr(analyses.celery_app, "send_task", send_task)

    response = analyses.submit_analysis_job(
        analysis_type="design",
        payload={"latitude": -31.95},
        project_code=None,
        user={"id": "user-1", "email": "engineer@agency.gov.au"},
        store=store,
    )

    assert response.status == "queued"
    assert response.cost == 0
    debit.assert_not_called()
    assert store.created["cost"] == 0
    send_task.assert_called_once_with(
        "basim.analysis.design",
        args=[response.job_id, {"latitude": -31.95}],
    )


def test_commercial_job_debits_one_credit(monkeypatch) -> None:
    store = SubmissionStore()
    debit = Mock(return_value=9)
    monkeypatch.setattr(analyses, "debit_analysis_credit", debit)
    monkeypatch.setattr(analyses.celery_app, "send_task", Mock())

    response = analyses.submit_analysis_job(
        analysis_type="clogging",
        payload={"clogging_years": 10},
        project_code="PROJECT",
        user={
            "id": "user-2",
            "email": "engineer@example.com",
            "company_id": "example.com",
        },
        store=store,
    )

    assert response.cost == 1
    debit.assert_called_once_with(
        "PROJECT",
        "example.com",
        "user-2",
        response.job_id,
    )
    assert store.created["cost"] == 1


def test_enqueue_failure_marks_failed_and_refunds(monkeypatch) -> None:
    store = SubmissionStore()
    refund = Mock(return_value=10)
    monkeypatch.setattr(analyses, "debit_analysis_credit", Mock(return_value=9))
    monkeypatch.setattr(analyses, "refund_analysis_credit", refund)
    monkeypatch.setattr(
        analyses.celery_app,
        "send_task",
        Mock(side_effect=RuntimeError("broker unavailable")),
    )

    with pytest.raises(HTTPException) as error:
        analyses.submit_analysis_job(
            analysis_type="design",
            payload={},
            project_code="PROJECT",
            user={
                "id": "user-3",
                "email": "engineer@example.com",
                "company_id": "example.com",
            },
            store=store,
        )

    assert error.value.status_code == 503
    assert store.state["status"] == "failed"
    assert store.events[-1]["type"] == "error"
    refund.assert_called_once_with(
        "PROJECT",
        "user-3",
        store.created["job_id"],
    )