from fastapi import APIRouter
from dubeditor.routers import projects, subtitles, characters, tts, export, ws, presets
from dubeditor.routers import auto_assign, auto_fix, chapters
from dubeditor.routers import translate
from dubeditor.routers import manual_translate  # v3.15: chế độ Dịch Thủ công
from dubeditor.routers import manual_translate_mega  # v4: mega-chunk manual mode
from dubeditor.routers import license as license_router
from dubeditor.routers import settings  # v3.12

router = APIRouter()
# License — đặt TRƯỚC các router khác để middleware không chặn nhầm
router.include_router(license_router.router,  prefix="/api/license",   tags=["dub-license"])
router.include_router(projects.router,     prefix="/api/projects",   tags=["dub-projects"])
router.include_router(subtitles.router,    prefix="/api/subtitles",  tags=["dub-subtitles"])
router.include_router(characters.router,   prefix="/api/characters", tags=["dub-characters"])
router.include_router(tts.router,          prefix="/api/tts",        tags=["dub-tts"])
router.include_router(export.router,       prefix="/api/export",     tags=["dub-export"])
router.include_router(auto_assign.router,  prefix="/api",            tags=["dub-auto-assign"])
router.include_router(auto_fix.router,     prefix="/api",            tags=["dub-auto-fix"])
router.include_router(chapters.router,     prefix="/api/chapters",   tags=["dub-chapters"])
router.include_router(translate.router,    prefix="/api",            tags=["dub-translate"])
# v3.15: Manual Translate v3 — backward compat (8 stages)
router.include_router(manual_translate.router, prefix="/api", tags=["dub-manual-translate"])
# v4: Manual Translate Mega-Chunk — workflow tối ưu (5 stages, 10-13 paste/phim)
router.include_router(manual_translate_mega.router, prefix="/api", tags=["dub-manual-translate-mega"])
router.include_router(ws.router,                                      tags=["dub-ws"])
router.include_router(presets.router,      prefix="/api/presets",    tags=["dub-presets"])
# v3.12: settings global (API keys + model presets)
router.include_router(settings.router,     prefix="/api",            tags=["dub-settings"])
