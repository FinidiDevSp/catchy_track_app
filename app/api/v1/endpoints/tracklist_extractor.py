from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.services.tracklist_extractor import DJResult, scrape_all_from_config

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tracklist-extractor"])


class SongInfo(BaseModel):
    artist: str
    title: str
    label: str


class TracklistInfo(BaseModel):
    title: str
    url: str
    songs: List[SongInfo]


class Tracklists1001Item(BaseModel):
    id: str
    name: str
    tracklists: List[TracklistInfo]
    error: Optional[str] = None


class Tracklists1001Response(BaseModel):
    ok: bool = True
    count: int
    items: List[Tracklists1001Item] = Field(default_factory=list)


# Renamed path to tracklist_extractor
@router.get("/tracklist_extractor/scrape", response_model=Tracklists1001Response)
async def scrape_1001_tracklists(limit: int | None = None) -> Tracklists1001Response:
    """Scrape 1001Tracklists for all DJs defined in config/tracklists_1001.json.

    Always performs live scraping (no DB cache). Returns titles per DJ.
    """
    config_path = Path("config/tracklists_1001.json")
    if not config_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Missing config file: config/tracklists_1001.json",
        )

    try:
        # Run Selenium (blocking) in a worker thread
        results: List[DJResult] = await asyncio.to_thread(
            scrape_all_from_config, config_path, limit=limit
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Unexpected error scraping 1001Tracklists")
        raise HTTPException(status_code=500, detail=str(e))

    items = []
    for r in results:
        tracklists = [
            TracklistInfo(
                title=e.title,
                url=e.url,
                songs=[SongInfo(artist=s.artist, title=s.title, label=s.label) for s in e.songs],
            )
            for e in r.tracklists
        ]
        items.append(Tracklists1001Item(id=r.id, name=r.name, tracklists=tracklists, error=r.error))
    return Tracklists1001Response(ok=True, count=len(items), items=items)
