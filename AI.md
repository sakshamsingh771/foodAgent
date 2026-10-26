# Gemini AI Assistant

The AI Assistant is a read-only, organization-scoped explanation layer. It uses the official `google-genai` SDK on the backend and does not create allocations, change recovery cases, or bypass the deterministic optimizer.

## Configuration

Set these variables in the root `.env` file:

```env
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-3.1-flash-lite
```

The variables are passed to the API container by `docker compose`. Never use a `NEXT_PUBLIC_` prefix for the key.

## Frontend

Users with the `ai:assistant` permission can open:

```text
http://localhost:3000/assistant
```

The page is also available as **AI Assistant** in the authenticated sidebar for administrators, operations managers, recovery managers, and auditors.

## Backend endpoints

All endpoints require authentication and the `ai:assistant` permission:

- `GET /api/v1/ai/status`
- `POST /api/v1/ai/chat`
- `POST /api/v1/ai/recommendations`
- `POST /api/v1/ai/failures`
- `POST /api/v1/ai/summary`
- `POST /api/v1/ai/allocation/explain`

The allocation explanation endpoint also requires `cases:read` and verifies organization ownership of the case.

## Safety and failure behavior

The backend builds a minimal context from the authenticated user's organization. It does not send passwords, tokens, phone numbers, or cross-organization records to Gemini. Model output must be JSON matching the validated response schema; malformed output, timeouts, quota errors, invalid credentials, and unavailable models return explicit API errors rather than mock answers.

AI recommendations are suggestions only. Human approval and existing recovery workflow authorization remain required.
