"""Routers cho Simple Translator pipeline."""
from fastapi import APIRouter

from dubeditor.simple.routers import (
    bible, batches, filter as filter_router, review, issues, config, subtitles,
)

router = APIRouter()

# Tất cả routers nest dưới prefix /api/projects/{pid}/simple/ (do main router add)
router.include_router(bible.router,        prefix="/projects/{project_id}/simple/bible",     tags=["simple-bible"])
router.include_router(batches.router,      prefix="/projects/{project_id}/simple/batches",   tags=["simple-batches"])
router.include_router(subtitles.router,    prefix="/projects/{project_id}/simple/subtitles", tags=["simple-subtitles"])
router.include_router(filter_router.router,prefix="/projects/{project_id}/simple/filter",    tags=["simple-filter"])
router.include_router(review.router,       prefix="/projects/{project_id}/simple/review",    tags=["simple-review"])
router.include_router(issues.router,       prefix="/projects/{project_id}/simple/issues",    tags=["simple-issues"])
router.include_router(config.router,       prefix="/projects/{project_id}/simple/config",    tags=["simple-config"])
