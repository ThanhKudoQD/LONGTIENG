"""
Filter router — Bước III.

Endpoints (prefix: /api/projects/{project_id}/simple/filter):
  GET    /stats                  → FilterStats + errors hiện tại (no rescan)
  POST   /scan                   → rescan toàn bộ + auto-fix
  POST   /auto-fix               → chỉ auto-fix (không rescan)
  POST   /push-review            → rebuild_review_groups
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple.schemas import FilterScanOut, OkOut
from dubeditor.simple import service_filter
from dubeditor.simple import service_review
from dubeditor.simple import service_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


@router.get("/stats", response_model=FilterScanOut)
def get_stats(project_id: int, db: Session = Depends(get_db)):
    """Lấy stats hiện tại (KHÔNG rescan, chỉ đọc DB issues)."""
    _check_project(db, project_id)
    return service_filter.get_filter_stats(db, project_id)


@router.post("/scan", response_model=FilterScanOut)
def scan(project_id: int, db: Session = Depends(get_db)):
    """Scan toàn bộ + auto-fix."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)
    return service_filter.scan_all_errors(db, project_id, config, auto_fix=True)


@router.post("/auto-fix", response_model=OkOut)
def auto_fix(project_id: int, db: Session = Depends(get_db)):
    """Chỉ chạy auto-fix (whitespace, punctuation) không rescan."""
    _check_project(db, project_id)
    count = service_filter.auto_fix_all(db, project_id)
    return OkOut(ok=True, message=f"Đã auto-fix {count} dòng.")


@router.post("/push-review", response_model=OkOut)
def push_to_review(project_id: int, db: Session = Depends(get_db)):
    """Rebuild review groups từ các pending issues."""
    _check_project(db, project_id)
    config = service_config.load_config(db, project_id)
    groups = service_review.rebuild_review_groups(db, project_id, config)
    return OkOut(ok=True, message=f"Đã tạo {len(groups)} review group(s).")
