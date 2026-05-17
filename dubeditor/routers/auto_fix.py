from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import json
import logging
from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text
from sqlalchemy.sql import func

from dubeditor.database import get_db, Base, engine
from dubeditor.models import Subtitle
from dubeditor.auto_fix_overlap import SubInfo, detect_chains, compute_fix, summarize

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Snapshot table cho undo ─────────────────────────────────────────────
class AutoFixSnapshot(Base):
    __tablename__ = "auto_fix_snapshots"
    id         = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    changes    = Column(Text)  # JSON: [{sub_id, old_offset, new_offset}]


def _ensure_snapshot_table():
    """Tạo bảng nếu chưa có."""
    Base.metadata.create_all(bind=engine, tables=[AutoFixSnapshot.__table__])


# ─── Request/Response ────────────────────────────────────────────────────
class AutoFixRequest(BaseModel):
    overlap_threshold: float = 0.5
    threshold_anchor:  float = 4.0
    dry_run:           bool  = True
    # v3.4: nếu truyền → CHỈ scan + fix các sub này (frontend dùng để giới hạn
    # auto-fix trong đoạn đang lọc). Không truyền → fix toàn project như cũ.
    subtitle_ids: Optional[List[int]] = None


class FixChangeOut(BaseModel):
    sub_id: int
    sub_index: int
    old_offset: float
    new_offset: float
    shift: float


class AutoFixResponse(BaseModel):
    summary: dict
    changes: list[FixChangeOut]
    snapshot_id: Optional[int] = None  # nếu apply, trả id để undo


# ─── Endpoints ───────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/auto-fix-overlap", response_model=AutoFixResponse)
def auto_fix_overlap(project_id: int, data: AutoFixRequest, db: Session = Depends(get_db)):
    _ensure_snapshot_table()

    # Load subtitles — scope theo subtitle_ids nếu có
    query = db.query(Subtitle).filter(Subtitle.project_id == project_id)
    if data.subtitle_ids:
        query = query.filter(Subtitle.id.in_(data.subtitle_ids))
    subs = query.order_by(Subtitle.index).all()
    if not subs:
        raise HTTPException(404, "Project không có phụ đề")

    sub_infos = [
        SubInfo(
            id=s.id,
            index=s.index,
            start_time=s.start_time,
            end_time=s.end_time,
            audio_offset=s.audio_offset or 0.0,
            wav_duration=s.wav_duration,
            has_audio=bool(s.tts_done and s.audio_path),
        )
        for s in subs
    ]

    chains = detect_chains(sub_infos, data.overlap_threshold)
    changes, _ = compute_fix(sub_infos, data.overlap_threshold, data.threshold_anchor)

    summary = summarize(changes, chains, len([s for s in sub_infos if s.has_audio]))

    changes_out = [
        FixChangeOut(
            sub_id=c.sub_id,
            sub_index=c.sub_index,
            old_offset=c.old_offset,
            new_offset=c.new_offset,
            shift=c.shift,
        ) for c in changes
    ]

    if data.dry_run or not changes:
        return AutoFixResponse(summary=summary, changes=changes_out, snapshot_id=None)

    # Apply: update DB
    by_id = {c.sub_id: c for c in changes}
    snapshot_data = []
    for s in subs:
        if s.id in by_id:
            c = by_id[s.id]
            snapshot_data.append({
                "sub_id": s.id,
                "old_offset": c.old_offset,
                "new_offset": c.new_offset,
            })
            s.audio_offset = c.new_offset

    # Lưu snapshot
    snap = AutoFixSnapshot(
        project_id=project_id,
        changes=json.dumps(snapshot_data),
    )
    db.add(snap)
    db.commit()
    db.refresh(snap)

    logger.info(f"[auto-fix] project={project_id} changes={len(changes)} snapshot={snap.id}")

    return AutoFixResponse(summary=summary, changes=changes_out, snapshot_id=snap.id)


@router.post("/projects/{project_id}/undo-auto-fix")
def undo_auto_fix(project_id: int, db: Session = Depends(get_db)):
    _ensure_snapshot_table()

    # Lấy snapshot mới nhất
    snap = db.query(AutoFixSnapshot).filter(
        AutoFixSnapshot.project_id == project_id
    ).order_by(AutoFixSnapshot.created_at.desc()).first()

    if not snap:
        raise HTTPException(404, "Không có snapshot để hoàn tác")

    changes = json.loads(snap.changes)
    for ch in changes:
        s = db.query(Subtitle).filter(Subtitle.id == ch["sub_id"]).first()
        if s:
            s.audio_offset = ch["old_offset"]

    db.delete(snap)
    db.commit()
    return {"undone": len(changes)}
