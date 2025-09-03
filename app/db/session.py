from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import get_settings

settings = get_settings()


def _build_engine():
    url = settings.database_url
    connect_args = {}
    if url.startswith("sqlite"):
        # Ensure data directory exists
        if url.startswith("sqlite:///"):
            db_path = url.replace("sqlite:///", "")
        elif url.startswith("sqlite:///"):
            db_path = url.replace("sqlite:///", "")
        else:
            db_path = None
        if db_path:
            data_dir = os.path.dirname(db_path)
            if data_dir and not os.path.isabs(data_dir):
                data_dir = os.path.join(settings.base_dir, data_dir)
            if data_dir and not os.path.exists(data_dir):
                os.makedirs(data_dir, exist_ok=True)
        connect_args = {"check_same_thread": False}
    engine = create_engine(url, future=True, echo=False, connect_args=connect_args)
    return engine


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
