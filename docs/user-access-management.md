# User access management

Access to the platform is **admin-controlled**. Two separate checks decide whether a request is allowed:

| Question | Answered by | Where |
| --- | --- | --- |
| Who is this? (identity) | Microsoft Entra ID: a valid, signed access token | `app/core/security.py` |
| May they use the platform? (authorisation) | The `users` table: an approved user with status `active`, then the role's permissions | `app/services/authentication/users.py`, `app/api/deps.py` |

Being able to sign in to the Entra tenant does **not** grant access. Someone who authenticates successfully but has not been added by an administrator gets `403 ACCESS_NOT_GRANTED`, and the SPA shows the "Access not granted" page.

## 1. How sign-in works

```
Browser ── MSAL (PKCE) ──> Entra ID ── access token ──> FastAPI
                                                        │
                    1. validate token: RS256 signature, iss, aud, exp/nbf/iat,
                       tid in the allow-list, scope or app role        → 401 if invalid
                    2. organisation = the one linked to the token's tid
                    3. user = (organisation, tid, oid)
                         found  → check status
                         absent → bootstrap Super Admin? / pending invitation?
                    4. status must be active                           → 403 ACCESS_NOT_GRANTED
                                                                         (403 ACCESS_SUSPENDED)
                    5. the route's permission                          → 403 PERMISSION_DENIED
```

Steps 2 to 4 run in `get_current_user`, which every protected route depends on, so they cannot be skipped by calling the API directly. A test (`test_every_protected_route_enforces_membership`) calls every route as an unapproved user and expects `ACCESS_NOT_GRANTED`. The only public API route is `GET /auth/config`.

The check runs on **every request**, so suspending or deactivating a user takes effect on their next API call. The SPA then drops its cached data and shows the access page.

### Identity binding

- The permanent identity key is **`(organization_id, entra_tenant_id, entra_object_id)`**, enforced by the unique index `uq_users_identity`. The Entra object ID (`oid`) is immutable for a user in a tenant.
- Email (`preferred_username`) is profile data only. It is refreshed from each token and is used for one thing: matching a **pending** invitation that has no `oid` yet.
- Once an invitation is activated, the `oid` is bound permanently. If someone else later presents the same email with a different `oid` (for example a recycled or renamed UPN), they are refused (`IDENTITY_MISMATCH` in the audit log). If the bound user's email changes in Entra, access continues.

## 2. Creating the first Super Admin (bootstrap)

The first person to sign in does **not** become an administrator. The first Super Admin is set in deployment configuration, which application users cannot change and the frontend never sees.

1. Find your Entra object ID: Entra admin centre > Users > your user > **Object ID**. Alternatively run `az ad signed-in-user show --query id -o tsv`.
2. Set the backend variable (an App Setting or Container Apps environment variable):

   ```
   BOOTSTRAP_SUPER_ADMIN_OIDS=<your-object-id>
   ```

   An entry without a tenant applies to the home tenant (`ENTRA_TENANT_ID`). For another allowed tenant, use `<tenant-id>/<object-id>`. Several entries can be comma-separated.
3. Deploy or restart the API, then sign in. You are created as an active Super Admin, recorded as `user.bootstrapped` in the audit log.
4. Optionally, remove the variable afterwards. It is ignored anyway once the organisation has an active Super Admin.

Safeguards:

- Values are validated at start-up. They must be GUIDs, and the tenant must be one that is allowed to sign in, otherwise the API refuses to start.
- The token must come from the configured tenant **and** carry the configured `oid`. The same `oid` presented from a different tenant does not match.
- Bootstrap only acts while the organisation has **no active Super Admin**. While one exists, listed identities are treated like everyone else and need an invitation.
- If the listed identity already exists as an **active** user, it is promoted to Super Admin. A suspended or deactivated user is never re-enabled by configuration.

## 3. Adding a user

Settings > Users (or **Users** in the sidebar) > **Add user**. Alternatively call `POST /api/v1/users/invite`.

1. Enter the user's Microsoft Entra email or UPN. It must be the account they sign in with. Optionally add a display name, and choose a role.
2. The user is created with status **Invited** (`pending`). No Entra object ID is stored yet.
3. Tell the user to open the platform and sign in with their work account. No email is sent: the platform has no mail provider, and invitation email is a possible future extension.

Invitations expire after **30 days**. Adding the same email again refreshes the invitation and updates its role. An email that already belongs to an active, suspended or deactivated user is rejected with `409 USER_EXISTS`; reactivate that user instead.

The platform does not query Microsoft Graph. Admins type the email rather than picking from the directory, so the API needs no directory read permissions. The object ID is learned safely from the user's own signed token.

## 4. How an invitation is activated

On the user's first successful sign-in, if no user matches `(organisation, tenant, oid)`, the API looks for a pending invitation with:

- the same organisation (the one linked to the token's `tid`),
- the same tenant ID,
- the same email, compared case-insensitively,
- no bound object ID, and not expired.

If one is found, the API stores the token's `oid`, sets the status to `active` and records `user.activated`, and the request proceeds. An invitation can never be redeemed from another tenant, even with the same email, because the organisation and tenant must both match.

## 5. Suspending a user

User actions menu > **Suspend**, or `POST /api/v1/users/{id}/suspend`. This applies only to active users. The user's next request is refused with `ACCESS_SUSPENDED`, and they see "Your access ... has been temporarily suspended". Their account, role and history are kept.

## 6. Reactivating a user

**Reactivate**, or `POST /users/{id}/reactivate`, takes a suspended or deactivated user back to `active` with their previous role. A revoked invitation that was never redeemed goes back to `pending`, with a new 30-day expiry.

## 7. Deactivating a user (removing access)

**Deactivate**, or `POST /users/{id}/deactivate`, removes access permanently until an administrator reactivates the user. For a pending invitation, the menu shows **Revoke invitation**. Users are **never deleted**. The row, the `deactivated_at` timestamp and all audit entries are kept, so the audit trail stays intact. There is no hard-delete endpoint.

## 8. Roles

Roles reuse the existing model (`app/core/permissions.py`). See [api.md](api.md#roles-and-permissions) for the full permission matrix.

| Role | Can manage users |
| --- | --- |
| Super Admin | Yes (`users:manage`) |
| Admin | No |
| Operator | No |
| Viewer | No |

Rules enforced by the API, regardless of the UI:

1. Nobody can change their own role or status (`SELF_MODIFICATION`).
2. Nobody can assign a role above their own, or manage a user ranked above them. Therefore only a Super Admin can create, change or remove a Super Admin, and an Admin could never promote themselves even if given `users:manage`.
3. The organisation always keeps **at least one active Super Admin**. The last one cannot be demoted, suspended or deactivated (`409 LAST_SUPER_ADMIN`). The check locks the Super Admin rows, so two concurrent changes cannot both pass.
4. If the token carries Entra app roles (`Monitoring.*`, see [entra-id.md](entra-id.md)), they decide the role of an **already approved** user, and the role cannot be edited in-app. App roles **never** grant access by themselves.

## 9. Tenant restriction

- Only tokens whose `tid` is `ENTRA_TENANT_ID` or listed in `ENTRA_ALLOWED_TENANTS` are accepted. Other tenants are rejected with `401` **before** any key download or database lookup.
- For a single-company deployment, set only `ENTRA_TENANT_ID` and leave `ENTRA_ALLOWED_TENANTS` empty.
- Each allowed tenant maps to exactly one organisation. Users, invitations, projects and resources are scoped to it, and a Super Admin in one organisation cannot see or change users in another (`404`).
- Organisations are no longer created automatically for arbitrary sign-ins. Only the bootstrap identity (or development mode) creates the organisation for its tenant.

## 10. Security model

| Concern | Control |
| --- | --- |
| Entra login alone grants access | Membership and `active` status are checked server-side on every request |
| Email reuse or rename | Access is bound to `tid` + `oid`. Email matches only unbound invitations |
| Cross-tenant invitation redemption | The organisation and tenant must both match the invitation |
| Insecure first-admin bootstrap | Configuration-only, tenant-validated, and inert once an active Super Admin exists |
| Privilege escalation | Rank rules, no self-modification, last-Super-Admin protection, all in FastAPI |
| User enumeration | One generic `ACCESS_NOT_GRANTED` response for every refusal reason (unknown, deactivated, expired invitation, identity mismatch). There is no unauthenticated "is this email registered?" endpoint |
| Probing and abuse | Per-IP limit on failed authentications and access denials (`RATE_LIMIT_AUTH_FAILURES_PER_MINUTE`, default 30), plus the per-user request limit |
| Audit flooding | A refused identity is audited at most once per reason every 10 minutes |
| Development bypass | `AUTH_MODE=dev` is refused at start-up unless `ENVIRONMENT` is `development` or `test` |
| Tokens | Never logged, audited or stored. MSAL caches them in `sessionStorage` |

### Audit events

| Event | When | Notes |
| --- | --- | --- |
| `user.invited` | User added, or invitation refreshed | `details.reinvite` |
| `user.activated` | Invitation redeemed on first sign-in | |
| `user.bootstrapped` | First Super Admin provisioned from configuration | |
| `user.suspended`, `user.reactivated`, `user.deactivated` | Status changes | `details.from`, `details.to` |
| `user.role_changed` | Role change | `details.from`, `details.to` |
| `user.login_allowed` | Interactive sign-in (`POST /auth/session`) or a resumed session after 5 minutes of inactivity | IP address and user agent |
| `user.login_denied` | Refused on `/auth/me` or `/auth/session` | `details.reason`, tenant ID, object ID |
| `user.access_denied` | Refused on any other API call | Same as above |

Denial reasons (audit only, never returned to the caller): `USER_NOT_FOUND`, `INVITATION_EXPIRED`, `IDENTITY_MISMATCH`, `USER_SUSPENDED`, `USER_DEACTIVATED`. Tokens from a tenant that is not allowed are rejected during token validation and logged as `token_tenant_rejected` (reason `TENANT_MISMATCH`) in the application log, not the audit log, because their signature is never verified.

## 11. Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| "Access not granted" after a successful Microsoft sign-in | The user was never added, the invitation expired or was revoked, or the user was deactivated | Settings > Users: add the user, re-add them to refresh the invitation, or reactivate them. Check `user.login_denied` in the audit log for the reason |
| Invited user still sees "Access not granted" | They signed in with a different account from the invited email or UPN (for example a personal account or an alias) | Check the "Signed in as" value on the access page and invite exactly that UPN |
| A user whose UPN was reassigned to a new person is refused | Expected: access is bound to the original `oid` | Deactivate the old user, then invite the new person |
| "Access suspended" | An administrator suspended the user | Reactivate them |
| Nobody can sign in after deployment, and there are no users | No bootstrap configured | Set `BOOTSTRAP_SUPER_ADMIN_OIDS` (section 2) and restart |
| Bootstrap identity is refused | An active Super Admin already exists, the token is from another tenant, or the object ID is wrong | Ask the existing Super Admin to invite you. Check the object ID and tenant |
| API refuses to start with a `BOOTSTRAP_SUPER_ADMIN_OIDS` error | An entry is not a GUID, the tenant is not allowed, or `ENTRA_TENANT_ID` is missing for a bare entry | Fix the value |
| `409 LAST_SUPER_ADMIN` | Attempt to demote or remove the only active Super Admin | Promote another user to Super Admin first |
| `429 RATE_LIMITED` during sign-in | Many failed or refused requests from one IP | Wait a minute. Raise `RATE_LIMIT_AUTH_FAILURES_PER_MINUTE` if many users share one egress IP |

## Upgrading an existing deployment

Migration `7c1f4b2a9d30` replaces `is_active` with `status`. Existing users keep their access: `is_active=true` becomes `active` and `false` becomes `deactivated`. Before this change, every user who signed in was created automatically as a Viewer, so **review the user list after upgrading** and deactivate anyone who should not have access. Downgrading deletes pending invitations, because the previous schema requires an object ID.
