from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request

from app.api.deps import CurrentUserDep, DbSession
from app.core.config import get_settings
from app.models import Organization, User
from app.schemas.misc import MeOut
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/config")
async def auth_config() -> dict[str, object]:
    """Public, non-secret settings the SPA needs to start MSAL."""
    settings = get_settings()
    return {
        "auth_mode": settings.auth_mode.value,
        "tenant_id": settings.entra_tenant_id,
        "client_id": settings.entra_client_id,
        "api_scope": f"{settings.entra_audience}/{settings.entra_required_scope}" if settings.entra_audience else None,
        "authority": f"{settings.entra_authority_host}/{settings.entra_tenant_id}"
        if settings.entra_tenant_id
        else None,
    }


async def _me(db: DbSession, user: CurrentUserDep) -> MeOut:
    org = await db.get(Organization, user.organization_id)
    settings = get_settings()
    return MeOut(
        id=user.id,
        organization_id=user.organization_id,
        organization_name=org.name if org else "",
        email=user.email,
        display_name=user.display_name,
        role=user.role.value,
        permissions=sorted(p.value for p in user.permissions),
        role_managed_by_entra=user.role_managed_by_entra,
        auth_mode=settings.auth_mode.value,
        azure_provider=settings.azure_provider.value,
    )


@router.get("/me", response_model=MeOut)
async def me(db: DbSession, user: CurrentUserDep) -> MeOut:
    return await _me(db, user)


@router.post("/session", response_model=MeOut)
async def start_session(request: Request, db: DbSession, user: CurrentUserDep) -> MeOut:
    """Called by the SPA right after an interactive sign-in so the login is audited."""
    target = await db.get(User, user.id)
    if target is not None:
        target.last_login_at = datetime.now(UTC)
    await record_audit(
        db,
        action="user.login_allowed",
        user=user,
        target_type="user",
        target_id=str(user.id),
        request=request,
        details={"trigger": "interactive_sign_in"},
    )
    await db.commit()
    return await _me(db, user)
