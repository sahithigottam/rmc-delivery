"""Clerk token verification and application role checks."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from fastapi.security import HTTPAuthorizationCredentials

from app import auth
from app.api.v1 import api_router
from app.auth import Principal
from app.config import settings


@pytest.fixture
def signed_token(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://issuer.test/jwks")
    monkeypatch.setattr(settings, "clerk_issuer", "https://issuer.test")
    monkeypatch.setattr(settings, "clerk_authorized_parties", "https://app.test")
    monkeypatch.setattr(settings, "super_admin_user_id", "user-super")

    class TestJwksClient:
        def get_signing_key_from_jwt(self, token):
            return SimpleNamespace(key=public_key)

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: TestJwksClient())

    def issue(**claims):
        now = datetime.now(timezone.utc)
        payload = {
            "iss": "https://issuer.test",
            "sub": "user-company-admin",
            "org_id": "org-one",
            "org_role": "org:admin",
            "azp": "https://app.test",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        payload.update(claims)
        return jwt.encode(payload, private_key, algorithm="RS256")

    return issue


def credentials(token):
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_valid_session_resolves_verified_user_org_and_role(signed_token):
    principal = auth.get_current_principal(credentials(signed_token()))
    assert principal == Principal(
        user_id="user-company-admin", organization_id="org-one",
        organization_role="org:admin", is_super_admin=False,
    )
    assert principal.is_plant_admin


def test_configured_super_admin_is_resolved_by_stable_user_id(signed_token):
    principal = auth.get_current_principal(credentials(signed_token(
        sub="user-super", org_role="org:member",
    )))
    assert principal.is_super_admin
    assert principal.is_plant_admin


def test_unconfigured_platform_owner_does_not_promote_company_admin(monkeypatch, signed_token):
    monkeypatch.setattr(settings, "super_admin_user_id", "")
    principal = auth.get_current_principal(credentials(signed_token()))
    assert not principal.is_super_admin


@pytest.mark.parametrize(("user_id", "allowed"), [
    ("user-super", True),
    ("user-second", True),
    ("user-company-admin", False),
    ("user-sec", False),
])
def test_semicolon_super_admin_allowlist(monkeypatch, signed_token, user_id, allowed):
    monkeypatch.setattr(settings, "super_admin_user_id", " user-super ; user-second ;; ")
    principal = auth.get_current_principal(credentials(signed_token(sub=user_id)))
    assert principal.is_super_admin is allowed
    if allowed:
        assert auth.require_super_admin(principal) == principal
    else:
        with pytest.raises(HTTPException) as error:
            auth.require_super_admin(principal)
        assert error.value.status_code == 403


def test_semicolon_only_allowlist_grants_nobody(monkeypatch, signed_token):
    monkeypatch.setattr(settings, "super_admin_user_id", " ; ; ")
    principal = auth.get_current_principal(credentials(signed_token(sub="user-super")))
    assert not principal.is_super_admin


@pytest.mark.parametrize("user_id", ["user-super", "user-company-admin"])
def test_current_user_endpoint_returns_verified_platform_capabilities(signed_token, user_id):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    response = TestClient(app).get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {signed_token(sub=user_id)}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user_id
    assert body["organization_id"] == "org-one"
    assert body["organization_role"] == "org:admin"
    assert body["is_platform_admin"] is (user_id == "user-super")
    assert body["can_manage_catalogue"] is (user_id == "user-super")
    assert body["can_manage_company_assignments"] is (user_id == "user-super")
    assert body["can_operate_trips"] is True


def test_expired_session_token_is_rejected(signed_token):
    expired = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials(signed_token(
            exp=expired, iat=expired - timedelta(minutes=5),
        )))
    assert error.value.status_code == 401


@pytest.mark.parametrize("role", ["org:admin", "org:member", "org:plantadmin", "org:driver"])
def test_operational_roles_cannot_administer_catalogue(signed_token, role):
    principal = auth.get_current_principal(
        credentials(signed_token(org_role=role)),
    )
    assert principal.organization_role == role
    assert principal.is_plant_admin
    assert not principal.is_super_admin
    assert auth.require_plant_admin(principal) == principal
    with pytest.raises(HTTPException) as error:
        auth.require_super_admin(principal)
    assert error.value.status_code == 403


@pytest.mark.parametrize("role", [None, "", "org:unknown", ["org:admin"]])
def test_missing_or_unsupported_roles_fail_closed(signed_token, role):
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials(signed_token(org_role=role)))
    assert error.value.status_code == 403


@pytest.mark.parametrize("role", ["admin", "plantadmin", "driver", "member"])
def test_current_clerk_token_format_uses_active_organization_role(signed_token, role):
    principal = auth.get_current_principal(credentials(signed_token(
        v=2, o={"id": "org-current", "rol": role},
        org_id="org-ignored", org_role="org:admin",
    )))
    assert principal.organization_id == "org-current"
    assert principal.organization_role == f"org:{role}"
    assert not principal.is_super_admin
    assert principal.is_plant_admin


@pytest.mark.parametrize("organization", [None, [], {}, {"id": "org-one", "rol": "unknown"}])
def test_current_token_missing_or_invalid_organization_fails_closed(signed_token, organization):
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials(signed_token(v=2, o=organization)))
    assert error.value.status_code == 403


@pytest.mark.parametrize(
    ("claims", "status"),
    [
        ({"azp": "https://attacker.test"}, 401),
        ({"azp": None}, 401),
        ({"org_id": None}, 403),
    ],
)
def test_rejects_untrusted_origin_or_missing_org(signed_token, claims, status):
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials(signed_token(**claims)))
    assert error.value.status_code == status


def test_missing_bearer_token_is_rejected():
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(None)
    assert error.value.status_code == 401


@pytest.mark.parametrize("claims", [
    {"org_id": None, "org_role": None},
    {"v": 2, "o": None},
])
def test_owner_without_company_can_administer_but_not_operate(signed_token, claims):
    principal = auth.get_current_principal(credentials(signed_token(sub="user-super", **claims)))
    assert principal.organization_id is None
    assert principal.organization_role is None
    assert auth.require_super_admin(principal) == principal
    with pytest.raises(HTTPException) as error:
        auth.require_plant_admin(principal)
    assert error.value.status_code == 403


@pytest.mark.parametrize("path", [
    "/api/v1/routes",
    "/api/v1/trips/all",
    "/api/v1/predict/delivery",
    "/api/v1/plants/analyse",
])
def test_owner_without_company_cannot_invoke_operational_endpoints(signed_token, path):
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    headers = {"Authorization": f"Bearer {signed_token(sub='user-super', v=2, o=None)}"}
    client = TestClient(app)
    response = client.post(path, headers=headers, json={}) if (
        "predict" in path or "analyse" in path
    ) else client.get(path, headers=headers)
    assert response.status_code == 403, response.text
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["is_platform_admin"] is True
    assert me.json()["organization_id"] is None
    assert me.json()["can_operate_trips"] is False


def test_api_requires_bearer_authentication():
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    response = TestClient(app).get("/api/v1/brands")
    assert response.status_code == 401


def test_missing_verification_configuration_fails_closed(monkeypatch, signed_token):
    monkeypatch.setattr(settings, "clerk_authorized_parties", "")
    with pytest.raises(HTTPException) as error:
        auth.get_current_principal(credentials(signed_token()))
    assert error.value.status_code == 503
