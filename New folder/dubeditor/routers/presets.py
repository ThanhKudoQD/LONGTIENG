from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from dubeditor.database import get_db
from dubeditor.models import Character
import json, logging
from sqlalchemy import Column, Integer, String, DateTime, text
from sqlalchemy.ext.declarative import declarative_base
from dubeditor.database import engine

logger = logging.getLogger(__name__)
router = APIRouter()

# Tạo model inline vì không có file models riêng cho preset
def get_presets(db: Session):
    return db.execute(text("SELECT id, name, chars, created_at FROM cast_presets ORDER BY created_at DESC")).fetchall()

def get_preset(db: Session, preset_id: int):
    return db.execute(text("SELECT id, name, chars FROM cast_presets WHERE id=:id"), {"id": preset_id}).fetchone()

class SavePresetRequest(BaseModel):
    name: str
    project_id: int

class LoadPresetRequest(BaseModel):
    preset_id: int
    project_id: int

@router.get("")
def list_presets(db: Session = Depends(get_db)):
    rows = get_presets(db)
    return {"presets": [
        {"id": r[0], "name": r[1], "char_count": len(json.loads(r[2])), "created_at": r[3]}
        for r in rows
    ]}

@router.post("/save")
def save_preset(data: SavePresetRequest, db: Session = Depends(get_db)):
    chars = db.query(Character).filter(Character.project_id == data.project_id).all()
    if not chars:
        raise HTTPException(400, "Project chưa có nhân vật nào")

    chars_data = [
        {
            "name": c.name,
            "color": c.color,
            "avatar": c.avatar,
            "voxcpm_role_id": c.voxcpm_role_id,
            "voxcpm_actor_name": c.voxcpm_actor_name,
            "voxcpm_role_name": c.voxcpm_role_name,
        }
        for c in chars
    ]

    db.execute(text("INSERT INTO cast_presets (name, chars) VALUES (:name, :chars)"),
               {"name": data.name.strip(), "chars": json.dumps(chars_data, ensure_ascii=False)})
    db.commit()
    logger.info(f"[Preset] Saved '{data.name}' with {len(chars_data)} chars")
    return {"ok": True, "char_count": len(chars_data)}

@router.post("/load")
def load_preset(data: LoadPresetRequest, db: Session = Depends(get_db)):
    row = get_preset(db, data.preset_id)
    if not row:
        raise HTTPException(404, "Preset không tìm thấy")

    chars_data = json.loads(row[2])

    # Xóa characters cũ của project
    db.query(Character).filter(Character.project_id == data.project_id).delete()

    # Tạo characters mới
    colors = ["#7C3AED","#0891B2","#DC2626","#059669","#D97706","#DB2777","#2563EB","#65A30D"]
    new_chars = []
    for i, c in enumerate(chars_data):
        char = Character(
            project_id=data.project_id,
            name=c["name"],
            color=c.get("color") or colors[i % len(colors)],
            avatar=c.get("avatar"),
            voxcpm_role_id=c.get("voxcpm_role_id"),
            voxcpm_actor_name=c.get("voxcpm_actor_name"),
            voxcpm_role_name=c.get("voxcpm_role_name"),
        )
        db.add(char)
        new_chars.append(char)

    db.commit()
    for c in new_chars:
        db.refresh(c)

    logger.info(f"[Preset] Loaded '{row[1]}' → project {data.project_id}")
    return {"ok": True, "chars": [
        {"id": c.id, "name": c.name, "color": c.color, "avatar": c.avatar,
         "voxcpm_role_id": c.voxcpm_role_id, "voxcpm_actor_name": c.voxcpm_actor_name,
         "voxcpm_role_name": c.voxcpm_role_name}
        for c in new_chars
    ]}

@router.delete("/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    db.execute(text("DELETE FROM cast_presets WHERE id=:id"), {"id": preset_id})
    db.commit()
    return {"ok": True}
