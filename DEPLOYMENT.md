# Deployment
1. Provision PostgreSQL 16 and set `DATABASE_URL`.
2. Set `ENVIRONMENT=production`, strong `JWT_SECRET` / `JWT_REFRESH_SECRET` (32+ chars), `CORS_ORIGINS` (the web origin), and build the web image with `NEXT_PUBLIC_API_URL` pointing at the public API URL (it is baked in at build time).
3. Run `docker compose up -d --build` (the api container applies migrations on start). Put a TLS-terminating reverse proxy in front; disable proxy buffering for `/api/v1/events/stream`.
4. Run **one** `worker`. Leave `SIMULATOR_ENABLED=false` outside demos. Never run `python -m app.seed` in production.
5. Back up the `pgdata` and `uploads` volumes. Scale the API horizontally only after moving login rate limiting to a shared store.
