from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest
from starlette.requests import Request

from src.api import billing


class ProjectQuery:
    def __init__(self, project: dict | None) -> None:
        self.project = project
        self.inserted = None

    def select(self, _columns: str):
        return self

    def eq(self, _column: str, _value: str):
        return self

    def insert(self, payload: dict):
        self.inserted = payload
        return self

    def execute(self):
        return SimpleNamespace(data=[self.project] if self.project else [])


class SupabaseStub:
    def __init__(self, project: dict | None) -> None:
        self.query = ProjectQuery(project)

    def table(self, table_name: str):
        assert table_name == "projects"
        return self.query


def _request(path: str = "/api/billing/checkout/project-1") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [(b"origin", b"https://basim.innealta.com.au")],
        }
    )


def test_balance_lookup_is_read_only_for_unknown_project(monkeypatch) -> None:
    supabase = SupabaseStub(None)
    monkeypatch.setattr(billing, "supabase_admin", supabase)

    with pytest.raises(HTTPException) as error:
        billing.get_balance(
            " project-1 ",
            {"id": "user-1", "company_id": "company-1", "is_admin": False},
        )

    assert error.value.status_code == 404
    assert supabase.query.inserted is None


def test_checkout_registers_project_and_returns_to_static_page(monkeypatch) -> None:
    supabase = SupabaseStub(None)
    create_session = Mock(return_value=SimpleNamespace(url="https://stripe.test/pay"))
    monkeypatch.setattr(billing, "supabase_admin", supabase)
    monkeypatch.setattr(billing.stripe.checkout.Session, "create", create_session)
    monkeypatch.setattr(billing, "BASIM_FRONTEND_URL", "")

    response = billing.create_checkout_link(
        " project-1 ",
        _request(),
        {"id": "user-1", "company_id": "company-1", "is_admin": False},
    )

    assert response == {"payment_url": "https://stripe.test/pay"}
    assert supabase.query.inserted == {
        "project_code": "PROJECT-1",
        "company_id": "company-1",
        "credit_balance": 0,
    }
    checkout = create_session.call_args.kwargs
    assert checkout["client_reference_id"] == "PROJECT-1"
    assert checkout["success_url"] == (
        "https://basim.innealta.com.au/billing.html?"
        "checkout=success&project_code=PROJECT-1"
    )
    assert checkout["cancel_url"] == (
        "https://basim.innealta.com.au/billing.html?"
        "checkout=cancelled&project_code=PROJECT-1"
    )


def test_webhook_requires_configuration(monkeypatch) -> None:
    monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", "")

    with pytest.raises(HTTPException) as error:
        asyncio.run(billing.stripe_webhook(_request("/api/billing/webhook/stripe")))

    assert error.value.status_code == 503


def test_paid_webhook_uses_session_id_for_idempotent_credit(monkeypatch) -> None:
    event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_123",
                "payment_status": "paid",
                "metadata": {
                    "project_code": "PROJECT-1",
                    "user_id": "user-1",
                },
            }
        },
    }
    credit = Mock(return_value=1000)
    monkeypatch.setattr(billing, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    monkeypatch.setattr(billing.stripe.Webhook, "construct_event", Mock(return_value=event))
    monkeypatch.setattr(billing, "credit_project_purchase", credit)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/billing/webhook/stripe",
            "headers": [(b"stripe-signature", b"signed")],
        },
        receive=AsyncMock(
            return_value={"type": "http.request", "body": b"{}"}
        ),
    )

    response = asyncio.run(billing.stripe_webhook(request))

    assert response == {"status": "ok"}
    credit.assert_called_once_with("PROJECT-1", "user-1", "cs_test_123")