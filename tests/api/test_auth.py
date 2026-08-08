from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.security import HTTPAuthorizationCredentials

from src.api import auth_utils


def test_verify_token_uses_public_supabase_client(monkeypatch) -> None:
    user = SimpleNamespace(id="user-1", email="engineer@agency.gov.au")
    get_user = Mock(return_value=SimpleNamespace(user=user))
    monkeypatch.setattr(auth_utils, "SUPABASE_JWT_SECRET", "placeholder")
    monkeypatch.setattr(
        auth_utils,
        "supabase_auth",
        SimpleNamespace(auth=SimpleNamespace(get_user=get_user)),
    )

    payload = auth_utils.verify_token(
        HTTPAuthorizationCredentials(scheme="Bearer", credentials="access-token")
    )

    assert payload == {
        "sub": "user-1",
        "email": "engineer@agency.gov.au",
        "_access_token": "access-token",
    }
    get_user.assert_called_once_with("access-token")


def test_authenticated_user_does_not_require_profile(monkeypatch) -> None:
    monkeypatch.setattr(auth_utils, "_get_profile", Mock(return_value={}))

    user = auth_utils.get_current_user(
        {
            "sub": "user-2",
            "email": "engineer@agency.gov.au",
            "_access_token": "access-token",
        }
    )

    assert user == {
        "id": "user-2",
        "email": "engineer@agency.gov.au",
        "company_id": None,
        "is_admin": False,
    }


def test_authenticated_user_receives_profile_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_utils,
        "_get_profile",
        Mock(return_value={"company_id": "example.com", "is_admin": True}),
    )

    user = auth_utils.get_current_user(
        {"sub": "user-3", "email": "engineer@example.com"}
    )

    assert user["company_id"] == "example.com"
    assert user["is_admin"] is True