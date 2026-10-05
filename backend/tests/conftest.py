"""Test fixtures.

* Real Entra token validation: tokens are RS256-signed with a test key and the
  JWKS endpoint is served by an httpx MockTransport. Nothing is bypassed.
* Azure is provided by the mock services (same interfaces as the real ones).
* Database: SQLite by default; set TEST_DATABASE_URL to run against PostgreSQL.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

TEST_TENANT = "11111111-2222-4333-8444-555555555555"
OTHER_TENANT = "99999999-8888-4777-8666-555555555555"
AUDIENCE = "api://monitoring-test"
_db_file = os.path.join(tempfile.mkdtemp(), "test.db")

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "AUTH_MODE": "entra",
        "ENTRA_TENANT_ID": TEST_TENANT,
        "ENTRA_CLIENT_ID": "00000000-0000-4000-8000-0000000c1e17",
        "ENTRA_AUDIENCE": AUDIENCE,
        "ENTRA_ALLOWED_TENANTS": OTHER_TENANT,
        "AZURE_PROVIDER": "mock",
        "TASK_BACKEND": "inline",
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:///{_db_file}"),
        "RATE_LIMIT_PER_MINUTE": "100000",
        "RATE_LIMIT_KQL_PER_MINUTE": "100000",
    }
)
os.environ.pop("REDIS_URL", None)

import httpx  # noqa: E402
import jwt  # noqa: E402
import pytest  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from jwt.algorithms import RSAAlgorithm  # noqa: E402

from app.api import deps  # noqa: E402
from app.core.cache import MemoryCache, set_cache  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.core.security import EntraTokenValidator, JwksCache  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, get_sessionmaker, init_engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services.azure.provider import set_azure_services  # noqa: E402

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
KID = "test-kid"


def _jwks() -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(_KEY.public_key(), as_dict=True)
    jwk.update(kid=KID, use="sig", alg="RS256")
    return {"keys": [jwk]}


def _jwks_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/discovery/v2.0/keys"):
        return httpx.Response(200, json=_jwks())
    return httpx.Response(404)


def make_token(
    oid: str | None = None,
    *,
    tenant: str = TEST_TENANT,
    roles: list[str] | None = None,
    scp: str | None = "access_as_user",
    aud: str = AUDIENCE,
    iss: str | None = None,
    exp_offset: int = 3600,
    key: Any = None,
    kid: str = KID,
    algorithm: str = "RS256",
    name: str = "Test User",
    email: str | None = None,
) -> str:
    now = int(time.time())
    claims: dict[str, Any] = {
        "oid": oid or str(uuid.uuid4()),
        "tid": tenant,
        "aud": aud,
        "iss": iss or f"https://login.microsoftonline.com/{tenant}/v2.0",
        "iat": now - 10,
        "nbf": now - 10,
        "exp": now + exp_offset,
        "name": name,
        "preferred_username": email or "user@example.test",
    }
    if scp:
        claims["scp"] = scp
    if roles:
        claims["roles"] = roles
    signing_key = key if key is not None else _KEY
    return jwt.encode(claims, signing_key, algorithm=algorithm, headers={"kid": kid})


ROLE_CLAIMS = {
    "super_admin": ["Monitoring.SuperAdmin"],
    "admin": ["Monitoring.Admin"],
    "operator": ["Monitoring.Operator"],
    "viewer": ["Monitoring.Viewer"],
}


def member_oid(role: str, tenant: str = TEST_TENANT) -> str:
    """Object id of the pre-approved member used by ``auth_headers(role)``."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{tenant}/{role}"))


def auth_headers(role: str = "admin", oid: str | None = None, tenant: str = TEST_TENANT) -> dict[str, str]:
    """Headers for an approved, active member (seeded per test) with the matching Entra app role."""
    stable_oid = oid or member_oid(role, tenant)
    return {"Authorization": f"Bearer {make_token(stable_oid, tenant=tenant, roles=ROLE_CLAIMS[role])}"}


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def add_member(
    oid: str | None,
    *,
    role: str = "viewer",
    status: str = "active",
    tenant: str = TEST_TENANT,
    email: str | None = None,
    **fields: Any,
) -> uuid.UUID:
    """Inserts a user row directly (an approved member, or with ``oid=None`` an invitation)."""
    from sqlalchemy import select

    from app.models import Organization, User

    async with get_sessionmaker()() as session:
        org = await session.scalar(select(Organization).where(Organization.entra_tenant_id == tenant))
        assert org is not None
        user = User(
            organization_id=org.id,
            entra_tenant_id=tenant,
            entra_object_id=oid,
            email=email,
            role_key=role,
            status=status,
            **fields,
        )
        session.add(user)
        await session.commit()
        return user.id


@pytest.fixture(scope="session", autouse=True)
def _validator() -> None:
    jwks = JwksCache(
        get_settings().entra_authority_host, httpx.AsyncClient(transport=httpx.MockTransport(_jwks_handler))
    )
    deps.set_validator(EntraTokenValidator(get_settings(), jwks))


@pytest.fixture(autouse=True)
async def database() -> AsyncIterator[None]:
    await dispose_engine()
    init_engine(os.environ["DATABASE_URL"])
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    from app.core.permissions import ROLE_PERMISSIONS
    from app.models import Organization, Role, User

    async with get_sessionmaker()() as session:
        for role, perms in ROLE_PERMISSIONS.items():
            session.add(Role(key=role.value, name=role.value, description="", permissions=sorted(perms)))
        await session.flush()
        # Membership is admin-controlled: seed one approved member per role in each allowed tenant.
        for i, tenant in enumerate((TEST_TENANT, OTHER_TENANT)):
            org = Organization(name=f"Org {i}", slug=f"org-{i}", entra_tenant_id=tenant)
            session.add(org)
            await session.flush()
            for role in ROLE_PERMISSIONS:
                session.add(
                    User(
                        organization_id=org.id,
                        entra_tenant_id=tenant,
                        entra_object_id=member_oid(role.value, tenant),
                        email=f"{role.value}@example.test",
                        display_name=f"Test {role.value}",
                        role_key=role.value,
                        status="active",
                    )
                )
        await session.commit()
    set_cache(MemoryCache())
    set_azure_services(None)
    yield
    from app.services.jobs import wait_for_inline_jobs

    await wait_for_inline_jobs()
    await dispose_engine()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def headers() -> Callable[..., dict[str, str]]:
    return auth_headers


OTHER_SIGNING_KEY = _OTHER_KEY
