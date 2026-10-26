# API
Interactive OpenAPI at `/docs` and `/openapi.json`. Base path `/api/v1`. Bearer JWT. Errors:
`{"error":{"code":"RECOVERY_CASE_NOT_FOUND","message":"…","request_id":"…","details":[…]}}`.

| Area | Endpoints |
|---|---|
| auth | `POST /auth/register` (`mode`: `create_org`\|`join`), `/auth/login`, `/auth/refresh` (rotating), `/auth/logout`; `GET /auth/me`, `/auth/invitation?token=`, `/auth/demo-accounts` (non-production) |
| onboarding | `POST/GET /invitations`, `POST /invitations/{id}/revoke`, `GET /users?q=&role=&status=`, `POST /users/{id}/approve\|reject`, `GET /platform/registrations`, `POST /platform/registrations/{id}/approve\|reject` |
| inventory | `GET/POST /lots`, `GET /lots/{id}`, `GET /products`, `GET /plants` (paginated, filter by status/urgency/plant/product/q, sort) |
| recovery | `GET/POST /recovery-cases`, `GET /{id}`, `POST /{id}/approve｜reject｜replan｜cancel｜simulate｜evidence`, `GET /{id}/evidence/{eid}/file` |
| allocation | `GET /recovery-cases/{id}/allocations`, `POST /recovery-cases/{id}/allocation/plan｜compare｜simulate｜commit｜approve`, `POST /allocations/{id}/cancel｜transport｜handover`; recipient role: `GET /recipient/allocations`, `POST /recipient/allocations/{id}/respond` (see `ALLOCATION.md`) |
| recipients | `GET /recipients`; recipient role: `GET /recipient/cases`, `POST /recipient/cases/{id}/respond` |
| logistics | `GET /pickups`, `POST /recovery-cases/{id}/pickup`, `PATCH /pickups/{id}/status`, `POST /pickups/{id}/delay｜handover` |
| insights | `/dashboard/summary`, `/sustainability/summary`, `/sustainability/export.csv`, `/plant/overview`, `/planning/forecast` |
| compliance | `GET/POST /compliance/documents`, `/audit`, `/audit/verify`, `/audit/export.csv` |
| scenarios | `/scenarios/catalog｜targets｜preview｜apply｜reset` |
| other | `/notifications` (+`/read`, `/read-all`), `/events/stream` (SSE), `/search`, `/users`, `/organizations/current`; `GET /health` |

Permissions are enforced per endpoint via `require(...)`; see `core/security.py` (`ROLE_PERMS`).
