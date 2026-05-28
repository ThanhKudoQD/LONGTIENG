"""
Issues router — Tab V.

Endpoints (prefix: /api/projects/{project_id}/simple/issues):
  GET    /                       → IssuesListOut (filter by status/type/attempt)
  POST   /{id}/refix             → reset issue về pending để retry
  POST   /{id}/manual-edit       → user sửa tay (body: {text, speaker})
  POST   /{id}/resolve           → mark manual_resolved
  GET    /export.csv             → CSV download
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple.schemas import (
    IssuesListOut, ManualEditIn, OkOut,
)
from dubeditor.simple import service_issues
from dubeditor.simple import service_review

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


@router.get("", response_model=IssuesListOut)
def list_issues(
    project_id: int,
    status: Optional[str] = Query(None),
    error_type: Optional[str] = Query(None),
    attempt: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """List + filter issues."""
    _check_project(db, project_id)
    return service_issues.list_issues(
        db, project_id,
        status=status,
        error_type=error_type,
        attempt=attempt,
    )


@router.post("/{issue_id}/refix", response_model=IssuesListOut)
def refix(project_id: int, issue_id: int, db: Session = Depends(get_db)):
    """Reset issue về pending (sẽ vào group khi push-review next)."""
    _check_project(db, project_id)
    try:
        service_review.refix_issue(db, issue_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return service_issues.list_issues(db, project_id)


@router.post("/{issue_id}/manual-edit", response_model=IssuesListOut)
def manual_edit(
    project_id: int,
    issue_id: int,
    body: ManualEditIn,
    db: Session = Depends(get_db),
):
    """User sửa tay → update subtitle + mark resolved."""
    _check_project(db, project_id)
    try:
        service_issues.manual_edit_issue(
            db, issue_id,
            text=body.text,
            speaker=body.speaker,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    return service_issues.list_issues(db, project_id)


@router.post("/{issue_id}/resolve", response_model=IssuesListOut)
def resolve(project_id: int, issue_id: int, db: Session = Depends(get_db)):
    """Mark manual_resolved (chấp nhận bản hiện tại không sửa)."""
    _check_project(db, project_id)
    try:
        service_issues.mark_resolved(db, issue_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return service_issues.list_issues(db, project_id)


@router.get("/export.csv")
def export_csv(project_id: int, db: Session = Depends(get_db)):
    """Download CSV file của toàn bộ issues."""
    _check_project(db, project_id)
    csv_text = service_issues.export_csv(db, project_id)

    def _iter():
        yield csv_text.encode('utf-8-sig')   # BOM cho Excel hiểu UTF-8

    return StreamingResponse(
        _iter(),
        media_type='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename="simple_issues_{project_id}.csv"',
        },
    )
