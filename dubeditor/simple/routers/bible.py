"""
Bible router — Bước I (background task version).

Endpoints (prefix: /api/projects/{project_id}/simple/bible):
  GET    /                       → BibleStateOut
  POST   /mode                   → đổi single/multi (rebuild parts; sync)
  POST   /{idx}/save             → manual save 1 part (sync)
  POST   /{idx}/auto             → spawn LLM task (return 202, push qua WS)
  POST   /merge/save             → manual save merge (sync)
  POST   /merge/auto             → spawn merge task (return 202, push qua WS)
  POST   /run-all                → spawn run-all task (return 202)
  POST   /reset                  → xóa hết Bible parts của project (sync)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Project
from dubeditor.simple.models import SimpleBiblePart, SimpleBibleMerge
from dubeditor.simple.schemas import (
    BibleStateOut, BibleModeIn, SaveResponseIn, OkOut,
)
from dubeditor.simple import service_bible
from dubeditor.simple import service_config
from dubeditor.simple.jobs import spawn_task

logger = logging.getLogger(__name__)
router = APIRouter()


def _check_project(db: Session, project_id: int) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


# ─── State ───────────────────────────────────────────────────────────────────

@router.get("", response_model=BibleStateOut)
def get_state(project_id: int, db: Session = Depends(get_db)):
    _check_project(db, project_id)
    return service_bible.get_bible_state(db, project_id)


@router.post("/mode", response_model=BibleStateOut)
def change_mode(
    project_id: int,
    body: BibleModeIn,
    db: Session = Depends(get_db),
):
    _check_project(db, project_id)
    try:
        service_bible.rebuild_parts(
            db, project_id,
            mode=body.mode,
            multi_parts_count=body.multi_parts_count,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return service_bible.get_bible_state(db, project_id)


@router.post("/{idx}/save", response_model=BibleStateOut)
def save_part(
    project_id: int,
    idx: int,
    body: SaveResponseIn,
    db: Session = Depends(get_db),
):
    _check_project(db, project_id)
    part = (
        db.query(SimpleBiblePart)
        .filter(
            SimpleBiblePart.project_id == project_id,
            SimpleBiblePart.part_index == idx,
        )
        .first()
    )
    if not part:
        raise HTTPException(404, f"Part {idx} not found")
    try:
        service_bible.save_part_response(db, part.id, body.response)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return service_bible.get_bible_state(db, project_id)


@router.post("/merge/save", response_model=BibleStateOut)
def save_merge(
    project_id: int,
    body: SaveResponseIn,
    db: Session = Depends(get_db),
):
    _check_project(db, project_id)
    try:
        service_bible.save_merge_response(db, project_id, body.response)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return service_bible.get_bible_state(db, project_id)


@router.post("/reset", response_model=OkOut)
def reset(project_id: int, db: Session = Depends(get_db)):
    _check_project(db, project_id)
    db.query(SimpleBiblePart).filter(
        SimpleBiblePart.project_id == project_id
    ).delete()
    db.query(SimpleBibleMerge).filter(
        SimpleBibleMerge.project_id == project_id
    ).delete()
    db.commit()
    return OkOut(ok=True, message="Đã xóa Bible.")


# ─── Background tasks (auto run LLM) ─────────────────────────────────────────

@router.post("/{idx}/auto")
def auto_run_part(
    project_id: int,
    idx: int,
    db: Session = Depends(get_db),
):
    """Spawn LLM job cho 1 part. Trả 202. Tiến độ broadcast qua WS."""
    _check_project(db, project_id)

    part = (
        db.query(SimpleBiblePart)
        .filter(
            SimpleBiblePart.project_id == project_id,
            SimpleBiblePart.part_index == idx,
        )
        .first()
    )
    if not part:
        raise HTTPException(404, f"Part {idx} not found")

    part_id = part.id

    async def _job(session: Session):
        config = service_config.load_config(session, project_id)
        await service_bible.run_bible_part(session, part_id, config)

    spawn_task(
        project_id=project_id,
        section="bible",
        task_id=f"bible.part.{idx}",
        coro_factory=_job,
        ref={"part_index": idx},
        state_loader=lambda s: service_bible.get_bible_state(s, project_id),
        start_message=f"Đang gọi LLM cho Part {idx + 1}...",
    )

    return {"ok": True, "task_id": f"bible.part.{idx}"}


@router.post("/merge/auto")
def auto_run_merge(project_id: int, db: Session = Depends(get_db)):
    """Spawn LLM merge job. Trả 202."""
    _check_project(db, project_id)

    # Validate điều kiện merge: phải đủ parts done
    parts = (
        db.query(SimpleBiblePart)
        .filter(SimpleBiblePart.project_id == project_id)
        .all()
    )
    if len(parts) < 2:
        raise HTTPException(400, "Cần ít nhất 2 parts (multi mode) để merge")
    if any(p.status != 'done' for p in parts):
        raise HTTPException(400, "Tất cả parts phải done trước khi merge")

    async def _job(session: Session):
        config = service_config.load_config(session, project_id)
        await service_bible.run_bible_merge(session, project_id, config)

    spawn_task(
        project_id=project_id,
        section="bible",
        task_id="bible.merge",
        coro_factory=_job,
        ref={"merge": True},
        state_loader=lambda s: service_bible.get_bible_state(s, project_id),
        start_message="Đang merge Bible...",
    )

    return {"ok": True, "task_id": "bible.merge"}


@router.post("/run-all")
def run_all(project_id: int, db: Session = Depends(get_db)):
    """Spawn job chạy hết parts còn idle + merge nếu multi mode."""
    _check_project(db, project_id)

    async def _job(session: Session):
        config = service_config.load_config(session, project_id)

        # Run từng part còn idle/error
        parts = (
            session.query(SimpleBiblePart)
            .filter(
                SimpleBiblePart.project_id == project_id,
                SimpleBiblePart.status.in_(('idle', 'error')),
            )
            .order_by(SimpleBiblePart.part_index)
            .all()
        )

        from dubeditor.simple.jobs import broadcast_simple
        for part in parts:
            try:
                await broadcast_simple(
                    project_id, "bible", "bible.run-all", "progress",
                    ref={"part_index": part.part_index},
                    message=f"Đang chạy Part {part.part_index + 1}/{len(parts)}...",
                )
                await service_bible.run_bible_part(session, part.id, config)
                # broadcast state để FE refresh
                await broadcast_simple(
                    project_id, "bible", "bible.run-all", "progress",
                    ref={"part_index": part.part_index},
                    data=service_bible.get_bible_state(session, project_id),
                    message=f"Part {part.part_index + 1} done",
                )
            except Exception as e:
                logger.warning(f"[bible/run-all] part={part.part_index} failed: {e}")

        # Check multi mode → merge
        total_parts = session.query(SimpleBiblePart).filter(
            SimpleBiblePart.project_id == project_id
        ).count()
        if total_parts > 1:
            done = (
                session.query(SimpleBiblePart)
                .filter(
                    SimpleBiblePart.project_id == project_id,
                    SimpleBiblePart.status == 'done',
                )
                .count()
            )
            if done == total_parts:
                try:
                    await broadcast_simple(
                        project_id, "bible", "bible.run-all", "progress",
                        ref={"merge": True}, message="Đang merge...",
                    )
                    await service_bible.run_bible_merge(session, project_id, config)
                except Exception as e:
                    logger.warning(f"[bible/run-all] merge failed: {e}")

    spawn_task(
        project_id=project_id,
        section="bible",
        task_id="bible.run-all",
        coro_factory=_job,
        ref={},
        state_loader=lambda s: service_bible.get_bible_state(s, project_id),
        start_message="Đang chạy toàn bộ Bible...",
    )

    return {"ok": True, "task_id": "bible.run-all"}
