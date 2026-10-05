"""Selects the real or mock Azure implementation based on configuration."""

from __future__ import annotations

from app.core.config import AzureProvider, get_settings
from app.services.azure.types import AzureServices

_services: AzureServices | None = None
_credentials = None


def build_azure_services() -> AzureServices:
    global _credentials
    settings = get_settings()
    if settings.azure_provider is AzureProvider.mock:
        from app.services.azure.mock.services import MockLogsService, MockMetricsService, MockResourceGraphService

        return AzureServices(MockResourceGraphService(), MockMetricsService(), MockLogsService(), is_mock=True)

    from app.services.azure.credentials import CredentialProvider
    from app.services.azure.log_analytics import AzureLogsService
    from app.services.azure.monitor import AzureMetricsService
    from app.services.azure.resource_graph import AzureResourceGraphService

    _credentials = CredentialProvider(settings)
    return AzureServices(
        AzureResourceGraphService(_credentials),
        AzureMetricsService(_credentials),
        AzureLogsService(_credentials),
        is_mock=False,
    )


def get_azure_services() -> AzureServices:
    """FastAPI dependency and worker accessor. Overridden in tests."""
    global _services
    if _services is None:
        _services = build_azure_services()
    return _services


def set_azure_services(services: AzureServices | None) -> None:
    global _services
    _services = services


async def close_azure_services() -> None:
    global _credentials, _services
    if _credentials is not None:
        await _credentials.close()
    _credentials = None
    _services = None
