# Microsoft Entra ID

Sign-in uses two app registrations: one for the API and one for the single-page application. The SPA uses MSAL (authorisation code flow with PKCE, redirect flow, `sessionStorage` token cache) to obtain an access token for the API. The API validates that token on every request.

## 1. API app registration

1. Register an application, for example "Monitoring Platform API". It has no redirect URI and needs no client secret.
2. **Expose an API.** Set the Application ID URI (for example `api://<api-client-id>`) and add the delegated scope `access_as_user`.
3. **Manifest.** Set `"accessTokenAcceptedVersion": 2` (on the new manifest schema, `api.requestedAccessTokenVersion: 2`). The backend accepts only v2.0 issuers (`https://login.microsoftonline.com/<tenant>/v2.0`).
4. **App roles** (allowed member types: users/groups). Create these, with the value exactly as shown:

   | Value | Platform role |
   | --- | --- |
   | `Monitoring.SuperAdmin` | Super Admin |
   | `Monitoring.Admin` | Admin |
   | `Monitoring.Operator` | Operator |
   | `Monitoring.Viewer` | Viewer |

5. Optional: in Enterprise applications, assign users or groups to the roles. Optionally set "Assignment required" so that only assigned users can obtain tokens. This is defence in depth: whether or not you do this, a user must also be added in the platform (Settings > Users) before they can use it.

## 2. SPA app registration

1. Register "Monitoring Platform Web" with platform type **Single-page application**. Add a redirect URI for each origin, for example `https://monitoring.example.com` and `http://localhost:5173` for development.
2. Under API permissions, add the delegated permission `access_as_user` from the API registration, then grant admin consent.

## Configuration

### Backend

| Variable | Example / default | Meaning |
| --- | --- | --- |
| `AUTH_MODE` | `entra` (default) | `dev` is refused outside development and test |
| `ENTRA_TENANT_ID` | `<tenant-guid>` | Home tenant; always allowed |
| `ENTRA_CLIENT_ID` | `<api-client-id>` | API registration client ID |
| `ENTRA_AUDIENCE` | `api://<api-client-id>` | Required `aud` claim |
| `ENTRA_REQUIRED_SCOPE` | `access_as_user` (default) | Required in `scp` for delegated tokens |
| `ENTRA_ALLOWED_TENANTS` | empty | Extra tenants allowed to sign in, comma-separated |
| `ENTRA_AUTHORITY_HOST` | `https://login.microsoftonline.com` | Authority used for JWKS and issuer |
| `BOOTSTRAP_SUPER_ADMIN_OIDS` | empty | First Super Admin: `<object-id>` (home tenant) or `<tenant-id>/<object-id>`. Ignored once an active Super Admin exists. See [user-access-management.md](user-access-management.md#2-creating-the-first-super-admin-bootstrap) |
| `RATE_LIMIT_AUTH_FAILURES_PER_MINUTE` | `30` | Failed authentications and access denials tolerated per client IP per minute |

With `AUTH_MODE=entra`, the application refuses to start unless `ENTRA_TENANT_ID`, `ENTRA_CLIENT_ID` and `ENTRA_AUDIENCE` are set. The only exception is the test environment.

`GET /api/v1/auth/config` is public and returns only non-secret values: auth mode, tenant ID, client ID, API scope and authority.

### Frontend (build-time)

| Variable | Example |
| --- | --- |
| `VITE_AUTH_MODE` | `entra` |
| `VITE_ENTRA_CLIENT_ID` | `<spa-client-id>` |
| `VITE_ENTRA_TENANT_ID` | `<tenant-guid>` |
| `VITE_ENTRA_API_SCOPE` | `api://<api-client-id>/access_as_user` |
| `VITE_ENTRA_REDIRECT_URI` | `https://monitoring.example.com` (defaults to the page origin) |
| `VITE_API_BASE_URL` | `/api/v1` (default, same origin) |

These values are identifiers, not secrets. The SPA never receives Azure credentials.

## What the backend validates

Implemented in `app/core/security.py`:

| Check | Detail |
| --- | --- |
| Algorithm | `RS256` only. `none` and symmetric algorithms are rejected |
| Signature | Signing keys come from `<authority>/<tid>/discovery/v2.0/keys`. They are cached for one hour and refreshed when an unknown `kid` appears (key rotation) |
| Tenant | `tid` must be `ENTRA_TENANT_ID` or appear in `ENTRA_ALLOWED_TENANTS` |
| Issuer | `iss` must equal `<authority>/<tid>/v2.0` |
| Audience | `aud` must equal `ENTRA_AUDIENCE` |
| Lifetime | `exp`, `nbf` and `iat` are validated with 60 seconds of leeway |
| Required claims | `exp`, `iat`, `nbf`, `aud`, `iss`, `tid` and `oid` must be present |
| Authorisation to call the API | `scp` contains `ENTRA_REQUIRED_SCOPE`, or the token carries app roles |

Failures return `401 UNAUTHENTICATED` (or `TOKEN_EXPIRED`), or `403 PERMISSION_DENIED` when the scope or role is missing. Tokens are never logged, stored or returned by the API. Repeated failures from one IP are rate limited (`429`).

A valid token proves identity only. Access to the platform is then decided by the `users` table; see the next section.

## Platform access and roles

Entra ID authentication does **not** grant access on its own. After the token is validated, the API looks up an **approved, active** user by `(organisation, tid, oid)`. Unknown identities get `403 ACCESS_NOT_GRANTED`, and nothing is created for them. Users are added by a Super Admin as invitations (by email or UPN) and are bound to their `oid` on first sign-in. The first Super Admin comes from `BOOTSTRAP_SUPER_ADMIN_OIDS`. The full process is in [user-access-management.md](user-access-management.md).

Role precedence for an approved user:

1. **Entra app roles are authoritative when present.** The highest assigned platform role is applied on every request, and the user is marked `role_managed_by_entra`, so the role cannot be edited in the app. App roles never grant membership.
2. If a user previously had Entra-managed roles and the token no longer carries any, the user is **downgraded to Viewer**.
3. Otherwise the role assigned in the platform applies (set when the user is added, changed under Settings > Users). Nobody can assign a role above their own or change their own role, and the last active Super Admin cannot be demoted.

The SPA calls `POST /api/v1/auth/session` once after an interactive sign-in, which records `user.login_allowed`. The same event, with trigger `session_resumed`, is recorded when a user returns after more than five minutes of inactivity.

### What to test in a real tenant

The automated tests use RS256 tokens signed with a test key and served from a mocked JWKS endpoint. They do not exercise a real tenant. After configuring the registrations, verify manually:

1. The bootstrap Super Admin can sign in and sees the Users page.
2. A tenant user who has not been added sees "Access not granted" (check `user.login_denied` in the audit log).
3. An invited user is activated on first sign-in. Check that `preferred_username` in their token equals the invited UPN. For guests (B2B) it is usually their home email.
4. A suspended user is refused on their next request.
5. A token from a tenant that is not allowed is rejected with `401`.
