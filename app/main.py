from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.db.session import Base, engine

settings = get_settings()
setup_logging(settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, debug=settings.debug)


@app.on_event("startup")
def on_startup() -> None:
    # Ensure DB tables
    Base.metadata.create_all(bind=engine)

    # Ensure allowed roots exist
    for root in settings.allowed_root_paths:
        try:
            os.makedirs(root, exist_ok=True)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to ensure allowed root exists: %s", root)


@app.get("/healthz")
def healthz():  # pragma: no cover
    return {"status": "ok"}


app.include_router(api_router, prefix="/api/v1")
