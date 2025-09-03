from __future__ import annotations

import logging
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from fastapi import HTTPException, status
from filelock import FileLock
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db import crud

logger = logging.getLogger(__name__)


def _is_within_any(path: Path, roots: Iterable[Path]) -> bool:
    rp = path.resolve()
    for root in roots:
        rr = root.resolve()
        try:
            rp.relative_to(rr)
            return True
        except ValueError:
            continue
    return False


def _slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = s.strip("-_")
    s = re.sub(r"-{2,}", "-", s)
    return s or "n-a"


def _on_rm_error(func, path, exc_info):  # noqa: D401
    # Make read-only files writable then retry (Windows friendly)
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:  # noqa: BLE001
        raise


@dataclass
class ProcessStats:
    processed: int = 0
    saved: int = 0
    deleted: int = 0
    skipped: int = 0


def process_path(*, action: str, directory: Path, db: Session, settings: Settings) -> dict:
    started = time.time()

    if action not in {"ALLOW", "DENY"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid action")

    # Normalize and validate directory
    if not directory.is_absolute():
        directory = (settings.base_dir / directory).resolve()

    if not directory.exists():
        raise HTTPException(status_code=404, detail="Directory not found")
    if not directory.is_dir():
        raise HTTPException(status_code=400, detail="Provided path is not a directory")

    allowed_roots = settings.allowed_root_paths
    if not _is_within_any(directory, allowed_roots):
        raise HTTPException(status_code=403, detail="Path is outside allowed roots")

    # Prevent concurrent processing of same directory
    lock = FileLock(str(directory / ".process.lock"))
    with lock:
        errors: List[dict] = []
        skipped: List[str] = []
        stats = ProcessStats()

        for child in directory.iterdir():
            if child.name.startswith("."):
                skipped.append(child.name)
                stats.skipped += 1
                continue
            if not child.is_dir():
                skipped.append(child.name)
                stats.skipped += 1
                continue
            if child.is_symlink():
                skipped.append(child.name)
                stats.skipped += 1
                continue

            stats.processed += 1
            name = child.name
            slug = _slugify(name)

            try:
                crud.create_folder_event(db, action=action, slug=slug, name=name)
                stats.saved += 1
            except Exception as e:  # noqa: BLE001
                db.rollback()
                logger.exception("Failed to persist folder event for %s", name)
                errors.append({"folder": name, "error": f"db: {e}"})
                # Do not attempt deletion if we couldn't persist
                continue

            # Safety: ensure child path is within allowed roots
            if not _is_within_any(child, allowed_roots):
                errors.append({"folder": name, "error": "child path outside allowed roots"})
                continue
            try:
                shutil.rmtree(child, onerror=_on_rm_error)
                stats.deleted += 1
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to delete folder %s", child)
                errors.append({"folder": name, "error": f"delete: {e}"})

    duration_ms = int((time.time() - started) * 1000)
    return {
        "ok": len([e for e in errors if e]) == 0,
        "requested_action": action,
        "base_path": str(directory),
        "processed_folders_count": stats.processed,
        "saved_count": stats.saved,
        "deleted_count": stats.deleted,
        "skipped_count": stats.skipped,
        "errors": errors,
        "skipped": skipped,
        "duration_ms": duration_ms,
    }
