# Deployment
1. Provision PostgreSQL 16 and set `DATABASE_URL`.
2. Set `ENVIRONMENT=production`, strong `JWT_SECRET` / `JWT_REFRESH_SECRET` (32+ chars), `CORS_ORIGINS` (the web origin), and build the web image with `NEXT_PUBLIC_API_URL` pointing at the public API URL (it is baked in at build time).
3. Run `docker compose up -d --build` (the api container applies migrations on start). Put a TLS-terminating reverse proxy in front; disable proxy buffering for `/api/v1/events/stream`.
4. Run **one** `worker`. Leave `SIMULATOR_ENABLED=false` outside demos. Never run `python -m app.seed` in production.
5. Back up the `pgdata` and `uploads` volumes. Scale the API horizontally only after moving login rate limiting to a shared store.

## Auth upgrade
Run `docker compose exec api alembic upgrade head` (adds migration `0003`: user status/approval columns, `invitations` table; existing users are kept, deactivated users become `DISABLED`). Set `JWT_SECRET`, `JWT_REFRESH_SECRET`, `ENVIRONMENT=production`, `APP_URL`, and either `FIRST_ADMIN_SETUP_TOKEN` or use `python -m app.manage approve-admin <email>` for the first administrator. No email service is wired in: invitation links are shown to the admin to share.
