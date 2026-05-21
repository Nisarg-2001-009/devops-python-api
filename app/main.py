"""FastAPI application entry point.

This module creates and configures the ASGI app instance. It is the only
place that knows about all routers — individual routers and services have
no knowledge of each other, which keeps coupling low.

Uvicorn is pointed at this module:  uvicorn app.main:app
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.routers import accounts, analytics, auth, transactions

from prometheus_fastapi_instrumentator import Instrumentator
from app.metrics import (
    TRANSACTIONS_CREATED_TOTAL,
    USERS_REGISTERED_TOTAL,
    ACTIVE_USERS,
    USER_LOGIN_TOTAL,
)

# ── Logging ───────────────────────────────────────────────────────────────────
# Get a logger named after this module ("app.main"). Uvicorn configures the
# root logger; child loggers inherit its handlers and level automatically.
logger = logging.getLogger(__name__)

settings = get_settings()

# ── Lifespan ──────────────────────────────────────────────────────────────────
# The lifespan context manager is the modern replacement for the deprecated
# @app.on_event("startup") / @app.on_event("shutdown") decorators (removed in
# FastAPI 0.103+). Code before `yield` runs at startup; code after runs at
# shutdown. Both phases share the same scope, making it easy to pass resources
# (DB pools, ML models, cache clients) between startup and shutdown without
# module-level globals.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Application started — %s v%s", settings.APP_NAME, settings.VERSION)
    # Future startup hooks go here:
    #   - Pre-warm database connection pool
    #   - Load ML models into memory
    #   - Connect to Redis / message broker
    yield
    # ── Shutdown ──────────────────────────────────────────────────────────────
    # Mirror startup: close connections, flush buffers, etc.
    logger.info("Application shutting down")


# ── FastAPI instance ──────────────────────────────────────────────────────────
# title, version, and description appear in the auto-generated OpenAPI JSON
# and in the Swagger UI at /docs and ReDoc at /redoc.
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description="""
## Personal Finance Tracker API

Track accounts, record transactions, set budgets, and analyse spending trends.

### Authentication
All protected endpoints require a **Bearer JWT** obtained from `POST /api/v1/auth/login`.
Include it in the `Authorization` header:
```
Authorization: Bearer <token>
```

### Analytics
Three SQL-heavy analytics endpoints showcase window functions and derived tables:
- **Monthly summary** — per-category spend with percentage of total using `SUM OVER`.
- **Spending trends** — month-over-month change using the `LAG()` window function.
- **Budget vs actual** — budget adherence using a LEFT JOIN subquery.
""",
    lifespan=lifespan,
    # Swagger UI served at /docs; disable if you prefer ReDoc-only in production.
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS middleware ───────────────────────────────────────────────────────────
# CORSMiddleware must be added before routers so every response — including
# 422 validation errors from router dependencies — carries the CORS headers.
#
# allow_origins=["*"] is acceptable during development (any frontend origin
# can call the API). In production, replace with an explicit list:
#   allow_origins=["https://yourdomain.com"]
#
# allow_credentials=True lets the browser send cookies / Authorization
# headers cross-origin. Required when the frontend uses the Bearer token
# stored in memory (not a cookie) — some HTTP clients send it as a credential.
#
# Note: allow_origins=["*"] and allow_credentials=True are mutually exclusive
# in the CORS spec for cookie-based auth, but fine for Bearer-token auth where
# the token is in the Authorization header, not a cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],   # GET, POST, PUT, PATCH, DELETE, OPTIONS
    allow_headers=["*"],   # Authorization, Content-Type, etc.
)

# ── Prometheus metrics ────────────────────────────────────────────────────────
# Instrumentator automatically creates a /metrics endpoint in Prometheus
# exposition format. expose() registers the endpoint. instrument() wraps
# every route to track request count, latency, and status codes.
Instrumentator().instrument(app).expose(app)

# ── Routers ───────────────────────────────────────────────────────────────────
# All routes are versioned under /api/v1. Bumping to v2 in the future is a
# one-line change per router.include_router call, or a loop over the list.
#
# The prefix here combines with the prefix declared inside each router module:
#   /api/v1  +  /auth         → /api/v1/auth/login, /api/v1/auth/register
#   /api/v1  +  /accounts     → /api/v1/accounts, /api/v1/accounts/{id}
#   /api/v1  +  /transactions → /api/v1/transactions, ...
#   /api/v1  +  /analytics    → /api/v1/analytics/summary, ...
_API_PREFIX = "/api/v1"

app.include_router(auth.router, prefix=_API_PREFIX)
app.include_router(accounts.router, prefix=_API_PREFIX)
app.include_router(transactions.router, prefix=_API_PREFIX)
app.include_router(analytics.router, prefix=_API_PREFIX)


# ── Utility endpoints ─────────────────────────────────────────────────────────

@app.get(
    "/health",
    tags=["meta"],
    summary="Service health check",
    response_description="Service is healthy",
)
def health_check():
    """Lightweight liveness probe used by Docker / Kubernetes health checks.

    Returns HTTP 200 as long as the Python process is running. This does NOT
    check database connectivity — add a separate readiness probe for that if
    needed (query `SELECT 1` and return 503 on failure).
    """
    return {
        "status": "ok",
        "app_name": settings.APP_NAME,
        "version": settings.VERSION,
    }


@app.get(
    "/",
    tags=["meta"],
    summary="Redirect to interactive API docs",
    include_in_schema=False,  # Hide from OpenAPI spec — it's a UX shortcut only
)
def root():
    """Redirect bare requests to the Swagger UI.

    include_in_schema=False removes this route from the generated OpenAPI JSON
    so API clients don't see it as a documented endpoint.
    """
    return RedirectResponse(url="/docs")
