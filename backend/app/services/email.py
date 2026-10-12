"""Outbound email for notifications.

Providers (``EMAIL_PROVIDER``):

* ``acs``: Azure Communication Services Email, authenticated with the platform's managed identity
  (no keys or connection strings). Recipients are sent as BCC, so they never see each other.
* ``log``: development and test only. Nothing is sent: a one-line summary is logged (recipients
  masked) and the message is kept in a small in-process outbox that tests can read.
* ``none``: email is disabled; sending raises ``EmailNotConfiguredError``.

Email addresses are personal data. They are never logged, audited or put in error messages in
full: use ``mask_email``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

#: Generous for ACS, which accepts the message and then delivers asynchronously.
_SEND_TIMEOUT_SECONDS = 30
_OUTBOX: deque[EmailMessage] = deque(maxlen=50)


class EmailNotConfiguredError(Exception):
    """Email delivery is not set up in this deployment."""


class EmailDeliveryError(Exception):
    """The provider did not accept the message. The message never contains addresses."""


@dataclass(frozen=True)
class EmailMessage:
    recipients: tuple[str, ...]
    subject: str
    text: str
    html: str
    #: What triggered it (alert, health, test), for metrics and logs.
    kind: str = "alert"
    headers: dict[str, str] = field(default_factory=dict)


def mask_email(address: str) -> str:
    """``alice@contoso.com`` -> ``a***@contoso.com``. Safe for logs and audit entries."""
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def mask_all(addresses: list[str] | tuple[str, ...]) -> list[str]:
    return [mask_email(a) for a in addresses]


def email_status() -> dict[str, object]:
    """Which provider is active and whether it can send. No endpoints or addresses."""
    provider = get_settings().email_provider
    return {"provider": provider, "configured": provider != "none"}


def sent_messages() -> list[EmailMessage]:
    """The ``log`` provider's outbox, newest last (development and tests)."""
    return list(_OUTBOX)


def clear_outbox() -> None:
    _OUTBOX.clear()


async def send_email(message: EmailMessage) -> None:
    """Hand one message to the configured provider. Raises on failure; callers decide what to do."""
    from app.core.metrics import EMAIL_FAILURES, EMAILS_SENT

    settings = get_settings()
    if not message.recipients:
        return
    if settings.email_provider == "none":
        raise EmailNotConfiguredError(
            "Email delivery is not configured in this deployment. An administrator must set EMAIL_PROVIDER=acs "
            "with an Azure Communication Services resource (see docs/monitoring.md)."
        )
    try:
        if settings.email_provider == "log":
            _OUTBOX.append(message)
            logger.info(
                "email_logged",
                extra={
                    "subject": message.subject[:120],
                    "recipients": mask_all(message.recipients),
                    "kind": message.kind,
                },
            )
        else:
            await asyncio.wait_for(_send_acs(message), timeout=_SEND_TIMEOUT_SECONDS)
    except EmailNotConfiguredError:
        raise
    except Exception as exc:
        EMAIL_FAILURES.inc(message.kind)
        logger.warning(
            "email_failed",
            extra={"kind": message.kind, "error_type": type(exc).__name__, "recipients": len(message.recipients)},
        )
        raise EmailDeliveryError("The email could not be sent.") from exc
    EMAILS_SENT.inc(message.kind)


async def _send_acs(message: EmailMessage) -> None:
    from azure.communication.email.aio import EmailClient

    from app.services.azure.credentials import CredentialProvider

    settings = get_settings()
    # A fresh credential per message: emails are infrequent, and nothing then outlives the event loop
    # of the Celery task that sent it.
    provider = CredentialProvider(settings)
    try:
        credential = provider.for_tenant(settings.azure_tenant_id or "")
        async with EmailClient(str(settings.acs_email_endpoint), credential) as client:
            poller = await client.begin_send(
                {
                    "senderAddress": settings.email_sender_address,
                    # ACS needs a visible recipient; the sender itself, with everyone else in BCC.
                    "recipients": {
                        "to": [{"address": settings.email_sender_address}],
                        "bcc": [{"address": a} for a in message.recipients],
                    },
                    "content": {"subject": message.subject, "plainText": message.text, "html": message.html},
                    "headers": message.headers,
                    "userEngagementTrackingDisabled": True,
                }
            )
            await poller.result()
    finally:
        await provider.close()
