"""Verify Clerk session tokens and expose application authorization rules."""
from dataclasses import dataclass
import logging
from functools import lru_cache
from typing import Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import InvalidTokenError, PyJWKClientError

from app.config import settings

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)
OPERATIONAL_ROLES = frozenset({
    "org:admin", "org:member", "org:plantadmin", "org:driver",
})


@dataclass(frozen=True)
class Principal:
    """Identity and active organization extracted only from a verified token."""

    user_id: str
    organization_id: Optional[str]
    organization_role: Optional[str]
    is_super_admin: bool

    @property
    def is_plant_admin(self) -> bool:
        # For the current rollout, all verified organization members have the
        # same operational access. Driver-vs-Plant-Admin RBAC is deferred.
        return bool(self.organization_id) and self.organization_role in OPERATIONAL_ROLES


@lru_cache(maxsize=1)
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, timeout=5)


def get_current_principal(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Principal:
    """Authenticate a session; only the platform owner may omit company context."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer authentication is required")

    parties = {
        party.strip()
        for party in settings.clerk_authorized_parties.split(",")
        if party.strip()
    }
    if not settings.clerk_jwks_url or not settings.clerk_issuer or not parties:
        logger.error("Clerk authentication settings are incomplete")
        raise HTTPException(status_code=503, detail="Authentication is not configured")

    try:
        signing_key = _jwks_client(settings.clerk_jwks_url).get_signing_key_from_jwt(
            credentials.credentials,
        )
        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={"require": ["exp", "iat", "iss", "sub"]},
        )
    except (InvalidTokenError, PyJWKClientError, ValueError) as exc:
        logger.info("Rejected invalid Clerk bearer token: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid or expired bearer token") from exc

    authorized_party = claims.get("azp")
    if not isinstance(authorized_party, str) or authorized_party not in parties:
        logger.warning("Rejected Clerk token with unauthorized or missing azp claim")
        raise HTTPException(status_code=401, detail="Token was not issued for this application")

    user_id = claims.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Token has no user identity")
    super_admin_ids = {
        configured_id.strip()
        for configured_id in settings.super_admin_user_id.split(";")
        if configured_id.strip()
    }
    is_super_admin = user_id in super_admin_ids
    if claims.get("v") == 2:
        organization = claims.get("o")
        if organization is None:
            organization_id = organization_role = None
        elif not isinstance(organization, dict):
            raise HTTPException(status_code=403, detail="An active company organization is required")
        else:
            organization_id = organization.get("id")
            role = organization.get("rol")
            organization_role = f"org:{role}" if isinstance(role, str) else None
            if not organization_id or not organization_role:
                raise HTTPException(status_code=403, detail="A supported organization membership is required")
    else:
        organization_id = claims.get("org_id")
        organization_role = claims.get("org_role")
    if is_super_admin and organization_id is None and organization_role is None:
        return Principal(user_id, None, None, is_super_admin=True)
    if not isinstance(organization_id, str) or not organization_id:
        raise HTTPException(status_code=403, detail="An active company organization is required")
    if not isinstance(organization_role, str) or organization_role not in OPERATIONAL_ROLES:
        raise HTTPException(status_code=403, detail="A supported organization membership is required")

    return Principal(
        user_id=user_id,
        organization_id=organization_id,
        organization_role=organization_role,
        is_super_admin=is_super_admin,
    )


def require_plant_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Require an authenticated member of an active organization."""
    if not principal.is_plant_admin:
        raise HTTPException(status_code=403, detail="Plant Admin access is required")
    return principal


def require_super_admin(
    principal: Principal = Depends(get_current_principal),
) -> Principal:
    """Require the platform owner configured by verified Clerk user ID."""
    if not principal.is_super_admin:
        raise HTTPException(status_code=403, detail="Super Admin access is required")
    return principal
