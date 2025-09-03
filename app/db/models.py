from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from .session import Base


class FolderEvent(Base):
    __tablename__ = "folder_events"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(16), nullable=False, index=True)
    slug = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
