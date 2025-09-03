from __future__ import annotations

from sqlalchemy.orm import Session

from .models import FolderEvent


def create_folder_event(db: Session, *, action: str, slug: str, name: str) -> FolderEvent:
    obj = FolderEvent(action=action, slug=slug, name=name)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj
