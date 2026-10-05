"""Import every model so Alembic and ``Base.metadata`` see the full schema."""

from app.models.alert import Alert, AlertEvent, AlertRule, HealthThreshold, NotificationChannel
from app.models.audit import AuditLog
from app.models.azure import AzureConnection, Resource, ResourceGroup, Subscription, SyncRun
from app.models.dashboard import Dashboard, DashboardTemplate, DashboardWidget
from app.models.organization import Organization, Role, User, UserStatus
from app.models.project import Environment, Project

__all__ = [
    "Alert",
    "AlertEvent",
    "AlertRule",
    "AuditLog",
    "AzureConnection",
    "Dashboard",
    "DashboardTemplate",
    "DashboardWidget",
    "Environment",
    "HealthThreshold",
    "NotificationChannel",
    "Organization",
    "Project",
    "Resource",
    "ResourceGroup",
    "Role",
    "Subscription",
    "SyncRun",
    "User",
    "UserStatus",
]
