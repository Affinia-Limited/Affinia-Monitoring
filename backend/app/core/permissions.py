"""Application roles and permissions.

The frontend uses the permission list returned by ``/auth/me`` only to hide
controls; every protected endpoint enforces permissions server-side through
``require_permission``.
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    view_dashboards = "dashboards:view"
    manage_dashboards = "dashboards:manage"
    view_resources = "resources:view"
    view_logs = "logs:view"
    run_kql = "logs:run_kql"
    connect_azure = "azure:connect"
    sync_azure = "azure:sync"
    manage_projects = "projects:manage"
    view_alerts = "alerts:view"
    manage_alerts = "alerts:manage"
    acknowledge_alerts = "alerts:acknowledge"
    manage_users = "users:manage"
    manage_settings = "settings:manage"
    view_audit = "audit:view"


class Role(StrEnum):
    super_admin = "super_admin"
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


_VIEWER = {
    Permission.view_dashboards,
    Permission.view_resources,
    Permission.view_alerts,
}

_OPERATOR = _VIEWER | {
    Permission.view_logs,
    Permission.run_kql,
    Permission.acknowledge_alerts,
    Permission.sync_azure,
}

_ADMIN = _OPERATOR | {
    Permission.manage_dashboards,
    Permission.connect_azure,
    Permission.manage_projects,
    Permission.manage_alerts,
    Permission.view_audit,
}

_SUPER_ADMIN: set[Permission] = set(Permission)

ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.viewer: frozenset(_VIEWER),
    Role.operator: frozenset(_OPERATOR),
    Role.admin: frozenset(_ADMIN),
    Role.super_admin: frozenset(_SUPER_ADMIN),
}

ROLE_DESCRIPTIONS: dict[Role, str] = {
    Role.super_admin: "Full control, including user and platform settings.",
    Role.admin: "Manage projects, Azure connections, dashboards and alert rules.",
    Role.operator: "View everything, run log queries, acknowledge alerts and trigger syncs.",
    Role.viewer: "Read-only access to dashboards, resources and alerts.",
}

#: Entra app role values (``roles`` claim) mapped to application roles.
ENTRA_APP_ROLE_MAP: dict[str, Role] = {
    "Monitoring.SuperAdmin": Role.super_admin,
    "Monitoring.Admin": Role.admin,
    "Monitoring.Operator": Role.operator,
    "Monitoring.Viewer": Role.viewer,
}

_RANK = {Role.viewer: 0, Role.operator: 1, Role.admin: 2, Role.super_admin: 3}


def highest_role(roles: list[Role]) -> Role | None:
    return max(roles, key=lambda r: _RANK[r]) if roles else None


def role_rank(role: Role) -> int:
    return _RANK[role]


def permissions_for(role: Role) -> frozenset[Permission]:
    return ROLE_PERMISSIONS[role]
