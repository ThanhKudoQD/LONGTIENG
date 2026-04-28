from fastapi import APIRouter
from dubeditor.routers import projects, subtitles, characters, tts, export, ws, presets
from dubeditor.routers import auto_assign
from dubeditor.routers import auto_fix
from dubeditor.routers import chapters

router = APIRouter()
router.include_router(projects.router,     prefix="/api/projects",   tags=["dub-projects"])
router.include_router(subtitles.router,    prefix="/api/subtitles",  tags=["dub-subtitles"])
router.include_router(characters.router,   prefix="/api/characters", tags=["dub-characters"])
router.include_router(tts.router,          prefix="/api/tts",        tags=["dub-tts"])
router.include_router(export.router,       prefix="/api/export",     tags=["dub-export"])
router.include_router(auto_assign.router,  prefix="/api",            tags=["dub-auto-assign"])
router.include_router(auto_fix.router,     prefix="/api",            tags=["dub-auto-fix"])
router.include_router(chapters.router,     prefix="/api/chapters",   tags=["dub-chapters"])
router.include_router(ws.router,                                      tags=["dub-ws"])
router.include_router(presets.router,      prefix="/api/presets",    tags=["dub-presets"])