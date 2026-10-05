"""Runtime secret resolution.

Secrets (e.g. notification webhook URLs) live in Azure Key Vault and are read
with the platform's managed identity when needed. The database stores only the
secret *name*. In local development without Key Vault, secrets can be supplied
as environment variables named ``SECRET_<NAME>`` (upper-cased, dashes as
underscores); this fallback is disabled outside development/test.
"""

from __future__ import annotations

import os
import re

from app.core.config import Environment, get_settings
from app.core.errors import AppError

_NAME = re.compile(r"^[0-9a-zA-Z-]{1,127}$")


class SecretNotAvailableError(AppError):
    status_code = 500
    code = "SECRET_NOT_AVAILABLE"
    message = "A required secret could not be read from Key Vault."


async def get_secret(name: str) -> str:
    if not _NAME.match(name):
        raise SecretNotAvailableError("Invalid secret reference.")
    settings = get_settings()
    if settings.key_vault_url:
        from azure.identity.aio import DefaultAzureCredential
        from azure.keyvault.secrets.aio import SecretClient

        async with (
            DefaultAzureCredential(
                managed_identity_client_id=settings.azure_client_id,
                workload_identity_client_id=settings.azure_client_id,
                exclude_environment_credential=True,
                exclude_interactive_browser_credential=True,
            ) as credential,
            SecretClient(settings.key_vault_url, credential) as client,
        ):
            try:
                secret = await client.get_secret(name)
            except Exception as exc:
                raise SecretNotAvailableError() from exc
            if not secret.value:
                raise SecretNotAvailableError()
            return secret.value
    if settings.environment in (Environment.development, Environment.test):
        value = os.environ.get(f"SECRET_{name.upper().replace('-', '_')}")
        if value:
            return value
    raise SecretNotAvailableError()
