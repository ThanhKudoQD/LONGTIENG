from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import Character, Role
from dubeditor.schemas import CharacterCreate, CharacterUpdate, CharacterOut

router = APIRouter()


@router.get("/project/{project_id}", response_model=list[CharacterOut])
def get_characters(project_id: int, db: Session = Depends(get_db)):
    return db.query(Character).filter(Character.project_id == project_id).all()


@router.get("/project/{project_id}/voice-modes")
def get_voice_modes_for_project(project_id: int, db: Session = Depends(get_db)):
    """Trả về danh sách voice modes có sẵn cho mỗi character của project.

    Response: {
        "<character_id>": ["normal", "sad", "angry"],
        ...
    }

    Đọc từ Role.voice_modes (DB chung) qua voxcpm_role_id mapping.
    """
    from dubeditor.voice_modes import parse_voice_modes
    chars = db.query(Character).filter(Character.project_id == project_id).all()
    role_ids = [c.voxcpm_role_id for c in chars if c.voxcpm_role_id]
    roles = db.query(Role).filter(Role.id.in_(role_ids)).all() if role_ids else []
    role_modes: dict[str, list[str]] = {}
    for r in roles:
        modes = parse_voice_modes(r.voice_modes)
        avail = [k for k in ("normal", "sad", "angry") if modes.get(k) and modes[k].get("audio")]
        role_modes[r.id] = avail

    result: dict[str, list[str]] = {}
    for c in chars:
        if c.voxcpm_role_id and c.voxcpm_role_id in role_modes:
            result[str(c.id)] = role_modes[c.voxcpm_role_id]
        else:
            result[str(c.id)] = []
    return result


@router.post("/project/{project_id}", response_model=CharacterOut)
def create_character(project_id: int, data: CharacterCreate, db: Session = Depends(get_db)):
    c = Character(project_id=project_id, **data.model_dump())
    db.add(c); db.commit(); db.refresh(c)
    return c


@router.patch("/{character_id}", response_model=CharacterOut)
def update_character(character_id: int, data: CharacterUpdate, db: Session = Depends(get_db)):
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