from fastapi import APIRouter

from .endpoints import folders, tracklist_extractor

api_router = APIRouter()
api_router.include_router(folders.router, prefix="")
api_router.include_router(tracklist_extractor.router, prefix="")
