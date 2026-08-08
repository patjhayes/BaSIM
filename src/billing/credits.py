"""Atomic Supabase credit operations shared by API and workers."""

from __future__ import annotations

from functools import lru_cache
import os


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
            "p_project_code": project_code,
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
            "p_project_code": project_code,
            "p_user_id": user_id,
            "p_job_id": job_id,
            "p_description": f"Refund for analysis job {job_id}",
        },
    ).execute()
    return int(response.data)