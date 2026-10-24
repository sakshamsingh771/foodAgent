# Security
- bcrypt password hashing; password policy (10+ chars, letters+digits); constant-time-ish login (hash always checked).
- Short-lived access JWT (15 min) + rotating refresh tokens stored as SHA-256 digests, revocable on logout.
- RBAC at the API (`require(...)`) and org isolation on every query; cross-org access returns 404.
- Pydantic validation on every body; SQL via ORM only.
- Uploads: extension allow-list, content-type match, magic-byte check for images/PDF, 10 MB cap, random on-disk names, SHA-256 stored, `nosniff` + attachment on download.
- Login rate limiting (per-process; use a shared store when scaled out). CORS allow-list. Security headers on API and web.
- Production refuses default/weak JWT secrets. No secrets in the repo; `.env` is git-ignored.
- Tamper-evident audit log (hash chain) with a verify endpoint. Logs are structured JSON with request IDs and never include passwords or tokens.
- Tokens are kept in `localStorage` for simplicity; move to httpOnly cookies + CSRF protection before a hardened production rollout.
