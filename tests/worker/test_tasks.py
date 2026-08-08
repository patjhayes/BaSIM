from __future__ import annotations

from unittest.mock import Mock

import pytest

from src.worker import tasks


class RefundStore:
    def __init__(self, cost=1) -> None:
        self.state = {
            "status": "queued",
            "cost": cost,
            "refunded": False,
            "project_code": "PROJECT" if cost else None,
            "user_id": "user-1",
            "result_available": False,
        }
        self.events = []

    def get_job(self, job_id):
        return dict(self.state)

    def is_cancelled(self, job_id):
        return False

    def update_job(self, job_id, **fields):
        self.state.update(fields)

    def append_event(self, job_id, event):
        self.events.append(event)

    def store_result(self, job_id, result):
        self.state["result_available"] = True


def test_paid_terminal_job_refunds_once(monkeypatch) -> None:
    store = RefundStore(cost=1)
    refund = Mock(return_value=10)
    monkeypatch.setattr(tasks, "refund_analysis_credit", refund)

    assert tasks.refund_job_if_needed(store, "job-1") is True
    assert tasks.refund_job_if_needed(store, "job-1") is False
    assert store.state["refunded"] is True
    assert store.events[-1]["type"] == "refund"
    refund.assert_called_once_with("PROJECT", "user-1", "job-1")


def test_free_terminal_job_does_not_call_billing(monkeypatch) -> None:
    store = RefundStore(cost=0)
    refund = Mock()
    monkeypatch.setattr(tasks, "refund_analysis_credit", refund)

    assert tasks.refund_job_if_needed(store, "job-2") is False
    refund.assert_not_called()


def test_engine_failure_is_refunded_and_reraised(monkeypatch) -> None:
    store = RefundStore(cost=1)
    refund = Mock(return_value=10)
    monkeypatch.setattr(tasks, "refund_analysis_credit", refund)

    def failing_runner(payload, progress):
        raise RuntimeError("engine failed")

    with pytest.raises(RuntimeError, match="engine failed"):
        tasks.execute_with_terminal_refund(store, "job-3", {}, failing_runner)

    assert store.state["status"] == "failed"
    assert store.state["refunded"] is True
    refund.assert_called_once_with("PROJECT", "user-1", "job-3")