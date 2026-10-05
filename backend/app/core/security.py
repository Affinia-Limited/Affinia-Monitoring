"""Microsoft Entra ID access-token validation.

Tokens are never simply decoded and trusted. For every request we verify:

* signature, using the tenant's published JWKS signing keys (RS256 only)
* ``exp`` / ``nbf`` / ``iat`` (with small clock-skew leeway)
* ``aud`` equals the configured API audience
* ``iss`` matches the v2.0 issuer for the token's tenant
* ``tid`` is an allowed tenant
* the delegated scope (``scp``) or an application role (``roles``) is present

Tokens are never logged or persisted.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import jwt
from jwt import PyJWK

from app.core.config import Settings
from app.core.errors import AuthenticationError, PermissionDeniedError

logger = logging.getLogger(__name__)

_ALLOWED_ALGORITHMS = ["RS256"]
_JWKS_TTL_SECONDS = 3600
_LEEWAY_SECONDS = 60


@dataclass(frozen=True)
class TokenPrincipal:
    """The validated identity extracted from an access token."""

    object_id: str
    tenant_id: str
    email: str | None
    display_name: str | None
    first_name: str | None = None
    last_name: str | None = None
    app_roles: list[str] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)


class JwksCache:
    """Caches signing keys per tenant; refreshes on unknown ``kid`` (key rotation)."""

    def __init__(self, authority_host: str, http_client: httpx.AsyncClient | None = None):
        self._authority_host = authority_host.rstrip("/")
        self._http = http_client
        self._keys: dict[str, tuple[float, dict[str, PyJWK]]] = {}
        self._lock = asyncio.Lock()

    def _jwks_url(self, tenant_id: str) -> str:
        return f"{self._authority_host}/{tenant_id}/discovery/v2.0/keys"

    async def _fetch(self, tenant_id: str) -> dict[str, PyJWK]:
        client = self._http or httpx.AsyncClient(timeout=10)
        try:
            response = await client.get(self._jwks_url(tenant_id))
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            logger.error("jwks_fetch_failed", extra={"tenant_id": tenant_id, "error_type": type(exc).__name__})
            raise AuthenticationError("Unable to validate the access token at this time.") from exc
        finally:
            if self._http is None:
                await client.aclose()
        keys: dict[str, PyJWK] = {}
        for jwk in payload.get("keys", []):
            if jwk.get("kid") and jwk.get("kty") == "RSA":
                keys[jwk["kid"]] = PyJWK.from_dict(jwk, algorithm="RS256")
        return keys

    async def get_key(self, tenant_id: str, kid: str) -> PyJWK:
        now = time.monotonic()
        cached = self._keys.get(tenant_id)
        if cached and now - cached[0] < _JWKS_TTL_SECONDS and kid in cached[1]:
            return cached[1][kid]
        async with self._lock:
            cached = self._keys.get(tenant_id)
            if not (cached and now - cached[0] < _JWKS_TTL_SECONDS and kid in cached[1]):
                self._keys[tenant_id] = (now, await self._fetch(tenant_id))
        key = self._keys[tenant_id][1].get(kid)
        if key is None:
            raise AuthenticationError("The access token was signed with an unknown key.")
        return key


class EntraTokenValidator:
    def __init__(self, settings: Settings, jwks: JwksCache | None = None):
        self._settings = settings
        self._jwks = jwks or JwksCache(settings.entra_authority_host)

    def _expected_issuer(self, tenant_id: str) -> str:
        return f"{self._settings.entra_authority_host.rstrip('/')}/{tenant_id}/v2.0"

    async def validate(self, token: str) -> TokenPrincipal:
        settings = self._settings
        try:
            header = jwt.get_unverified_header(token)
            # Only used to pick the tenant's key set; every claim is verified below.
            unverified = jwt.decode(token, options={"verify_signature": False})
        except jwt.PyJWTError as exc:
            raise AuthenticationError("The access token is malformed.") from exc

        if header.get("alg") not in _ALLOWED_ALGORITHMS:
            raise AuthenticationError("The access token uses an unsupported algorithm.")
        kid = header.get("kid")
        tenant_id = unverified.get("tid")
        if not kid or not tenant_id:
            raise AuthenticationError("The access token is missing required claims.")
        if tenant_id not in settings.allowed_tenants:
            logger.warning("token_tenant_rejected", extra={"reason": "TENANT_MISMATCH"})
            raise AuthenticationError("Sign-in from this tenant is not permitted.")

        key = await self._jwks.get_key(tenant_id, kid)
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=_ALLOWED_ALGORITHMS,
                audience=settings.accepted_audiences,
                issuer=self._expected_issuer(tenant_id),
                leeway=_LEEWAY_SECONDS,
                options={"require": ["exp", "iat", "nbf", "aud", "iss", "tid", "oid"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthenticationError("The access token has expired.", code="TOKEN_EXPIRED") from exc
        except jwt.InvalidAudienceError as exc:
            raise AuthenticationError("The access token was not issued for this API.") from exc
        except jwt.InvalidIssuerError as exc:
            raise AuthenticationError("The access token issuer is not trusted.") from exc
        except jwt.PyJWTError as exc:
            raise AuthenticationError("The access token is invalid.") from exc

        scopes = str(claims.get("scp", "")).split()
        app_roles = list(claims.get("roles", []) or [])
        if settings.entra_required_scope not in scopes and not app_roles:
            raise PermissionDeniedError("The access token does not grant access to this API.")

        return TokenPrincipal(
            object_id=str(claims["oid"]),
            tenant_id=str(claims["tid"]),
            email=claims.get("preferred_username") or claims.get("email") or claims.get("upn"),
            display_name=claims.get("name"),
            first_name=claims.get("given_name"),
            last_name=claims.get("family_name"),
            app_roles=app_roles,
            scopes=scopes,
        )
