"""Versioned EULA acceptance for protected BaSIM web-service actions."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth_utils import get_current_user, supabase_admin


EULA_VERSION = "2026-09-02-placeholder"
router = APIRouter(prefix="/api/legal", tags=["legal"])


class EulaAcceptance(BaseModel):
    version: str


def require_current_eula(user: dict = Depends(get_current_user)) -> dict:
    if user.get("eula_version") != EULA_VERSION or not user.get("eula_accepted_at"):
        raise HTTPException(
            status_code=428,
            detail="Accept the current BaSIM End-User Licence Agreement before continuing",
        )
    return user


@router.post("/eula/accept")
def accept_eula(
    acceptance: EulaAcceptance,
    user: dict = Depends(get_current_user),
) -> dict:
    if acceptance.version != EULA_VERSION:
        raise HTTPException(status_code=400, detail="Unsupported EULA version")
    try:
        response = (
            supabase_admin.table("profiles")
            .update(
                {
                    "eula_version": EULA_VERSION,
                    "eula_accepted_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            .eq("id", user["id"])
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to record EULA acceptance") from exc
    if not response.data:
        raise HTTPException(status_code=404, detail="User profile not found")
    return {"eula_version": EULA_VERSION, "accepted": True}
