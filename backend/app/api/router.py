from fastapi import APIRouter

from app.api import auth, candidates, profiles, sources, ws

api_router = APIRouter(prefix="/api")
for module in (auth, candidates, profiles, sources, ws):
    api_router.include_router(module.router)
