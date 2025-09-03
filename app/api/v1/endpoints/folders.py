from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.services.folder_processor import process_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["folders"])


class ProcessRequest(BaseModel):
    action: Literal["ALLOW", "DENY"]
    path: str = Field(..., description="Directory path containing subfolders to process")


class ProcessResult(BaseModel):
    ok: bool
    requested_action: Literal["ALLOW", "DENY"]
    base_path: str
    processed_folders_count: int
    saved_count: int
    deleted_count: int
    skipped_count: int
    errors: List[Dict[str, str]] = []
    skipped: List[str] = []
    duration_ms: int


@router.post("/folders/process", response_model=ProcessResult, status_code=status.HTTP_200_OK)
def process_folders(
    body: ProcessRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    path = Path(body.path)
    try:
        result = process_path(action=body.action, directory=path, db=db, settings=settings)
        return result
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected error while processing folders")
        raise HTTPException(status_code=500, detail=str(e))
