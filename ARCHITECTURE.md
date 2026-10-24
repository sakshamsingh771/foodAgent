# Architecture
```
Next.js (web) ──REST + SSE──> FastAPI (api) ──SQLAlchemy──> PostgreSQL
                                   ▲                              ▲
                  worker / simulator (separate containers) ───────┘
```
**Backend layers** (`backend/app`): `api/` thin routers (auth, validation, serialization) → `services/` business logic and side effects (cases, scenarios, audit, events) → `models/`. The scoring logic in `services/recovery_engine.py` is **pure** (no DB), so it is unit-tested directly.

**Recovery flow:** lot → `create_case` (engine scores R1–R4) → manager `approve` (human) → recipient `accept/decline` (decline auto-replans without that recipient) → `schedule_pickup` → status transitions → `confirm_handover` → sustainability metric. Every step writes an audit event and an outbox event.

**Real-time:** services write to `event_outbox`; `GET /events/stream` tails it. Because the table is shared, events from the API, worker and simulator all reach browsers. The web app reads the stream with `fetch` so the JWT stays in an `Authorization` header, never a URL. It reconnects with backoff and shows Live / Reconnecting.

**Org isolation:** every record carries `org_id`; `get_owned()` returns 404 across orgs. Recipients are scoped by `recipient_id`.

**Methods are labelled everywhere:** RULE (eligibility, freshness), STATISTICAL (acceptance from history, seeded forecasts), SIMULATED (what-if, scenarios). There is no ML or LLM in the decision path.

**Frontend:** App Router, a central API client (`lib/api.ts`: refresh-on-401, structured errors), TanStack Query for all data, SSE events invalidate query keys, shared `QueryBoundary` gives every screen loading/empty/error states.
