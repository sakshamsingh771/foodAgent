# Roles & permissions

Single source of truth: `backend/app/core/security.py::ROLE_PERMS`. `/auth/login`, `/auth/refresh` and `/auth/me` return the caller's `permissions`; the frontend (`frontend/lib/rbac.ts`) derives navigation from them. The backend remains the security boundary: every endpoint uses `require(...)` and `get_owned`/`ensure_org` (404 across organizations).

| Capability (permission) | Admin | Ops Mgr | Recovery Mgr | Logistics | Recipient | Auditor |
|---|---|---|---|---|---|---|
| View lots (`lots:read`) | ✔ | ✔ | ✔ | ✔ | – | ✔ |
| Register lot (`lots:write`) | ✔ | ✔ | – | – | – | – |
| Adjust stock (`lots:adjust`) **new** | ✔ | ✔ | – | – | – | – |
| Create case / evidence (`cases:create`, `evidence:write`) | ✔ | ✔ | evidence only | – | – | – |
| Simulate allocation (`simulate`) | ✔ | – | ✔ | – | – | – |
| Approve/reject/replan/commit (`cases:approve`) | ✔ | – | ✔ | – | – | – |
| Close/cancel case (`cases:close`) | ✔ | – | ✔ | – | – | – |
| Schedule pickup (`pickups:schedule`) | ✔ | ✔ | – | – | – | – |
| Update pickup / transport (`pickups:write`) | ✔ | ✔ | – | assigned only | – | – |
| Respond to offers (`recipient:respond`) | – | – | – | – | own offers | – |
| Audit log (`audit:read`) | ✔ | – | ✔ | – | – | ✔ |
| Reports & CSV export (`reports:export`) **new** | ✔ | ✔ | ✔ | – | – | ✔ |
| AI Assistant (`ai:assistant`) | ✔ | ✔ | ✔ | – | – | ✔ |
| Manage users (`users:manage`), admin overview (`admin:overview`) **new overview / PATCH** | ✔ | – | – | – | – | – |

Other roles: none. `is_platform_admin` is the only cross-organization flag.

## Changes in this upgrade
- `PATCH /users/{id}` – role change / (de)activation; reason required, org-scoped, no self-lockout, last-admin protected, recipient role locked, refresh tokens revoked on deactivation, audited.
- `POST /lots/{id}/adjust`, `GET /lots/{id}/history` – row-locked stock adjustment; reason required; can't reach ≤0 or drop below reserved/open-case quantity; audited.
- `GET /reports/exceptions`, `/reports/{cases,inventory,pickups,exceptions}.csv` – org-scoped, CSV-injection-safe, each export audited.
- `GET /admin/overview` – users by role, pending approvals, exceptions, recent user-security events.
- Frontend: permission-aware nav, `/users`, `/reports`, inventory Adjust dialog (shown only with `lots:adjust`).
- AI Assistant: `/assistant` and `/api/v1/ai/*` are available only to roles with `ai:assistant`; Gemini context is organization-scoped and read-only.

## Not implemented (needs schema migration / larger scope)
Organization verification status & management UI, driver/vehicle fields, proof-of-delivery upload, partial-quantity acceptance beyond the existing allocation flow, Playwright E2E run (browsers not installed here).

## Onboarding, invitations & approval (auth upgrade)
- **Join**: admin creates an invitation (`POST /invitations`, `users:manage`) for an email + role. The raw token is returned once (link `/register?invite=…`); only its hash is stored. Joining requires the same email, an unexpired, unrevoked, unused invitation. Role and organization are taken from the invitation, never from the request. Optional `requires_approval` leaves the new user `PENDING` until an org admin approves (`POST /users/{id}/approve|reject`).
- **Create organization**: public sign-up creates the organization with a `PENDING` account that has no permissions. It becomes ADMIN only via the protected setup code (`FIRST_ADMIN_SETUP_TOKEN`), a platform administrator (`/platform/registrations/*`), or the operator CLI `python -m app.manage approve-admin <email>`.
- **Recipients**: public self-registration as a recipient is not offered (a recipient account must be linked to a recipient record, which only an invitation from the owning organization can do via the API: `role=RECIPIENT`, `recipient_id`).
- **Account status**: `ACTIVE`, `PENDING`, `REJECTED`, `DISABLED`; only `ACTIVE` accounts can sign in or call protected endpoints (`ACCOUNT_PENDING` 403, disabled 401/403).
- **Home routes** (from backend-verified role): Admin `/dashboard`, Operations `/operations`, Recovery `/recovery`, Logistics `/logistics`, Recipient `/recipients`, Auditor `/compliance`.
- Every invitation, acceptance, approval, rejection, role change and (de)activation is written to the hash-chained audit log with actor, target and before/after.
