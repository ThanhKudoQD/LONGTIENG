"""
dubeditor/router.py (v4 — Simple Translator)

⚠️ THAY ĐỔI:
  - BỎ import `translate` (pipeline v3)
  - BỎ import `presets` (LEGACY — Simple dùng config riêng per-project)
  - THÊM import `simple.routers` (pipeline mới)
"""
from fastapi import APIRouter

from dubeditor.routers import projects, subtitles, characters, tts, export, ws
from dubeditor.routers import auto_assign, auto_fix, chapters
from dubeditor.routers import license as license_router
from dubeditor.routers import settings   # v3.12 — vẫn dùng cho global API keys legacy

# Simple Translator v4 (pipeline mới)
from dubeditor.simple.routers import router as simple_router

router = APIRouter()

# License — đặt TRƯỚC các router khác
router.include_router(license_router.router, prefix="/api/license",   tags=["dub-license"])
router.include_router(projects.router,       prefix="/api/projects",  tags=["dub-projects"])
router.include_router(subtitles.router,      prefix="/api/subtitles", tags=["dub-subtitles"])
router.include_router(characters.router,     prefix="/api/characters",tags=["dub-characters"])
router.include_router(tts.router,            prefix="/api/tts",       tags=["dub-tts"])
router.include_router(export.router,         prefix="/api/export",    tags=["dub-export"])
router.include_router(auto_assign.router,    prefix="/api",           tags=["dub-auto-assign"])
router.include_router(auto_fix.router,       prefix="/api",           tags=["dub-auto-fix"])
router.include_router(chapters.router,       prefix="/api/chapters",  tags=["dub-chapters"])
router.include_router(ws.router,                                       tags=["dub-ws"])
router.include_router(settings.router,       prefix="/api",           tags=["dub-settings"])

# Simple pipeline — endpoints dạng /api/projects/{pid}/simple/...
# (sub-routers tự thêm prefix /projects/{pid}/simple/{section})
router.include_router(simple_router,         prefix="/api",           tags=["dub-simple"])
