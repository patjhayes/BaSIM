import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import stripe

from .auth_utils import get_current_admin, get_current_user, supabase_admin
from .legal import require_current_eula
from src.billing.credits import (
    adjust_project_credits,
    credit_project_purchase,
    normalize_project_code,
)


router = APIRouter()
LOGGER = logging.getLogger(__name__)

stripe.api_key = os.environ.get("STRIPE_API_KEY", "placeholder")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
BASIM_FRONTEND_URL = os.environ.get("BASIM_FRONTEND_URL", "").rstrip("/")

CREDIT_PACKAGES = {
    "starter": {
        "credits": 1_000,
        "unit_amount": 1_000,
        "label": "1,000 BaSIM Simulation Credits",
    },
    "standard": {
        "credits": 10_000,
        "unit_amount": 10_000,
        "label": "10,000 BaSIM Simulation Credits",
    },
}


class CreditAdjustment(BaseModel):
    project_code: str
    amount: int
    description: str


def _project_code(value: str) -> str:
    try:
        return normalize_project_code(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _company_id(user: dict) -> str:
    company_id = user.get("company_id")
    if not company_id:
        raise HTTPException(
            status_code=403,
            detail="User is not assigned to a company",
        )
    return str(company_id)


def _get_project(project_code: str) -> dict | None:
    response = (
        supabase_admin.table("projects")
        .select("*")
        .eq("project_code", project_code)
        .execute()
    )
    return response.data[0] if response.data else None


def _assert_project_access(project: dict, user: dict) -> None:
    if user.get("is_admin"):
        return
    if project["company_id"] != _company_id(user):
        raise HTTPException(
            status_code=403,
            detail="Not authorized to access this project",
        )


def _checkout_return_url(
    request: Request,
    status_value: str,
    project_code: str,
) -> str:
    origin = BASIM_FRONTEND_URL or request.headers.get(
        "origin",
        "https://basim.innealta.com.au",
    ).rstrip("/")
    query = urlencode(
        {"checkout": status_value, "project_code": project_code}
    )
    return f"{origin}/billing.html?{query}"


@router.get("/balance/{project_code}")
def get_balance(project_code: str, user: dict = Depends(require_current_eula)):
    """Fetch a company-owned project's credit balance without mutating it."""
    normalized = _project_code(project_code)
    project = _get_project(normalized)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    _assert_project_access(project, user)
    return {
        "project_code": normalized,
        "credit_balance": project["credit_balance"],
    }


@router.post("/checkout/{project_code}")
def create_checkout_link(
    project_code: str,
    request: Request,
    user: dict = Depends(require_current_eula),
    package: str = "starter",
):
    """Create a Stripe Checkout session for a fixed project-credit package."""
    selected_package = CREDIT_PACKAGES.get(package)
    if selected_package is None:
        raise HTTPException(status_code=400, detail="Invalid credit package")
    normalized = _project_code(project_code)
    company_id = _company_id(user)
    project = _get_project(normalized)
    if project is None:
        supabase_admin.table("projects").insert(
            {
                "project_code": normalized,
                "company_id": company_id,
                "credit_balance": 0,
            }
        ).execute()
    else:
        _assert_project_access(project, user)

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": "aud",
                        "product_data": {
                            "name": selected_package["label"],
                        },
                        "unit_amount": selected_package["unit_amount"],
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=_checkout_return_url(
                request,
                "success",
                normalized,
            ),
            cancel_url=_checkout_return_url(
                request,
                "cancelled",
                normalized,
            ),
            client_reference_id=normalized,
            metadata={
                "project_code": normalized,
                "user_id": user["id"],
                "credit_package": package,
                "credits": str(selected_package["credits"]),
            },
        )
        return {"payment_url": checkout_session.url}
    except Exception as exc:
        LOGGER.exception("Failed to create Stripe checkout for %s", normalized)
        raise HTTPException(
            status_code=502,
            detail="Unable to create checkout",
        ) from exc


@router.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    """Verify Stripe events and idempotently credit completed purchases."""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Stripe webhook is not configured",
        )
    signature = request.headers.get("stripe-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    try:
        event = stripe.Webhook.construct_event(
            await request.body(),
            signature,
            STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError) as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid Stripe webhook",
        ) from exc

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if session.get("payment_status") != "paid":
            return {"status": "ignored", "reason": "payment_not_paid"}
        metadata = session.get("metadata", {})
        project_code = metadata.get("project_code")
        user_id = metadata.get("user_id")
        package = metadata.get("credit_package")
        selected_package = CREDIT_PACKAGES.get(package or "")
        if not project_code or not user_id or selected_package is None:
            raise HTTPException(
                status_code=400,
                detail="Checkout metadata is incomplete",
            )
        credit_project_purchase(
            project_code,
            user_id,
            session["id"],
            amount=selected_package["credits"],
        )

    return {"status": "ok"}


@router.post("/admin/adjust_credits")
def admin_adjust_credits(
    adjustment: CreditAdjustment,
    admin: dict = Depends(get_current_admin),
):
    """Atomically add or deduct credits as an administrator."""
    balance = adjust_project_credits(
        adjustment.project_code,
        str(admin["id"]),
        adjustment.amount,
        adjustment.description,
    )
    return {
        "status": "success",
        "adjusted": adjustment.amount,
        "balance": balance,
    }