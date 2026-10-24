# Product audit (honest status)
Greenfield build. "Verified" = executed in the build sandbox. "Not verified" = written but not run here.

## Verified
- Backend: 31 pytest tests pass on **SQLite and on real PostgreSQL** (auth, rotation, RBAC, org isolation, validation, pagination, full recovery workflow, decline→replan, uploads, scenarios+reset, audit tamper detection, notifications, exports).
- Alembic migration applies on Postgres; `alembic check` shows no drift; seed loads on Postgres.
- Live API on Postgres: health, login, SSE stream delivered scenario/notification events to the correct user, CORS and security headers.
- Frontend: `tsc --noEmit` clean; `next build` succeeds (19 routes).

## Not verified here
- `docker compose up` (no Docker in the sandbox): Dockerfiles/compose are written but unexecuted.
- Playwright E2E, axe accessibility run, Lighthouse scores, real-device/360px layout checks (browser download blocked). Specs are in `frontend/e2e/`; run them locally. No accessibility score is claimed.
- Frontend ↔ backend in a browser (each side verified independently; contract shared via typed client).

## Checklist
Implemented: Freshness Ring, Recovery Ladder, Confidence meter with "Why?", method badges, What-if simulator, Live Operations (SSE, Live/Reconnecting), recovery cases (approve/reject/replan/cancel, evidence, timeline), recipient flow (EN/HI), logistics statuses + delays, plant ops, planning (P50/P80/backtest), sustainability (charts, CSV), compliance + hash-chained audit with verify, scenario control, notifications, global search (Ctrl/Cmd+K), light/dark/system, responsive shell with bottom nav, RBAC, auth with refresh rotation.
Partial / not done: PDF export, maps, dedicated ProductionPlan/SystemSetting entities, LLM explanation layer, performance tuning against Lighthouse targets, frontend unit tests. See ASSUMPTIONS.md.


## Allocation optimizer update (this iteration)
IMPLEMENTED AND VERIFIED (executed here):
- Multi-recipient optimizer, strategy comparison, read-only what-if scenarios, atomic quantity reservation, idempotent rejection, partial acceptance, transport delay/failure replanning, per-slice handover, audit events, role checks. See `ALLOCATION.md`.
- Backend: 72 pytest tests pass on SQLite **and on a real PostgreSQL 16** (includes threaded concurrency tests, duplicate-event tests and a brute-force optimality check). Migration `0002` applies, downgrades and re-applies on PostgreSQL; `alembic check` reports no drift; seed loads.
- Frontend: `tsc --noEmit` clean and `next build` succeeds with the new allocation panel and split-lot recipient offers. `package-lock.json` was out of sync with `package.json` (`npm ci`, used by the Dockerfile, failed); it is regenerated.
- Simulated benchmark: `BENCHMARK.md`.

NOT TESTED / NOT DONE:
- `docker compose up` (no Docker daemon here), Playwright E2E of the new panel, browser verification of the UI against the live API.
- PDF export, maps/routing, LLM explanations (explanations are deterministic rule-based text), statistical/ML prediction from history (no real historical data exists; scoring stays heuristic).
- Seed additions for the ten demo scenarios: the existing 12-lot seed is unchanged; the scenarios are exercised by the automated tests instead.
- Alternative-vehicle selection (no transport fleet model exists).
