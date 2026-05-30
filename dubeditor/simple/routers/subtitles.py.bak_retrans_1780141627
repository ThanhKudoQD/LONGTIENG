"""
Subtitles router — tab Phụ đề (Simple pipeline).

Endpoints (prefix: /api/projects/{project_id}/simple/subtitles):
  GET    /                  → list subtitles + error notes
  PATCH  /{index}           → sửa 1 dòng (speaker + vi), sync legacy
  POST   /scan-errors       → quét lỗi code-based → gắn notes
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple import service_subtitles, service_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


class PatchSubtitleIn(BaseModel):
    simple_text_vi: Optional[str] = None
    simple_speaker_zh: Optional[str] = None


@router.get("")
def list_subtitles(project_id: int, db: Session = Depends(get_db)):
    _check_project(db, project_id)
    return {"subtitles": service_subtitles.list_subtitles_with_notes(db, project_id)}


@router.patch("/{index}")
def patch_subtitle(
    project_id: int,
    index: int,
    body: PatchSubtitleIn,
    db: Session = Depends(get_db),
):
    _check_project(db, project_id)
    try:
        result = service_subtitles.patch_subtitle(
            db, project_id, index,
            simple_text_vi=body.simple_text_vi,
            simple_speaker_zh=body.simple_speaker_zh,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return result


@router.post("/scan-errors")
def scan_errors(project_id: int, db: Session = Depends(get_db)):
    """Quét lỗi code-based → gắn notes cho từng dòng."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)
    result = service_subtitles.scan_errors_for_view(db, project_id, config)
    # Trả luôn list mới để FE refresh
    result['subtitles'] = service_subtitles.list_subtitles_with_notes(db, project_id)
    return result
