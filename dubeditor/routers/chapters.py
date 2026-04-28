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
