from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import math

from dubeditor.database import get_db
from dubeditor.models import Chapter, Subtitle, Project
from dubeditor.schemas import (
    ChapterCreate, ChapterUpdate, ChapterOut,
    AutoSplitRequest, SetCurrentChapterRequest,
)

router = APIRouter()


@router.get("/project/{project_id}", response_model=List[ChapterOut])
def list_chapters(project_id: int, db: Session = Depends(get_db)):
    return db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.sort_order).all()


@router.post("/project/{project_id}/sync-from-arcs")
def sync_chapters_from_arcs(project_id: int, db: Session = Depends(get_db)):
    """Đồng bộ StoryArc → Chapter.

    Xóa các Chapter có source='auto_from_arc' và tạo lại từ arcs hiện tại.
    Giữ nguyên Chapter có source='user' (user tạo tay).
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project không tồn tại")

    from dubeditor.translate_service import sync_arcs_to_chapters
    try:
        created = sync_arcs_to_chapters(db, project_id)
        return {
            "ok": True,
            "created": created,
            "message": f"Đã sync {created} chapters từ arcs"
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Sync failed: {e}")


@router.post("/project/{project_id}/sync-from-batches")
def sync_chapters_from_batches(project_id: int, db: Session = Depends(get_db)):
    """Đồng bộ Simple Translate Batches → Chapter.

    Mỗi batch dịch (SimpleBatch) → 1 chapter. Tên chapter = "Batch N (start→end)".
    Xóa các Chapter source='auto_from_arc' (legacy) trước khi tạo mới.
    Giữ nguyên Chapter source='user'.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project không tồn tại")

    from dubeditor.simple.models import SimpleBatch

    batches = (
        db.query(SimpleBatch)
        .filter(SimpleBatch.project_id == project_id)
        .order_by(SimpleBatch.batch_index)
        .all()
    )
    if not batches:
        raise HTTPException(400, "Chưa có batch dịch nào. Vào tab 'Dịch batch' để chia trước.")

    # Xóa Chapter auto cũ (cả từ arc + batch)
    db.query(Chapter).filter(
        Chapter.project_id == project_id,
        Chapter.source.in_(['auto_from_arc', 'auto_from_batch']),
    ).delete(synchronize_session=False)
    db.flush()

    # Tính sort_order base (giữ chapter user tạo tay trước)
    existing_user = (
        db.query(Chapter)
        .filter(Chapter.project_id == project_id, Chapter.source == 'user')
        .count()
    )

    created = 0
    for i, b in enumerate(batches):
        ch = Chapter(
            project_id=project_id,
            name=f"Batch {b.batch_index + 1} ({b.start_line}→{b.end_line})",
            start_sub_index=b.start_line,
            end_sub_index=b.end_line,
            sort_order=existing_user + i,
            source='auto_from_batch',
            arc_index=b.batch_index,
        )
        db.add(ch)
        created += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Sync failed: {e}")

    return {
        "ok": True,
        "created": created,
        "message": f"Đã chia {created} chapters từ batch dịch",
    }



@router.get("/project/{project_id}/stats")
def chapters_stats(project_id: int, db: Session = Depends(get_db)):
    """
    Trả về thống kê cho từng chapter của project.
    Format:
    [
      {
        "chapter_id": 1,
        "total": 300,
        "assigned": 285,
        "tts_done": 280,
        "overlap_count": 0
      },
      ...
    ]
    """
    chapters = db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.sort_order).all()
    if not chapters:
        return []

    # Lấy hết subs của project 1 lần
    subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).order_by(Subtitle.index).all()

    # Tính overlap toàn project (dùng auto_fix_overlap util)
    from dubeditor.auto_fix_overlap import SubInfo, detect_chains
    sub_infos = [
        SubInfo(
            id=s.id, index=s.index,
            start_time=s.start_time, end_time=s.end_time,
            audio_offset=s.audio_offset or 0.0,
            wav_duration=s.wav_duration,
            has_audio=bool(s.tts_done and s.audio_path),
        )
        for s in subs
    ]
    # threshold mặc định 0.3s — tương thích với UI
    chains = detect_chains(sub_infos, overlap_threshold=0.3)
    overlap_sub_ids = set()
    for chain in chains:
        for idx in chain:
            overlap_sub_ids.add(sub_infos[idx].id)

    # Index lookup nhanh
    subs_by_index = {s.index: s for s in subs}

    result = []
    for c in chapters:
        chapter_subs = [s for idx, s in subs_by_index.items()
                        if c.start_sub_index <= idx <= c.end_sub_index]
        total = len(chapter_subs)
        assigned = sum(1 for s in chapter_subs if s.character_id)
        tts_done = sum(1 for s in chapter_subs if s.tts_done)
        overlap_count = sum(1 for s in chapter_subs if s.id in overlap_sub_ids)

        result.append({
            "chapter_id": c.id,
            "name": c.name,
            "status": c.status,
            "collapsed": c.collapsed,
            "start_sub_index": c.start_sub_index,
            "end_sub_index": c.end_sub_index,
            "total": total,
            "assigned": assigned,
            "tts_done": tts_done,
            "overlap_count": overlap_count,
        })
    return result


@router.post("/project/{project_id}", response_model=ChapterOut)
def create_chapter(project_id: int, data: ChapterCreate, db: Session = Depends(get_db)):
    # Tự gán sort_order = max + 1 nếu chưa có
    last = db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.sort_order.desc()).first()
    sort_order = (last.sort_order + 1) if last else 0
    payload = data.model_dump()
    if 'sort_order' not in payload or payload.get('sort_order') == 0:
        payload['sort_order'] = sort_order
    c = Chapter(project_id=project_id, **payload)
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.post("/project/{project_id}/auto-split", response_model=List[ChapterOut])
def auto_split(project_id: int, data: AutoSplitRequest, db: Session = Depends(get_db)):
    if data.size < 10:
        raise HTTPException(400, "Mỗi đoạn ít nhất 10 dòng")

    # Lấy danh sách index của subs (sorted)
    subs = db.query(Subtitle.index).filter(Subtitle.project_id == project_id).order_by(Subtitle.index).all()
    if not subs:
        raise HTTPException(404, "Project chưa có phụ đề")

    indices = [s[0] for s in subs]
    n = len(indices)

    # Xoá tất cả chapter cũ
    db.query(Chapter).filter(Chapter.project_id == project_id).delete()

    # Cập nhật current_chapter_id của project về null
    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj:
        proj.current_chapter_id = None

    # Tạo chapter mới
    chapters = []
    num_chapters = math.ceil(n / data.size)
    for i in range(num_chapters):
        start_idx = indices[i * data.size]
        end_pos = min((i + 1) * data.size - 1, n - 1)
        end_idx = indices[end_pos]
        c = Chapter(
            project_id=project_id,
            name=f"Đoạn {i + 1}",
            start_sub_index=start_idx,
            end_sub_index=end_idx,
            status="pending",
            sort_order=i,
        )
        db.add(c)
        chapters.append(c)

    db.commit()
    for c in chapters:
        db.refresh(c)
    return chapters


@router.patch("/{chapter_id}", response_model=ChapterOut)
def update_chapter(chapter_id: int, data: ChapterUpdate, db: Session = Depends(get_db)):
    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(404, "Chapter not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    return c


@router.delete("/{chapter_id}")
def delete_chapter(chapter_id: int, db: Session = Depends(get_db)):
    c = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    if not c:
        raise HTTPException(404, "Chapter not found")
    project_id = c.project_id
    # Nếu đây là current chapter của project, clear nó
    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj and proj.current_chapter_id == chapter_id:
        proj.current_chapter_id = None
    db.delete(c); db.commit()
    return {"ok": True}


@router.post("/project/{project_id}/set-current")
def set_current_chapter(project_id: int, data: SetCurrentChapterRequest, db: Session = Depends(get_db)):
    proj = db.query(Project).filter(Project.id == project_id).first()
    if not proj:
        raise HTTPException(404, "Project not found")
    proj.current_chapter_id = data.chapter_id
    db.commit()
    return {"ok": True, "current_chapter_id": data.chapter_id}


@router.delete("/project/{project_id}/all")
def delete_all_chapters(project_id: int, db: Session = Depends(get_db)):
    """Xoá tất cả chapter của project."""
    db.query(Chapter).filter(Chapter.project_id == project_id).delete()
    proj = db.query(Project).filter(Project.id == project_id).first()
    if proj:
        proj.current_chapter_id = None
    db.commit()
    return {"ok": True}
