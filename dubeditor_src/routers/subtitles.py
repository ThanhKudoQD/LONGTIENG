from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Subtitle
from schemas import SubtitleOut, SubtitleCreate, SubtitleUpdate, BulkAssignRequest

router = APIRouter()


@router.get("/project/{project_id}", response_model=list[SubtitleOut])
def get_subtitles(project_id: int, db: Session = Depends(get_db)):
    return db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).order_by(Subtitle.index).all()


@router.post("/project/{project_id}", response_model=SubtitleOut)
def create_subtitle(project_id: int, data: SubtitleCreate, db: Session = Depends(get_db)):
    s = Subtitle(project_id=project_id, **data.model_dump())
    db.add(s); db.commit(); db.refresh(s)
    return s


@router.patch("/{subtitle_id}", response_model=SubtitleOut)
def update_subtitle(subtitle_id: int, data: SubtitleUpdate, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    db.commit(); db.refresh(s)
    return s


@router.delete("/{subtitle_id}")
def delete_subtitle(subtitle_id: int, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")
    db.delete(s); db.commit()
    return {"ok": True}


@router.post("/bulk-assign")
def bulk_assign(data: BulkAssignRequest, db: Session = Depends(get_db)):
    updated = db.query(Subtitle).filter(
        Subtitle.id.in_(data.subtitle_ids)
    ).update({"character_id": data.character_id}, synchronize_session=False)
    db.commit()
    return {"updated": updated}
