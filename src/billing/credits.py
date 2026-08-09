"""Atomic Supabase credit operations shared by API and workers."""

from __future__ import annotations

from functools import lru_cache
import os
import re


PROJECT_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,79}$")


def normalize_project_code(project_code: str) -> str:
    normalized = project_code.strip().upper()
    if not PROJECT_CODE_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Project code must be 2-80 characters using letters, numbers, '.', '_', or '-'."
        )
    return normalized


@lru_cache(maxsize=1)
def _supabase_admin():
    from supabase import create_client

    return create_client(
        os.environ.get("SUPABASE_URL", "https://placeholder.supabase.co"),
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "placeholder"),
    )


def debit_analysis_credit(
    project_code: str,
    company_id: str,
    user_id: str,
    job_id: str,
) -> int:
    response = _supabase_admin().rpc(
        "debit_analysis_credit",
        {
            "p_project_code": normalize_project_code(project_code),
            "p_company_id": company_id,
            "p_user_id": user_id,
            "p_job_id": job_id,
            "p_description": f"Analysis job {job_id}",
        },
    ).execute()
    return int(response.data)


def refund_analysis_credit(
    project_code: str,
    user_id: str,
    job_id: str,
) -> int:
    response = _supabase_admin().rpc(
        "refund_analysis_credit",
        {
            "p_project_code": normalize_project_code(project_code),
            "p_user_id": user_id,
            "p_job_id": job_id,
            "p_description": f"Refund for analysis job {job_id}",
        },
    ).execute()
    return int(response.data)


def credit_project_purchase(
    project_code: str,
    user_id: str,
    checkout_session_id: str,
    amount: int = 1000,
) -> int:
    response = _supabase_admin().rpc(
        "credit_project_purchase",
        {
            "p_project_code": normalize_project_code(project_code),
            "p_user_id": user_id,
            "p_checkout_session_id": checkout_session_id,
            "p_amount": amount,
            "p_description": f"Stripe Checkout {checkout_session_id}",
        },
    ).execute()
    return int(response.data)


def adjust_project_credits(
    project_code: str,
    user_id: str,
    amount: int,
    description: str,
) -> int:
    response = _supabase_admin().rpc(
        "adjust_project_credits",
        {
            "p_project_code": normalize_project_code(project_code),
            "p_user_id": user_id,
            "p_amount": amount,
            "p_description": description,
        },
    ).execute()
    return int(response.data)