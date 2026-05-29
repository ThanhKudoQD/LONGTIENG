"""
Review router — tab Review (AI review bản dịch).

Endpoints (prefix /api/projects/{project_id}/simple/review):
  GET    /                       → state (groups + suggestions)
  POST   /rebuild                → chia review batch
  GET    /{idx}                  → 1 group detail
  POST   /{idx}/auto             → Auto gọi AI (background)
  POST   /{idx}/save             → paste response
  POST   /run-all                → Auto tất cả groups (background)
  POST   /suggestions/{sid}/apply    → apply 1 suggestion
  POST   /suggestions/{sid}/dismiss  → bỏ qua 1 suggestion
  POST   /apply-all              → apply tất cả pending (optional group_index)
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple import service_review, service_config
from dubeditor.simple.models import SimpleReviewGroup
from dubeditor.simple.jobs import spawn_task

logger = logging.getLogger(__name__)
router = APIRouter()


def _check(db: Session, pid: int):
    if not db.query(Project).filter(Project.id == pid).first():
        raise HTTPException(404, f"Project {pid} not found")


class SaveResponseIn(BaseModel):
    response: str


@router.get("")
def get_state(project_id: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    return service_review.get_review_state(db, project_id)


@router.post("/rebuild")
def rebuild(project_id: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    config = service_config.load_config(db, project_id)
    result = service_review.rebuild_review_groups(db, project_id, config)
    result.update(service_review.get_review_state(db, project_id))
    return result


@router.post("/{group_index}/auto")
def auto_group(project_id: int, group_index: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    group = db.query(SimpleReviewGroup).filter(
        SimpleReviewGroup.project_id == project_id,
        SimpleReviewGroup.group_index == group_index,
    ).first()
    if not group:
        raise HTTPException(404, f"Review group {group_index} not found")

    group_id = group.id
    task_id = f"review.group.{group_index}"

    async def _job(session: Session):
        await service_review.run_review_group(session, group_id)

    spawn_task(
        project_id=project_id,
        section="review",
        task_id=task_id,
        coro_factory=_job,
        ref={"group_index": group_index},
        state_loader=lambda s: service_review.get_review_state(s, project_id),
        start_message=f"Đang review nhóm {group_index + 1}...",
    )
    return {"ok": True, "status": "started", "task_id": task_id}


@router.post("/{group_index}/save")
def save_group(project_id: int, group_index: int, body: SaveResponseIn,
               db: Session = Depends(get_db)):
    _check(db, project_id)
    group = db.query(SimpleReviewGroup).filter(
        SimpleReviewGroup.project_id == project_id,
        SimpleReviewGroup.group_index == group_index,
    ).first()
    if not group:
        raise HTTPException(404, f"Review group {group_index} not found")
    try:
        service_review.save_group_response(db, group.id, body.response)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return service_review.get_review_state(db, project_id)


@router.post("/run-all")
def run_all(project_id: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    groups = db.query(SimpleReviewGroup).filter(
        SimpleReviewGroup.project_id == project_id,
    ).order_by(SimpleReviewGroup.group_index).all()
    if not groups:
        raise HTTPException(400, "Chưa có review group. Bấm Rebuild trước.")

    group_ids = [g.id for g in groups]
    task_id = "review.run-all"

    async def _job(session: Session):
        for gid in group_ids:
            try:
                await service_review.run_review_group(session, gid)
            except Exception as e:
                logger.warning(f"[review.run-all] group {gid} failed: {e}")

    spawn_task(
        project_id=project_id,
        section="review",
        task_id=task_id,
        coro_factory=_job,
        state_loader=lambda s: service_review.get_review_state(s, project_id),
        start_message=f"Đang review {len(group_ids)} nhóm...",
    )
    return {"ok": True, "status": "started", "task_id": task_id}


@router.post("/suggestions/{sid}/apply")
def apply_one(project_id: int, sid: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    try:
        service_review.apply_suggestion(db, project_id, sid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return service_review.get_review_state(db, project_id)


@router.post("/suggestions/{sid}/dismiss")
def dismiss_one(project_id: int, sid: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    try:
        service_review.dismiss_suggestion(db, project_id, sid)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return service_review.get_review_state(db, project_id)


class ApplyAllIn(BaseModel):
    group_index: Optional[int] = None


@router.post("/apply-all")
def apply_all(project_id: int, body: ApplyAllIn = ApplyAllIn(), db: Session = Depends(get_db)):
    _check(db, project_id)
    result = service_review.apply_all_suggestions(db, project_id, body.group_index)
    result.update(service_review.get_review_state(db, project_id))
    return result
