"""
Router cho cài đặt global của app:
- API keys (gemini / openai / deepseek) — lưu trong AppSetting
- Model presets — preset cho 6 stage + retranslate

Endpoints:
  GET    /dub/api/settings/api-keys            → trả 3 key (masked)
  PUT    /dub/api/settings/api-keys            → set 3 key
  GET    /dub/api/settings/presets             → list preset
  POST   /dub/api/settings/presets             → tạo preset
  PUT    /dub/api/settings/presets/{id}        → update preset
  DELETE /dub/api/settings/presets/{id}        → xóa
  POST   /dub/api/settings/presets/{id}/default → set default
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from dubeditor.database import get_db
from dubeditor.models import ModelPreset, AppSetting

router = APIRouter(prefix="/settings", tags=["settings"])


# ─── Schemas ─────────────────────────────────────────────────────────────────

class ApiKeysIn(BaseModel):
    api_key_gemini:   Optional[str] = None
    api_key_openai:   Optional[str] = None
    api_key_deepseek: Optional[str] = None


class ApiKeysOut(BaseModel):
    api_key_gemini:   str = ""
    api_key_openai:   str = ""
    api_key_deepseek: str = ""


class PresetIn(BaseModel):
    name:        str
    description: Optional[str] = None
    model_stage0:      Optional[str] = None
    model_stage1:      Optional[str] = None
    model_stage2:      Optional[str] = None
    model_stage3:      Optional[str] = None
    model_stage4:      Optional[str] = None
    model_stage5:      Optional[str] = None
    model_retranslate: Optional[str] = None


class PresetOut(PresetIn):
    id:         int
    is_default: bool = False

    class Config:
        from_attributes = True


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _get_setting(db: Session, key: str) -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else ""


def _set_setting(db: Session, key: str, value: str):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


# ─── API keys ────────────────────────────────────────────────────────────────

@router.get("/api-keys", response_model=ApiKeysOut)
def get_api_keys(db: Session = Depends(get_db)):
    """Trả 3 API key đã lưu. Frontend tự quyết hiển thị masked hay không."""
    return ApiKeysOut(
        api_key_gemini=_get_setting(db, "api_key_gemini"),
        api_key_openai=_get_setting(db, "api_key_openai"),
        api_key_deepseek=_get_setting(db, "api_key_deepseek"),
    )


@router.put("/api-keys")
def put_api_keys(body: ApiKeysIn, db: Session = Depends(get_db)):
    """Cập nhật 3 API key. Field nào không truyền → giữ nguyên giá trị cũ."""
    if body.api_key_gemini is not None:
        _set_setting(db, "api_key_gemini", body.api_key_gemini.strip())
    if body.api_key_openai is not None:
        _set_setting(db, "api_key_openai", body.api_key_openai.strip())
    if body.api_key_deepseek is not None:
        _set_setting(db, "api_key_deepseek", body.api_key_deepseek.strip())
    db.commit()
    return {"ok": True}


# ─── Presets CRUD ────────────────────────────────────────────────────────────

@router.get("/presets", response_model=list[PresetOut])
def list_presets(db: Session = Depends(get_db)):
    rows = db.query(ModelPreset).order_by(
        ModelPreset.is_default.desc(),
        ModelPreset.id.asc(),
    ).all()
    return rows


@router.post("/presets", response_model=PresetOut)
def create_preset(body: PresetIn, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Tên preset không được rỗng")
    if db.query(ModelPreset).filter(ModelPreset.name == name).first():
        raise HTTPException(409, f"Đã tồn tại preset tên '{name}'")
    preset = ModelPreset(
        name=name,
        description=body.description,
        model_stage0=body.model_stage0,
        model_stage1=body.model_stage1,
        model_stage2=body.model_stage2,
        model_stage3=body.model_stage3,
        model_stage4=body.model_stage4,
        model_stage5=body.model_stage5,
        model_retranslate=body.model_retranslate,
        is_default=False,
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return preset


@router.put("/presets/{preset_id}", response_model=PresetOut)
def update_preset(preset_id: int, body: PresetIn, db: Session = Depends(get_db)):
    preset = db.query(ModelPreset).filter(ModelPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(404, "Preset not found")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Tên preset không được rỗng")
    # Cho phép giữ name nếu là chính nó, không cho trùng với preset khác
    dup = db.query(ModelPreset).filter(
        ModelPreset.name == name,
        ModelPreset.id != preset_id,
    ).first()
    if dup:
        raise HTTPException(409, f"Đã tồn tại preset tên '{name}'")
    preset.name = name
    preset.description = body.description
    preset.model_stage0 = body.model_stage0
    preset.model_stage1 = body.model_stage1
    preset.model_stage2 = body.model_stage2
    preset.model_stage3 = body.model_stage3
    preset.model_stage4 = body.model_stage4
    preset.model_stage5 = body.model_stage5
    preset.model_retranslate = body.model_retranslate
    db.commit()
    db.refresh(preset)
    return preset


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    preset = db.query(ModelPreset).filter(ModelPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(404, "Preset not found")
    db.delete(preset)
    db.commit()
    return {"ok": True}


@router.post("/presets/{preset_id}/default")
def set_default_preset(preset_id: int, db: Session = Depends(get_db)):
    """Mark 1 preset là default — đồng thời un-mark các preset khác."""
    preset = db.query(ModelPreset).filter(ModelPreset.id == preset_id).first()
    if not preset:
        raise HTTPException(404, "Preset not found")
    db.query(ModelPreset).update({"is_default": False})
    preset.is_default = True
    _set_setting(db, "default_preset_id", str(preset_id))
    db.commit()
    return {"ok": True, "default_preset_id": preset_id}
