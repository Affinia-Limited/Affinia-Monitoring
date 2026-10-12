import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, Pencil } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { endpoints } from "@/api/endpoints";
import { KeyValue, PageHeader } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useAccess } from "@/hooks/useAccess";
import { PERMISSIONS, useMe, usePermission } from "@/hooks/useMe";
import { formatDateTime } from "@/utils/format";
import { UserActionsMenu } from "./UsersPage";
import type { UserDetail } from "@/types/api";
import { accessSummary } from "./UsersPage";
import { availableActions, EditAccessDialog, ROLE_LABELS, userName, UserStatusBadge } from "./userShared";

const AUDIT_PAGE_SIZE = 20;

function AuditHistory({ userId }: { userId: string }) {
  const [page, setPage] = useState(1);
  const audit = useQuery({
    queryKey: ["user-audit", userId, page],
    queryFn: () => endpoints.userAudit(userId, { page, page_size: AUDIT_PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const pages = Math.max(1, Math.ceil((audit.data?.total ?? 0) / AUDIT_PAGE_SIZE));
  return (
    <Card>
      <CardHeader title="Audit history" description="Access changes made to this user and actions they performed." />
      <CardContent className="px-0">
        {audit.isLoading ? (
          <div className="px-4">
            <LoadingBlock label="Loading audit history" />
          </div>
        ) : audit.isError ? (
          <div className="px-4">
            <ErrorState error={audit.error} />
          </div>
        ) : !audit.data?.items.length ? (
          <EmptyState title="No audit entries yet" />
        ) : (
          <>
            <Table>
              <THead>
                <TR>
                  <TH>Time</TH>
                  <TH>Action</TH>
                  <TH>Actor</TH>
                  <TH>Result</TH>
                  <TH>IP address</TH>
                </TR>
              </THead>
              <tbody>
                {audit.data.items.map((e) => (
                  <TR key={e.id}>
                    <TD className="whitespace-nowrap">{formatDateTime(e.created_at)}</TD>
                    <TD className="font-mono text-xs">{e.action}</TD>
                    <TD>{e.actor}</TD>
                    <TD>
                      <Badge tone={e.result === "success" ? "healthy" : e.result === "denied" ? "warning" : "critical"}>{e.result}</Badge>
                    </TD>
                    <TD className="font-mono text-xs">{e.ip_address ?? "-"}</TD>
                  </TR>
                ))}
              </tbody>
            </Table>
            <div className="flex items-center justify-end gap-1 border-t border-border px-4 py-2 text-xs text-muted-foreground">
              <Button size="icon-sm" variant="ghost" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)}>
                <ChevronLeft />
              </Button>
              Page {page} of {pages}
              <Button size="icon-sm" variant="ghost" aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)}>
                <ChevronRight />
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function grantLabel(g: UserDetail["access"]["grants"][number]): string {
  if (!g.project_id) return "All projects";
  if (!g.environment_id) return `${g.project_name ?? "Project"}: all environments`;
  if (!g.resource_id) return `${g.project_name ?? "Project"} / ${g.environment_name ?? "Environment"}: all resources`;
  return `${g.project_name ?? "Project"} / ${g.environment_name ?? "Environment"} / ${g.resource_name ?? "Resource"}`;
}

/** Which projects, environments and resources the user can see; their role decides what they can do there. */
function AccessCard({ user, canEdit }: { user: UserDetail; canEdit: boolean }) {
  const [editing, setEditing] = useState(false);
  const superAdmin = user.role_key === "super_admin";
  const grants = user.access?.grants ?? [];
  return (
    <Card>
      <CardHeader
        title="Projects and resources"
        description={`What ${userName(user)} can see. Their role (${ROLE_LABELS[user.role_key]}) decides what they can do within it.`}
        actions={
          canEdit ? (
            <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
              <Pencil /> Edit access
            </Button>
          ) : null
        }
      />
      <CardContent>
        {superAdmin ? (
          <p className="text-sm">Everything. Super Admins always have access to all projects, environments and resources.</p>
        ) : user.access?.unrestricted ? (
          <p className="text-sm">All projects, including projects created later.</p>
        ) : grants.length === 0 ? (
          <p className="text-sm text-warning">No access yet: this user can sign in but sees no projects.</p>
        ) : (
          <>
            <p className="mb-2 text-sm text-muted-foreground">{accessSummary(user)}</p>
            <ul className="space-y-1 text-sm" aria-label="Access grants">
              {grants.map((g) => (
                <li key={g.id} className="rounded-md border border-border px-3 py-1.5">
                  {grantLabel(g)}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
      {editing ? <EditAccessDialog user={user} open={editing} onClose={() => setEditing(false)} /> : null}
    </Card>
  );
}

export function UserDetailPage() {
  const { userId = "" } = useParams();
  const { data: me } = useMe();
  const access = useAccess();
  const canManage = usePermission(PERMISSIONS.manageUsers);
  const user = useQuery({ queryKey: ["user", userId], queryFn: () => endpoints.user(userId), enabled: canManage && !!userId });

  const back = (
    <Link to="/settings/users" className="mb-3 inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="size-4" />
      Users
    </Link>
  );
  if (!canManage) return <EmptyState title="You do not have access to user management" />;
  if (user.isLoading) return <LoadingBlock label="Loading user" />;
  if (user.isError || !user.data) {
    return (
      <>
        {back}
        <ErrorState error={user.error} />
      </>
    );
  }
  const u = user.data;
  return (
    <>
      {back}
      <PageHeader
        title={userName(u)}
        description={u.email ?? undefined}
        badge={<UserStatusBadge status={u.status} />}
        actions={<UserActionsMenu user={u} me={me} />}
      />
      <div className="space-y-4">
        <AccessCard user={u} canEdit={availableActions(u, me).editAccess} />
        <Card>
          <CardHeader title="Account" />
          <CardContent>
            <KeyValue
              items={[
                { label: "Name", value: u.display_name },
                { label: "Email", value: u.email },
                { label: "Role", value: `${ROLE_LABELS[u.role_key]}${u.role_managed_by_entra ? " (Entra ID app role)" : ""}` },
                { label: "Status", value: <UserStatusBadge status={u.status} /> },
                { label: "Added by", value: u.created_by_name ?? "System" },
                { label: "Created", value: formatDateTime(u.created_at) },
                { label: "Invited", value: u.invited_at ? formatDateTime(u.invited_at) : null },
                {
                  label: "Invitation expires",
                  value: u.status === "pending" && u.invitation_expires_at ? formatDateTime(u.invitation_expires_at) : null,
                },
                { label: "Activated", value: u.activated_at ? formatDateTime(u.activated_at) : null },
                { label: "Last login", value: u.last_login_at ? formatDateTime(u.last_login_at) : "Never" },
                { label: "Deactivated", value: u.deactivated_at ? formatDateTime(u.deactivated_at) : null },
              ]}
            />
          </CardContent>
        </Card>
        <Card>
          <CardHeader
            title="Microsoft Entra identity"
            description="Access is bound to this immutable object ID after the first sign-in. Email changes in Entra ID do not move access to another account."
          />
          <CardContent>
            <KeyValue
              items={[
                {
                  label: "Entra object ID",
                  value: u.entra_object_id ? (
                    <span className="font-mono text-xs">{u.entra_object_id}</span>
                  ) : (
                    <span className="text-muted-foreground">Bound on first sign-in</span>
                  ),
                },
                { label: "Tenant ID", value: <span className="font-mono text-xs">{u.entra_tenant_id}</span> },
              ]}
            />
          </CardContent>
        </Card>
        {access.unrestricted ? <AuditHistory userId={u.id} /> : null}
      </div>
    </>
  );
}
