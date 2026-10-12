"""Diagnose Microsoft Teams alert delivery without printing any webhook URL.

Run inside the backend container:

    docker compose exec -T backend python -m app.tools.check_teams           # checks only
    docker compose exec -T backend python -m app.tools.check_teams --post    # also posts a test card

For every Teams channel it reports where its URL is expected (Key Vault or a SECRET_ variable),
whether the URL is found and well formed, whether the host resolves to a public address, and,
with --post, the HTTP status Teams returns. URLs are never printed.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
from sqlalchemy import select

from app.core.config import Environment, get_settings
from app.db.session import session_scope
from app.models import NotificationChannel
from app.services.alerts.channels.registry import DeliveryRefusedError, check_public_destination
from app.services.secrets import SecretNotAvailableError, get_secret


def env_name(secret_ref: str) -> str:
    return f"SECRET_{secret_ref.upper().replace('-', '_')}"


async def main(post: bool) -> int:
    settings = get_settings()
    env_secrets = settings.allow_env_secrets or settings.environment in (Environment.development, Environment.test)
    print(f"ENVIRONMENT        : {settings.environment.value}")
    print(f"Key Vault          : {'set' if settings.key_vault_url else 'not set'}")
    source = "Key Vault" if settings.key_vault_url else ("SECRET_ variables" if env_secrets else "NOWHERE")
    print(f"Secrets are read from: {source}")
    if source == "NOWHERE":
        print("  -> Production mode without Key Vault: SECRET_ variables are ignored.")
        print("     Set ENVIRONMENT=development, or ALLOW_ENV_SECRETS=true, and recreate the containers.")
    names = sorted(k for k in os.environ if k.startswith("SECRET_"))
    print(f"SECRET_ variables in this container: {names or 'none'}")

    async with session_scope() as db:
        channels = list(
            await db.scalars(
                select(NotificationChannel).where(
                    NotificationChannel.channel_type == "teams", NotificationChannel.deleted_at.is_(None)
                )
            )
        )
    if not channels:
        print("No Teams channels exist yet: add one under Alerts > Microsoft Teams.")
        return 1

    problems = 0
    for channel in channels:
        ref = channel.secret_ref or ""
        print(f"\nChannel '{channel.name}' (enabled={channel.enabled}) secret name: {ref or '(none)'}")
        if not ref:
            print("  PROBLEM: the channel has no secret name.")
            problems += 1
            continue
        if not settings.key_vault_url:
            raw = os.environ.get(env_name(ref))
            print(f"  Expected variable : {env_name(ref)} -> {'present' if raw is not None else 'MISSING'}")
            if raw is not None:
                if raw[:1] in "\"'" or raw[-1:] in "\"'":
                    print("  PROBLEM: the value has quotes around it. Remove the quotes in .env.")
                    problems += 1
                if raw != raw.strip():
                    print("  PROBLEM: the value has leading or trailing spaces.")
                    problems += 1
        try:
            url = await get_secret(ref)
        except SecretNotAvailableError:
            print("  PROBLEM: the URL could not be read (variable missing, misnamed or ignored in this mode).")
            problems += 1
            continue
        if not url.startswith("https://"):
            print("  PROBLEM: the value does not start with https://")
            problems += 1
            continue
        print("  URL found and starts with https://")
        try:
            await check_public_destination(url)
            print("  Host resolves to a public address: OK")
        except DeliveryRefusedError as exc:
            print(f"  PROBLEM: host check failed ({exc}). Check the server's DNS / internet access.")
            problems += 1
            continue
        if post:
            card = {
                "type": "message",
                "attachments": [
                    {
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": {
                            "type": "AdaptiveCard",
                            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                            "version": "1.4",
                            "body": [
                                {"type": "TextBlock", "text": "Diagnostic test from the Azure Monitoring Platform"}
                            ],
                        },
                    }
                ],
            }
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False) as client:
                    response = await client.post(url, json=card)
                print(f"  Teams answered HTTP {response.status_code}")
                if response.status_code >= 300:
                    print("  PROBLEM: Teams refused the post. Is the workflow still on, and is the URL complete?")
                    problems += 1
            except httpx.HTTPError as exc:
                print(f"  PROBLEM: could not reach Teams ({type(exc).__name__}). Check outbound HTTPS from the server.")
                problems += 1
    print("\nAll checks passed." if not problems else f"\n{problems} problem(s) found.")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main("--post" in sys.argv)))
