"""Routers cho Simple Translator pipeline."""
from fastapi import APIRouter

from dubeditor.simple.routers import (
    bible, batches, review, config, subtitles, flow,
)

router = APIRouter()

# Tất cả routers nest dưới prefix /api/projects/{pid}/simple/ (do main router add)
router.include_router(bible.router,        prefix="/projects/{project_id}/simple/bible",     tags=["simple-bible"])
router.include_router(batches.router,      prefix="/projects/{project_id}/simple/batches",   tags=["simple-batches"])
router.include_router(subtitles.router,    prefix="/projects/{project_id}/simple/subtitles", tags=["simple-subtitles"])
router.include_router(review.router,       prefix="/projects/{project_id}/simple/review",    tags=["simple-review"])
router.include_router(config.router,       prefix="/projects/{project_id}/simple/config",    tags=["simple-config"])
router.include_router(flow.router,         prefix="/projects/{project_id}/simple/flow",      tags=["simple-flow"])
