import os
from fastapi import Request, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from supabase import create_client, Client
import jwt

# We use the Service Role Key for backend administration (bypassing RLS)
# But we verify client JWTs normally.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://placeholder.supabase.co")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "placeholder")
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "placeholder")

supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

security = HTTPBearer()

def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Validate the JWT from the Authorization header using Supabase JWT secret.
    Returns the user data if valid.
    """
    token = credentials.credentials
    try:
        # If SUPABASE_JWT_SECRET is set correctly, we can verify it synchronously
        # without hitting the API.
        # Audience is typically "authenticated" in Supabase
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            audience="authenticated"
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError as e:
        # Fallback: if JWT decoding fails locally (e.g. wrong secret in dev), 
        # try verifying it with the supabase API
        try:
            user = supabase_admin.auth.get_user(token)
            if user and user.user:
                return {"sub": user.user.id, "email": user.user.email}
            raise Exception("Invalid token")
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid token")

def get_current_user(payload: dict = Security(verify_token)):
    user_id = payload.get("sub")
    email = payload.get("email")
    if not user_id:
        raise HTTPException(status_code=401, detail="User ID not found in token")
    
    # Optionally, we can fetch their profile to see if they are admin or what company they belong to.
    # We do a quick lookup via the service role
    response = supabase_admin.table('profiles').select('*').eq('id', user_id).execute()
    if not response.data:
        raise HTTPException(status_code=401, detail="Profile not found")
        
    profile = response.data[0]
    return {
        "id": user_id,
        "email": email,
        "company_id": profile.get("company_id"),
        "is_admin": profile.get("is_admin", False)
    }

def get_current_admin(user: dict = Security(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
