from fastapi import APIRouter

from .endpoints import folders

api_router = APIRouter()
api_router.include_router(folders.router, prefix="")
