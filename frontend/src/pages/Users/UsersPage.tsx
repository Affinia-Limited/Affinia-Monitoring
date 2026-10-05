import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, MoreHorizontal, Search, UserPlus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import type { UserStatusAction } from "@/api/endpoints";
import { endpoints } from "@/api/endpoints";
import { PageHeader } from "@/components/common";
import { TimeAgo } from "@/components/status";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/form";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/menu";
import { EmptyState, ErrorState, LoadingBlock } from "@/components/ui/states";
import { LG_ONLY, Table, TD, TH, THead, TR } from "@/components/ui/table";
import { useDebounce } from "@/hooks/useDebounce";
import { PERMISSIONS, useMe, usePermission } from "@/hooks/useMe";
import type { Me, UserOut } from "@/types/api";
import { formatDateTime } from "@/utils/format";
import {
  AddUserDialog,
  availableActions,
  ChangeRoleDialog,
  ROLE_LABELS,
  ROLES,
  StatusActionDialog,
  STATUSES,
  statusLabel,
  userName,
  UserStatusBadge,
} from "./userShared";

const PAGE_SIZE = 25;

export function UserActionsMenu({ user, me }: { user: UserOut; me: Me | undefined }) {
  const [status, setStatus] = useState<UserStatusAction | null>(null);
  const [roleOpen, setRoleOpen] = useState(false);
  const actions = availableActions(user, me);
  const name = userName(user);
  if (actions.self) return <span className="text-xs text-muted-foreground">You</span>;
  const any = actions.changeRole || actions.suspend || actions.reactivate || actions.deactivate;
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={`Actions for ${name}`} disabled={!any}>
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem asChild>
            <Link to={`/settings/users/${user.id}`}>View details</Link>
          </DropdownMenuItem>
          {actions.changeRole ? <DropdownMenuItem onSelect={() => setRoleOpen(true)}>Change role</DropdownMenuItem> : null}
          {actions.suspend || actions.reactivate || actions.deactivate ? <DropdownMenuSeparator /> : null}
          {actions.reactivate ? <DropdownMenuItem onSelect={() => setStatus("reactivate")}>Reactivate</DropdownMenuItem> : null}
          {actions.suspend ? <DropdownMenuItem onSelect={() => setStatus("suspend")}>Suspend</DropdownMenuItem> : null}
          {actions.deactivate ? (
            <DropdownMenuItem className="text-critical" onSelect={() => setStatus("deactivate")}>
              {user.status === "pending" ? "Revoke invitation" : "Deactivate"}
            </DropdownMenuItem>
          ) : null}
        </DropdownMenuContent>
      </DropdownMenu>
      <StatusActionDialog user={user} action={status} onClose={() => setStatus(null)} />
      {roleOpen ? <ChangeRoleDialog user={user} me={me} open={roleOpen} onClose={() => setRoleOpen(false)} /> : null}
    </>
  );
}

export function UsersPage() {
  const { data: me } = useMe();
  const canManage = usePermission(PERMISSIONS.manageUsers);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const q = useDebounce(search.trim(), 300);
  const users = useQuery({
    queryKey: ["users", { q, role, status, page }],
    queryFn: () => endpoints.users({ q, role, status, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    enabled: canManage,
  });

  if (!canManage) {
    return (
      <EmptyState
        title="You do not have access to user management"
        description="Ask a Super Admin if you need to add or change users."
        action={
          <Link className="text-primary hover:underline" to="/settings">
            Back to settings
          </Link>
        }
      />
    );
  }

  const total = users.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(q || role || status);
  return (
    <>
      <PageHeader
        title="Users"
        description="Only users listed here can access the platform. Microsoft Entra ID verifies identity; access is granted here."
        actions={
          <Button onClick={() => setAdding(true)}>
            <UserPlus />
            Add user
          </Button>
        }
      />
      <Card>
        <div className="flex flex-wrap items-center gap-3 border-b border-border p-3">
          <div className="relative w-full max-w-xs">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              aria-label="Search users"
              className="h-8 pl-8"
              placeholder="Search name or email"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
          <Select aria-label="Filter by role" className="h-8 w-40 text-xs" value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}>
            <option value="">All roles</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </Select>
          <Select aria-label="Filter by status" className="h-8 w-40 text-xs" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {statusLabel(s)}
              </option>
            ))}
          </Select>
          <span className="ml-auto text-xs text-muted-foreground" aria-live="polite">
            {users.data ? `${total} user${total === 1 ? "" : "s"}` : null}
          </span>
        </div>
        {users.isLoading ? (
          <div className="p-4">
            <LoadingBlock label="Loading users" />
          </div>
        ) : users.isError ? (
          <div className="p-4">
            <ErrorState error={users.error} />
          </div>
        ) : !users.data?.items.length ? (
          <EmptyState
            title={filtered ? "No users match these filters" : "No users yet"}
            description={filtered ? "Try a different search or clear the filters." : "Add a user to grant access to the platform."}
          />
        ) : (
          <>
            <Table>
              <THead>
                <TR>
                  <TH>Display name</TH>
                  <TH>Email</TH>
                  <TH>Role</TH>
                  <TH>Status</TH>
                  <TH className={LG_ONLY}>Last login</TH>
                  <TH className={LG_ONLY}>Added</TH>
                  <TH className={LG_ONLY}>Added by</TH>
                  <TH className="text-right">Actions</TH>
                </TR>
              </THead>
              <tbody>
                {users.data.items.map((u) => (
                  <TR key={u.id}>
                    <TD>
                      <Link className="font-medium hover:underline" to={`/settings/users/${u.id}`}>
                        {u.display_name ?? "-"}
                      </Link>
                    </TD>
                    <TD className="max-w-64 truncate text-muted-foreground" title={u.email ?? ""}>
                      {u.email ?? "-"}
                    </TD>
                    <TD>
                      <span className="whitespace-nowrap">{ROLE_LABELS[u.role_key]}</span>
                      {u.role_managed_by_entra ? (
                        <Badge tone="outline" className="ml-1.5" title="Assigned through an Entra ID app role">
                          Entra
                        </Badge>
                      ) : null}
                    </TD>
                    <TD>
                      <UserStatusBadge status={u.status} />
                    </TD>
                    <TD className={LG_ONLY}>{u.last_login_at ? <TimeAgo value={u.last_login_at} /> : <span className="text-muted-foreground">Never</span>}</TD>
                    <TD className={`${LG_ONLY} whitespace-nowrap`}>{formatDateTime(u.invited_at ?? u.created_at)}</TD>
                    <TD className={`${LG_ONLY} text-muted-foreground`}>{u.created_by_name ?? "System"}</TD>
                    <TD className="text-right">
                      <UserActionsMenu user={u} me={me} />
                    </TD>
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
      </Card>
      <AddUserDialog me={me} open={adding} onClose={() => setAdding(false)} />
    </>
  );
}
