"""
Config router — get/save per-project config.

Endpoints (prefix: /api/projects/{project_id}/simple/config):
  GET    /                       → SimpleConfigSchema
  POST   /                       → save (body: SimpleConfigSchema)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple.schemas import SimpleConfigSchema, OkOut
from dubeditor.simple import service_config

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


@router.get("", response_model=SimpleConfigSchema)
def get_config(project_id: int, db: Session = Depends(get_db)):
    _check_project(db, project_id)
    return service_config.load_config(db, project_id)


@router.post("", response_model=OkOut)
def save_config(
    project_id: int,
    body: SimpleConfigSchema,
    db: Session = Depends(get_db),
):
    _check_project(db, project_id)
    service_config.save_config(db, project_id, body)
    return OkOut(ok=True, message="Config saved.")
