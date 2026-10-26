import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import ai, allocations, auth, inventory, invitations, logistics, insights, misc, recovery, reports
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_ctx

settings = get_settings()
settings.assert_production_safe()
configure_logging()
log = logging.getLogger("foodagent.http")

app = FastAPI(
    title="foodAgent API", version="1.0.0",
    description="foodAgent — Intelligent Food Recovery & Redistribution Platform. Decision support and workflow software; "
                "it does not certify food as safe for human consumption.",
    docs_url="/docs", openapi_url="/openapi.json",
)
install_error_handlers(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_credentials=False,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-Request-ID"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    token = request_id_ctx.set(rid)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_ctx.reset(token)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.environment == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path != "/health":
        log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, (time.perf_counter() - start) * 1000)
    return response


for r in (auth.router, inventory.router, recovery.router, allocations.router, logistics.router, insights.router, misc.router, reports.router, invitations.router, ai.router):
    app.include_router(r, prefix="/api/v1")


@app.get("/health", tags=["health"])
def health():
    try:
        with SessionLocal() as s:
            s.execute(text("select 1"))
        return {"status": "ok", "service": "foodagent-api", "database": "ok"}
    except Exception:
        from fastapi.responses import JSONResponse
        return JSONResponse({"status": "degraded", "service": "foodagent-api", "database": "unavailable"}, status_code=503)
