# foodAgent Project Audit

## Scope

This audit records the implementation state of the existing foodAgent application after the Gemini, navigation, authentication-hardening, and documentation updates. It is based on the repository, automated tests, and production frontend build.

## Architecture

- Frontend: Next.js 14, TypeScript, TanStack Query, Tailwind, Radix UI.
- Backend: FastAPI, SQLAlchemy 2, Pydantic v2, Alembic.
- Database: PostgreSQL in Docker; SQLite-backed tests are available.
- Authentication: JWT access and rotating refresh tokens, database-backed active-account checks.
- Authorization: backend `ROLE_PERMS`, endpoint permission dependencies, organization ownership checks.
- AI: official `google-genai` SDK, server-side only, structured JSON validation.

## Verified feature inventory

| Area | Status | Evidence / limitation |
|---|---|---|
| Authentication and refresh-token rotation | Working and verified | Backend authentication tests pass. |
| Role permissions and organization checks | Working and verified for current endpoints | Direct API role and cross-organization tests pass. |
| Role-specific dashboards and navigation | Working and verified by build/tests | Frontend routes are permission-filtered; backend remains authoritative. |
| Inventory and freshness | Working and verified | Existing API and allocation tests pass. |
| Recovery cases and evidence | Working and verified for current lifecycle | State checks, audit events, and evidence validation are covered by tests. |
| Allocation optimizer | Working and verified | Unit, API, reservation, rejection, and replan tests pass. |
| Pickup and handover workflow | Working and verified for current state model | Transition and regression tests pass. |
| Scenario simulation | Partially implemented but guarded | Auditors can read catalog/preview; only `scenarios:run` roles can apply/reset. Simulation is audited and resettable. |
| Reports and analytics | Working for current endpoints | Organization filters and export tests exist; some metrics are explicitly estimates. |
| Notifications and live events | Implemented for current workflows | Provider-backed email/SMS/push delivery is not claimed. |
| Gemini AI Assistant | Implemented and build-verified | Live provider call remains dependent on valid external credentials/model. |
| PostgreSQL migration/deployment verification | Partially verified | Compose configuration validates; full live Docker stack and migration run require Docker/database runtime. |
| Full browser E2E | Not fully verified | Requires Playwright browsers and running services. |

## Root causes fixed

1. `/assistant` existed but was absent from role-aware navigation, so the app shell redirected permitted users to `/unauthorized`.
2. Docker Compose did not pass `GEMINI_API_KEY` and `GEMINI_MODEL` to backend services.
3. Frontend AI response types were missing, causing the production frontend build to fail.
4. A malformed JWT subject could raise an unhandled `ValueError`; it now returns `TOKEN_INVALID`.
5. README referenced missing Gemini documentation; `AI.md` now documents configuration and endpoints.
6. A stale role test expected 401 for a disabled account while the established API contract returns 403 `ACCOUNT_DISABLED`.

## Important domain decision

`Recipient.org_id` identifies the partner organization that owns the recipient. Recovery cases belong to donor/plant organizations and intentionally match against partner recipients in other organizations. Therefore, recipient matching must not require `recipient.org_id == case.org_id`; doing so would disable the seeded donation-to-NGO workflow. Case, lot, allocation, pickup, report, and AI records remain organization-scoped to the case owner, while authorized partner recipient data is used for matching.

## Remaining limitations

- A formal donor-to-partner relationship/visibility model is not represented by the current schema. Adding one would require a product decision and migration; it was not invented as part of this pass.
- The live Gemini provider call was not executed without a valid, rotated key and confirmed supported model.
- Full Docker runtime, PostgreSQL migration, and Playwright browser tests require the corresponding local services/runtime.
