"""Application configuration.

All configuration comes from environment variables (or a local, git-ignored
``.env`` file during development). No secrets are hard-coded here: Azure access
uses Managed Identity / Workload Identity / developer credentials through
``DefaultAzureCredential``, and any genuine secret (for example a notification
webhook URL) is resolved from Azure Key Vault at runtime.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

CsvList = Annotated[list[str], NoDecode]
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class Environment(StrEnum):
    development = "development"
    test = "test"
    staging = "staging"
    production = "production"


class AuthMode(StrEnum):
    #: Validate Microsoft Entra ID access tokens (the only mode allowed outside development).
    entra = "entra"
    #: Local development only: every request is treated as a fixed, clearly labelled dev user.
    dev = "dev"


class AzureProvider(StrEnum):
    #: Real Azure SDK calls using DefaultAzureCredential.
    azure = "azure"
    #: Deterministic mock implementations with the same interfaces. Development and tests only.
    mock = "mock"


class TaskBackend(StrEnum):
    celery = "celery"
    #: Runs jobs as in-process asyncio tasks. Development and tests only.
    inline = "inline"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: Environment = Environment.development
    app_name: str = "Azure Monitoring Platform"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://monitoring:monitoring@localhost:5432/monitoring"
    database_echo: bool = False
    #: ``password`` (credentials in DATABASE_URL, local development) or ``entra`` (Azure Database for
    #: PostgreSQL with Microsoft Entra authentication: the managed identity's access token is the password).
    database_auth: Literal["password", "entra"] = "password"

    redis_url: str | None = None

    # --- Authentication (Microsoft Entra ID) ---
    auth_mode: AuthMode = AuthMode.entra
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    #: Expected ``aud`` claim, usually ``api://<api-app-client-id>`` or the API client id.
    entra_audience: str | None = None
    #: Scope the SPA requests for the API (checked in the ``scp`` claim for delegated tokens).
    entra_required_scope: str = "access_as_user"
    #: Additional tenants allowed to sign in (multi-tenant deployments). Empty = home tenant only.
    entra_allowed_tenants: CsvList = Field(default_factory=list)
    entra_authority_host: str = "https://login.microsoftonline.com"
    #: Bootstrap only: Entra identities provisioned as the first Super Admin of their organisation.
    #: Entries are ``<object-id>`` (home tenant, ``ENTRA_TENANT_ID``) or ``<tenant-id>/<object-id>``.
    #: Ignored once the organisation has an active Super Admin. See docs/user-access-management.md.
    bootstrap_super_admin_oids: CsvList = Field(default_factory=list)

    #: Role of the synthetic user in ``AUTH_MODE=dev``.
    dev_user_role: str = "super_admin"

    # --- Azure ---
    azure_provider: AzureProvider = AzureProvider.azure
    #: Tenant of the platform's own identity (Managed Identity / Workload Identity).
    azure_tenant_id: str | None = None
    #: Client id of a user-assigned managed identity or workload identity app registration.
    azure_client_id: str | None = None
    #: Other tenants the platform identity may request tokens for.
    azure_additionally_allowed_tenants: CsvList = Field(default_factory=list)
    key_vault_url: str | None = None

    # --- Resource mapping ---
    project_tag_keys: CsvList = Field(default_factory=lambda: ["project", "Project", "application"])
    environment_tag_keys: CsvList = Field(default_factory=lambda: ["environment", "Environment", "env"])

    # --- Jobs ---
    task_backend: TaskBackend = TaskBackend.celery
    sync_interval_minutes: int = 15
    health_interval_minutes: int = 5

    # --- Caching (seconds) ---
    cache_ttl_metrics: int = 60
    cache_ttl_resource_graph: int = 300
    cache_ttl_health: int = 120

    # --- HTTP ---
    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:5173"])
    rate_limit_per_minute: int = 300
    rate_limit_kql_per_minute: int = 30
    #: Failed authentications (invalid/expired tokens) and access denials tolerated per client IP per minute.
    rate_limit_auth_failures_per_minute: int = 30
    #: Hard cap on rows returned from a log query.
    log_query_max_rows: int = 5000
    trusted_proxy_count: int = 0

    @field_validator(
        "cors_origins",
        "entra_allowed_tenants",
        "bootstrap_super_admin_oids",
        "azure_additionally_allowed_tenants",
        "project_tag_keys",
        "environment_tag_keys",
        mode="before",
    )
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def _guard_unsafe_modes(self) -> Settings:
        non_dev = self.environment not in (Environment.development, Environment.test)
        if non_dev and self.auth_mode is AuthMode.dev:
            raise ValueError("AUTH_MODE=dev is only permitted when ENVIRONMENT is development or test")
        if non_dev and self.azure_provider is AzureProvider.mock:
            raise ValueError("AZURE_PROVIDER=mock is only permitted when ENVIRONMENT is development or test")
        if non_dev and self.task_backend is TaskBackend.inline:
            raise ValueError("TASK_BACKEND=inline is only permitted when ENVIRONMENT is development or test")
        if self.auth_mode is AuthMode.entra and self.environment is not Environment.test:
            missing = [
                name
                for name, val in (
                    ("ENTRA_TENANT_ID", self.entra_tenant_id),
                    ("ENTRA_CLIENT_ID", self.entra_client_id),
                    ("ENTRA_AUDIENCE", self.entra_audience),
                )
                if not val
            ]
            if missing:
                raise ValueError(f"AUTH_MODE=entra requires: {', '.join(missing)}")
        for entry in self.bootstrap_super_admin_oids:
            tenant, _, oid = entry.rpartition("/")
            tenant = tenant or (self.entra_tenant_id or "")
            if not (_GUID.match(oid) and _GUID.match(tenant)):
                raise ValueError(
                    "BOOTSTRAP_SUPER_ADMIN_OIDS entries must be <object-id> or <tenant-id>/<object-id> GUIDs, "
                    "and ENTRA_TENANT_ID must be set for entries without a tenant"
                )
            if self.auth_mode is AuthMode.entra and tenant not in self.allowed_tenants:
                raise ValueError("BOOTSTRAP_SUPER_ADMIN_OIDS references a tenant that is not allowed to sign in")
        if non_dev and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are not permitted outside development")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment is Environment.production

    @property
    def bootstrap_super_admins(self) -> set[tuple[str, str]]:
        """``(tenant_id, object_id)`` pairs, lower-cased."""
        pairs = set()
        for entry in self.bootstrap_super_admin_oids:
            tenant, _, oid = entry.rpartition("/")
            pairs.add(((tenant or self.entra_tenant_id or "").lower(), oid.lower()))
        return pairs

    @property
    def allowed_tenants(self) -> set[str]:
        tenants = set(self.entra_allowed_tenants)
        if self.entra_tenant_id:
            tenants.add(self.entra_tenant_id)
        return tenants


@lru_cache
def get_settings() -> Settings:
    return Settings()
