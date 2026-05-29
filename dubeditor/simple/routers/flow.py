"""
Flow router — tab Auto Flow (chạy Bible → Dịch → Review tự động).

Endpoints (prefix /api/projects/{project_id}/simple/flow):
  GET    /          → state (status + logs)
  POST   /run       → khởi động flow (background) với body {do_bible, do_translate, do_review}
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple import service_flow
from dubeditor.simple.jobs import spawn_task

logger = logging.getLogger(__name__)
router = APIRouter()


def _check(db: Session, pid: int):
    if not db.query(Project).filter(Project.id == pid).first():
        raise HTTPException(404, f"Project {pid} not found")


class RunFlowIn(BaseModel):
    do_bible: bool = True
    do_translate: bool = True
    do_review: bool = True


@router.get("")
def get_state(project_id: int, db: Session = Depends(get_db)):
    _check(db, project_id)
    return service_flow.get_flow_state(project_id)


@router.post("/run")
def run_flow(project_id: int, body: RunFlowIn = RunFlowIn(), db: Session = Depends(get_db)):
    _check(db, project_id)

    # Không cho chạy 2 flow đồng thời
    st = service_flow.get_flow_state(project_id)["status"]
    if st.get("running"):
        raise HTTPException(409, "Flow đang chạy. Đợi xong hoặc tải lại trang.")

    opts = {
        "do_bible": body.do_bible,
        "do_translate": body.do_translate,
        "do_review": body.do_review,
    }

    async def _job(session: Session):
        await service_flow.run_full_flow(session, project_id, **opts)

    task_id = spawn_task(
        project_id=project_id,
        section="flow",
        task_id="flow.run",
        coro_factory=_job,
        state_loader=lambda s: service_flow.get_flow_state(project_id),
        start_message="Bắt đầu Auto Flow...",
    )
    return {"ok": True, "task_id": task_id}
