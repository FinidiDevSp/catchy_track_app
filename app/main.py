from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.db.session import Base, engine

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)


# Lifespan handler replacing deprecated on_event("startup")
@asynccontextmanager
async def lifespan_ctx(app: FastAPI):
    # Startup
    # Ensure DB tables
    Base.metadata.create_all(bind=engine)
    # Ensure allowed roots exist
    for root in settings.allowed_root_paths:
        try:
            os.makedirs(root, exist_ok=True)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to ensure allowed root exists: %s", root)
    yield
    # Shutdown (nothing for now)


# Hide interactive docs in production (when debug is False)
docs_url = "/docs" if settings.debug else None
redoc_url = "/redoc" if settings.debug else None
openapi_url = "/openapi.json" if settings.debug else None

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
    lifespan=lifespan_ctx,
)

# Security: API Key dependency for /api/v1
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(
    api_key: str | None = Security(api_key_header),
    authorization: str | None = Header(default=None),
    settings=settings,  # use module-level settings
):
    if not settings.auth_enabled:
        return
    # Determine provided key from X-API-Key or Authorization: ApiKey <key>
    provided = api_key
    if not provided and authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() in {"apikey", "bearer"}:
            provided = parts[1]

    # Treat unresolved HTTP client placeholders like {{apiKey}} as missing in debug
    if provided and provided.startswith("{{") and provided.endswith("}}"):
        if settings.debug and settings.api_key:
            logger.warning(
                "Received placeholder API key '{{...}}'; using configured dev key from settings."
            )
            provided = settings.api_key
        else:
            provided = None

    # Require a configured API key and a correct provided key
    if not settings.api_key or not provided or provided != settings.api_key:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


@app.get("/healthz")
def healthz():  # pragma: no cover
    return {"status": "ok"}


# Middleware: CORS and Trusted Hosts
allow_all = "*" in settings.cors_origin_list
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else settings.cors_origin_list,
    allow_credentials=False if allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts_list)


app.include_router(api_router, prefix="/api/v1", dependencies=[Depends(verify_api_key)])


# Security headers (applied on all responses; HSTS only if HTTPS)
@app.middleware("http")
async def add_security_headers(request, call_next):
    resp = await call_next(request)
    # Basic hardening headers
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Consider reverse proxy header for scheme
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme)
    if scheme == "https":
        # 2 years, include subdomains, preload (adjust to your policy)
        resp.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"
        )
    return resp
