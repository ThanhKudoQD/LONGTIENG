from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Character
from dubeditor.schemas import CharacterCreate, CharacterOut

router = APIRouter()


@router.get("/project/{project_id}", response_model=list[CharacterOut])
def get_characters(project_id: int, db: Session = Depends(get_db)):
    return db.query(Character).filter(Character.project_id == project_id).all()


@router.post("/project/{project_id}", response_model=CharacterOut)
def create_character(project_id: int, data: CharacterCreate, db: Session = Depends(get_db)):
    c = Character(project_id=project_id, **data.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.patch("/{character_id}", response_model=CharacterOut)
def update_character(character_id: int, data: CharacterCreate, db: Session = Depends(get_db)):
    c = db.query(Character).filter(Character.id == character_id).first()
    if not c:
        raise HTTPException(404, "Character not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit(); db.refresh(c)
    return c


@router.delete("/{character_id}")
def delete_character(character_id: int, db: Session = Depends(get_db)):
    c = db.query(Character).filter(Character.id == character_id).first()
    if not c:
        raise HTTPException(404, "Character not found")
    db.delete(c); db.commit()
    return {"ok": True}
