"""Azure credential handling for the platform's own identity.

The platform never holds customer credentials. It authenticates as itself using
``DefaultAzureCredential``, which resolves, in order of precedence relevant here:

* Workload Identity (AKS / federated credentials) - production
* Managed Identity (App Service / Container Apps) - production
* Azure CLI / Azure Developer CLI sign-in - local development only

Customers grant that identity read-only Azure RBAC roles on their subscriptions
(or delegate access with Azure Lighthouse). See ``docs/azure-rbac.md``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from azure.core.credentials import AccessToken
from azure.core.credentials_async import AsyncTokenCredential
from azure.identity.aio import DefaultAzureCredential

from app.core.config import Environment, Settings


class TenantScopedCredential(AsyncTokenCredential):
    """Requests tokens for a specific tenant when it differs from the identity's home tenant.

    Cross-tenant token requests work for workload identity / multi-tenant app
    registrations when the tenant is listed in AZURE_ADDITIONALLY_ALLOWED_TENANTS.
    For Azure Lighthouse delegations the home tenant token is used directly.
    """

    def __init__(self, inner: AsyncTokenCredential, tenant_id: str | None):
        self._inner = inner
        self._tenant_id = tenant_id

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        if self._tenant_id and "tenant_id" not in kwargs:
            kwargs["tenant_id"] = self._tenant_id
        return await self._inner.get_token(*scopes, **kwargs)

    async def close(self) -> None:  # the shared inner credential is closed by the provider
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class CachingCredential(AsyncTokenCredential):
    """Caches access tokens until shortly before expiry and de-duplicates concurrent requests.

    ``DefaultAzureCredential`` does not cache tokens from developer credentials (each request
    starts an ``az`` process), and a dashboard issues many metric calls at once. Tokens are held
    in memory only, per process, and never logged or persisted.
    """

    _REFRESH_MARGIN_SECONDS = 300

    def __init__(self, inner: AsyncTokenCredential):
        self._inner = inner
        self._tokens: dict[tuple[Any, ...], AccessToken] = {}
        self._locks: dict[tuple[Any, ...], asyncio.Lock] = {}

    def _fresh(self, key: tuple[Any, ...]) -> AccessToken | None:
        token = self._tokens.get(key)
        if token and token.expires_on - self._REFRESH_MARGIN_SECONDS > time.time():
            return token
        return None

    async def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        if kwargs.get("claims"):  # claims challenges (e.g. CAE) must always fetch a new token
            return await self._inner.get_token(*scopes, **kwargs)
        key = (tuple(sorted(scopes)), kwargs.get("tenant_id"))
        if token := self._fresh(key):
            return token
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if token := self._fresh(key):
                return token
            token = await self._inner.get_token(*scopes, **kwargs)
            self._tokens[key] = token
            return token

    async def close(self) -> None:
        self._tokens.clear()
        await self._inner.close()

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class CredentialProvider:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._credential: CachingCredential | None = None

    def _base(self) -> CachingCredential:
        if self._credential is None:
            dev = self._settings.environment is Environment.development
            inner = DefaultAzureCredential(
                managed_identity_client_id=self._settings.azure_client_id,
                workload_identity_client_id=self._settings.azure_client_id,
                additionally_allowed_tenants=self._settings.azure_additionally_allowed_tenants,
                # Interactive and developer credentials are never used outside local development.
                exclude_interactive_browser_credential=True,
                exclude_cli_credential=not dev,
                exclude_developer_cli_credential=not dev,
                exclude_powershell_credential=not dev,
                exclude_visual_studio_code_credential=True,
                exclude_shared_token_cache_credential=True,
                # Never read service principal secrets from the environment.
                exclude_environment_credential=True,
                # `az` can be slow to start on developer machines (development only).
                process_timeout=60 if dev else 10,
            )
            self._credential = CachingCredential(inner)
        return self._credential

    def for_tenant(self, tenant_id: str) -> AsyncTokenCredential:
        home = self._settings.azure_tenant_id
        scoped_tenant = tenant_id if home and tenant_id.lower() != home.lower() else None
        return TenantScopedCredential(self._base(), scoped_tenant)

    async def close(self) -> None:
        if self._credential is not None:
            await self._credential.close()
            self._credential = None
