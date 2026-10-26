# foodAgent — Intelligent Food Recovery & Redistribution Platform
*Turn surplus into recovery.*

foodAgent finds the best recovery pathway for surplus food **before** it is lost:
**Food at risk → Assess → Recommend → Verify (human) → Recover → Track → Measure impact.**

> foodAgent provides decision support and workflow assistance. It does **not** certify food as safe for human consumption. A person approves every plan.

## Stack
Next.js 14 · TypeScript · Tailwind · Radix · TanStack Query · React Hook Form + Zod · Recharts · Framer Motion · next-themes —
FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2 · PostgreSQL 16 · JWT + RBAC · SSE · Docker Compose.

## Quick start
```bash
cp .env.example .env          # then set JWT_SECRET and JWT_REFRESH_SECRET (see file)
make demo                     # build, migrate, load demo data
# web  http://localhost:3000     api  http://localhost:8000/docs
```
Demo logins are in [DEMO.md](DEMO.md) (password `FoodAgent#2026demo`, demo data only).

Without Docker:
```bash
cd backend && pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://user:pass@localhost/foodagent JWT_SECRET=... JWT_REFRESH_SECRET=...
alembic upgrade head && python -m app.seed && uvicorn app.main:app --reload
cd ../frontend && npm ci && NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## Commands
`make up|down|build|migrate|seed|demo|test|lint|format|logs`
Tests: `cd backend && pytest app/tests -q` (SQLite by default; set `TEST_DATABASE_URL` to run on Postgres). E2E + axe: `cd frontend && npx playwright install && npm run test:e2e` with the stack running.

## Environment variables
See `.env.example`. Required: `JWT_SECRET`, `JWT_REFRESH_SECRET` (production refuses dev/weak values), `DATABASE_URL`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`. `GEMINI_API_KEY` and `GEMINI_MODEL` enable the server-side AI assistant; the feature reports a truthful unavailable state when they are empty. `LLM_API_KEY` is legacy and optional.

## Docs
[ARCHITECTURE](ARCHITECTURE.md) · [API](API.md) · [DATABASE](DATABASE.md) · [SECURITY](SECURITY.md) · [DEPLOYMENT](DEPLOYMENT.md) · [DEMO](DEMO.md) · [ASSUMPTIONS](ASSUMPTIONS.md) · [PRODUCT_AUDIT](PRODUCT_AUDIT.md) · [Project audit](docs/PROJECT_AUDIT.md) · [Role matrix](docs/ROLE_PERMISSION_MATRIX.md)

AI assistant (Gemini): see [AI.md](AI.md).
