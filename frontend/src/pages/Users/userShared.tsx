import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { endpoints, type UserStatusAction } from "@/api/endpoints";
import { Badge, type BadgeTone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/form";
import { ErrorState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import type { Me, RoleKey, UserOut, UserStatus } from "@/types/api";

export const ROLE_LABELS: Record<RoleKey, string> = {
  super_admin: "Super Admin",
  admin: "Admin",
  operator: "Operator",
  viewer: "Viewer",
};

const ROLE_RANK: Record<RoleKey, number> = { viewer: 0, operator: 1, admin: 2, super_admin: 3 };
export const ROLES = Object.keys(ROLE_LABELS) as RoleKey[];

const STATUS: Record<UserStatus, { label: string; tone: BadgeTone }> = {
  active: { label: "Active", tone: "healthy" },
  pending: { label: "Invited", tone: "info" },
  suspended: { label: "Suspended", tone: "warning" },
  deactivated: { label: "Deactivated", tone: "neutral" },
};

export const STATUSES = Object.keys(STATUS) as UserStatus[];

export function statusLabel(status: UserStatus): string {
  return STATUS[status].label;
}

export function UserStatusBadge({ status }: { status: UserStatus }) {
  return <Badge tone={STATUS[status].tone}>{STATUS[status].label}</Badge>;
}

export function userName(user: Pick<UserOut, "display_name" | "email">): string {
  return user.display_name ?? user.email ?? "Unnamed user";
}

/** Roles the signed-in user may assign (never above their own). The API enforces the same rule. */
export function assignableRoles(me: Me | undefined): RoleKey[] {
  const own = ROLE_RANK[(me?.role as RoleKey) ?? "viewer"] ?? 0;
  return ROLES.filter((r) => ROLE_RANK[r] <= own);
}

/** UI hints only; the API is authoritative for every rule. */
export function availableActions(user: UserOut, me: Me | undefined) {
  const self = user.id === me?.id;
  const outranked = ROLE_RANK[user.role_key] > ROLE_RANK[(me?.role as RoleKey) ?? "viewer"];
  const manageable = !self && !outranked;
  return {
    self,
    changeRole: manageable && !user.role_managed_by_entra && user.status !== "deactivated",
    suspend: manageable && user.status === "active",
    reactivate: manageable && (user.status === "suspended" || user.status === "deactivated"),
    deactivate: manageable && user.status !== "deactivated",
  };
}

const ACTION_COPY: Record<UserStatusAction, { title: string; confirm: string; body: (name: string, user: UserOut) => string; done: string }> = {
  suspend: {
    title: "Suspend user",
    confirm: "Suspend user",
    body: (name) => `Are you sure you want to suspend ${name}? ${name} will no longer be able to access the Monitoring Platform.`,
    done: "suspended",
  },
  reactivate: {
    title: "Reactivate user",
    confirm: "Reactivate user",
    body: (name, user) =>
      !user.activated_at
        ? `${name}'s invitation will be reopened for 30 days.`
        : `${name} will be able to access the Monitoring Platform again with their current role.`,
    done: "reactivated",
  },
  deactivate: {
    title: "Deactivate user",
    confirm: "Deactivate user",
    body: (name, user) =>
      user.status === "pending"
        ? `The invitation for ${name} will be revoked.`
        : `${name} will lose access to the Monitoring Platform. Their account and audit history are kept, and an administrator can reactivate them later.`,
    done: "deactivated",
  },
};

function useInvalidateUsers() {
  const qc = useQueryClient();
  return (id?: string) =>
    Promise.all([
      qc.invalidateQueries({ queryKey: ["users"] }),
      id ? qc.invalidateQueries({ queryKey: ["user", id] }) : null,
      id ? qc.invalidateQueries({ queryKey: ["user-audit", id] }) : null,
    ]);
}

export function StatusActionDialog({
  user,
  action,
  onClose,
}: {
  user: UserOut;
  action: UserStatusAction | null;
  onClose: () => void;
}) {
  const invalidate = useInvalidateUsers();
  const { notify } = useToast();
  const name = userName(user);
  const mutation = useMutation({
    mutationFn: (a: UserStatusAction) => endpoints.setUserStatus(user.id, a),
    onSuccess: async (_, a) => {
      notify({ tone: "success", title: `${name} ${ACTION_COPY[a].done}` });
      await invalidate(user.id);
      onClose();
    },
  });
  const copy = action ? ACTION_COPY[action] : null;
  return (
    <Dialog
      open={action !== null}
      onOpenChange={(open) => {
        if (!open) {
          mutation.reset();
          onClose();
        }
      }}
    >
      {copy && action ? (
        <DialogContent
          title={copy.title}
          description={copy.body(name, user)}
          footer={
            <>
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                variant={action === "reactivate" ? "default" : "destructive"}
                disabled={mutation.isPending}
                onClick={() => mutation.mutate(action)}
              >
                {copy.confirm}
              </Button>
            </>
          }
        >
          <p className="text-sm text-muted-foreground">This action takes effect immediately and is recorded in the audit log.</p>
          {mutation.isError ? <ErrorState error={mutation.error} className="mt-3" /> : null}
        </DialogContent>
      ) : null}
    </Dialog>
  );
}

export function ChangeRoleDialog({ user, me, open, onClose }: { user: UserOut; me: Me | undefined; open: boolean; onClose: () => void }) {
  const invalidate = useInvalidateUsers();
  const { notify } = useToast();
  const [role, setRole] = useState<RoleKey>(user.role_key);
  const mutation = useMutation({
    mutationFn: () => endpoints.updateUser(user.id, { role_key: role }),
    onSuccess: async () => {
      notify({ tone: "success", title: `${userName(user)} is now ${ROLE_LABELS[role]}` });
      await invalidate(user.id);
      onClose();
    },
  });
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          mutation.reset();
          setRole(user.role_key);
          onClose();
        }
      }}
    >
      <DialogContent
        title="Change role"
        description={`Choose the role for ${userName(user)}. Permissions change on their next request.`}
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button disabled={mutation.isPending || role === user.role_key} onClick={() => mutation.mutate()}>
              Save role
            </Button>
          </>
        }
      >
        <Field label="Role" htmlFor="change-role">
          <Select id="change-role" value={role} onChange={(e) => setRole(e.target.value as RoleKey)}>
            {assignableRoles(me).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </Select>
        </Field>
        {mutation.isError ? <ErrorState error={mutation.error} className="mt-3" /> : null}
      </DialogContent>
    </Dialog>
  );
}

export function AddUserDialog({ me, open, onClose }: { me: Me | undefined; open: boolean; onClose: () => void }) {
  const invalidate = useInvalidateUsers();
  const { notify } = useToast();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<RoleKey>("viewer");
  const reset = () => {
    setEmail("");
    setDisplayName("");
    setRole("viewer");
  };
  const mutation = useMutation({
    mutationFn: () => endpoints.inviteUser({ email: email.trim(), role_key: role, display_name: displayName.trim() || null }),
    onSuccess: async (created) => {
      notify({
        tone: "success",
        title: `${created.email} added`,
        description: "Ask them to sign in with their Microsoft work account to activate access.",
      });
      await invalidate();
      reset();
      onClose();
    },
  });
  const valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!o) {
          mutation.reset();
          reset();
          onClose();
        }
      }}
    >
      <DialogContent
        title="Add user"
        description="Only users added here can access the platform, even if they can sign in to Microsoft Entra ID."
        footer={
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" form="add-user-form" disabled={!valid || mutation.isPending}>
              Add user
            </Button>
          </>
        }
      >
        <form
          id="add-user-form"
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) mutation.mutate();
          }}
        >
          <Field
            label="Microsoft Entra email or UPN"
            htmlFor="add-user-email"
            hint="Must match the account they sign in with. Their access activates on first sign-in; the invitation expires after 30 days."
          >
            <Input
              id="add-user-email"
              type="email"
              autoComplete="off"
              placeholder="name@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </Field>
          <Field label="Display name (optional)" htmlFor="add-user-name" hint="Replaced by the name from Entra ID when they sign in.">
            <Input id="add-user-name" value={displayName} maxLength={200} onChange={(e) => setDisplayName(e.target.value)} />
          </Field>
          <Field label="Role" htmlFor="add-user-role">
            <Select id="add-user-role" value={role} onChange={(e) => setRole(e.target.value as RoleKey)}>
              {assignableRoles(me).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </Select>
          </Field>
          {mutation.isError ? <ErrorState error={mutation.error} /> : null}
        </form>
      </DialogContent>
    </Dialog>
  );
}
