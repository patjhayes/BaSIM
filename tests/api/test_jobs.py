from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from src.api.routes import jobs


class JobRouteStore:
    def __init__(self, state, result=None) -> None:
        self.state = dict(state)
        self.result = result
        self.events = []
        self.cancel_requested = False

    def get_job(self, job_id):
        return dict(self.state) if self.state else None

    def get_result(self, job_id):
        return self.result

    def request_cancellation(self, job_id):
        self.cancel_requested = True
        return True

    def update_job(self, job_id, **fields):
        self.state.update(fields)
        return dict(self.state)

    def append_event(self, job_id, event):
        self.events.append(event)


def test_job_owner_is_enforced() -> None:
    store = JobRouteStore({"id": "job-1", "user_id": "owner"})

    with pytest.raises(HTTPException) as error:
        jobs.get_owned_job(store, "job-1", {"id": "other", "is_admin": False})

    assert error.value.status_code == 403


def test_completed_result_is_returned() -> None:
    result = {"model_runs": [{"peak_depth_m": 0.1431}]}
    store = JobRouteStore(
        {"id": "job-2", "user_id": "owner", "status": "completed"},
        result=result,
    )

    actual = jobs.get_job_result("job-2", {"id": "owner"}, store)

    assert actual == result


def test_paid_cancellation_refunds_and_marks_cancelling(monkeypatch) -> None:
    store = JobRouteStore(
        {
            "id": "job-3",
            "user_id": "owner",
            "status": "running",
            "cost": 1,
            "project_code": "PROJECT",
            "refunded": False,
        }
    )
    refund = Mock(return_value=10)
    monkeypatch.setattr(jobs, "refund_analysis_credit", refund)

    response = jobs.cancel_job("job-3", {"id": "owner"}, store)

    assert response == {
        "job_id": "job-3",
        "status": "cancelling",
        "refunded": True,
    }
    assert store.cancel_requested is True
    assert store.state["status"] == "cancelling"
    assert store.state["refunded"] is True
    assert store.events[-1]["status"] == "cancelling"
    refund.assert_called_once_with("PROJECT", "owner", "job-3")