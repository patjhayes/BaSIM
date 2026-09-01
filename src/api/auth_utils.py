import os
from dotenv import load_dotenv
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
from supabase.lib.client_options import SyncClientOptions
import jwt

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://placeholder.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "placeholder")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "placeholder")

supabase_admin: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY or "placeholder",
)
supabase_auth: Client = create_client(
    SUPABASE_URL,
    SUPABASE_ANON_KEY or SUPABASE_SERVICE_ROLE_KEY,
)

security = HTTPBearer()


def _is_configured(value: str) -> bool:
    return bool(value and value != "placeholder")


def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """Validate a Supabase access token locally or through the Auth API."""
    token = credentials.credentials
    if _is_configured(SUPABASE_JWT_SECRET):
        try:
            return jwt.decode(
                token,
                SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError as exc:
            raise HTTPException(status_code=401, detail="Token has expired") from exc
        except jwt.InvalidTokenError:
            pass

    try:
        response = supabase_auth.auth.get_user(token)
        user = response.user if response else None
        if user is None:
            raise ValueError("Invalid token")
        return {
            "sub": user.id,
            "email": user.email,
            "_access_token": token,
        }
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _get_profile(user_id: str, access_token: str | None) -> dict:
    if _is_configured(SUPABASE_SERVICE_ROLE_KEY):
        client = supabase_admin
    elif _is_configured(SUPABASE_ANON_KEY) and access_token:
        client = create_client(
            SUPABASE_URL,
            SUPABASE_ANON_KEY,
            options=SyncClientOptions(
                headers={"Authorization": f"Bearer {access_token}"},
            ),
        )
    else:
        return {}

    response = client.table("profiles").select("*").eq("id", user_id).execute()
    return response.data[0] if response.data else {}


def get_current_user(payload: dict = Security(verify_token)):
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")

    try:
        profile = _get_profile(str(user_id), payload.get("_access_token"))
    except Exception:
        profile = {}

    return {
        "id": str(user_id),
        "email": email,
        "company_id": profile.get("company_id"),
        "is_admin": profile.get("is_admin", False),
        "eula_version": profile.get("eula_version"),
        "eula_accepted_at": profile.get("eula_accepted_at"),
    }


def get_current_admin(user: dict = Security(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
