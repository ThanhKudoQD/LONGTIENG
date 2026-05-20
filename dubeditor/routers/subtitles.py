from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from dubeditor.database import get_db
from dubeditor.models import Subtitle
from dubeditor.schemas import SubtitleOut, SubtitleCreate, SubtitleUpdate, BulkAssignRequest

router = APIRouter()


@router.get("/project/{project_id}", response_model=list[SubtitleOut])
def get_subtitles(project_id: int, db: Session = Depends(get_db)):
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).order_by(Subtitle.index).all()

    # Auto-clean: dòng đã được Stage 0 normalize (is_cleaned=True) nhưng
    # cột `text` legacy vẫn chứa TQ gốc lúc import → clear text.
    # Stage 4 sẽ ghi lại text bằng bản dịch Việt sau này.
    dirty = False
    for s in subs:
        if s.is_cleaned and s.text and s.text != (s.text_v1 or ""):
            # text khác text_v1 (Việt) → có thể là TQ legacy, clear đi
            if s.text != s.original_text:  # tránh xóa nhầm
                s.text = s.text_v1 or ""
                dirty = True
    if dirty:
        db.commit()

    return subs


@router.get("/{subtitle_id}", response_model=SubtitleOut)
def get_subtitle(subtitle_id: int, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")
    return s


@router.post("/project/{project_id}", response_model=SubtitleOut)
def create_subtitle(project_id: int, data: SubtitleCreate, db: Session = Depends(get_db)):
    s = Subtitle(project_id=project_id, **data.model_dump())
    db.add(s); db.commit(); db.refresh(s)
    return s


class InsertSubtitleRequest(BaseModel):
    start_time: float
    end_time: Optional[float] = None  # nếu null → tự tính đến sub kế tiếp


@router.post("/project/{project_id}/insert", response_model=SubtitleOut)
def insert_subtitle(project_id: int, data: InsertSubtitleRequest, db: Session = Depends(get_db)):
    """
    Chèn 1 sub mới tại vị trí start_time.
    - Tự tính index: chèn sau sub cuối có start_time <= data.start_time
    - Re-index toàn bộ sub sau điểm chèn (+1)
    - end_time: min(start+3s, next_sub.start_time - 0.1) nếu không truyền
    """
    # Lấy tất cả subs của project sort theo start_time (để tính vị trí chèn)
    all_subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).order_by(Subtitle.start_time).all()

    # Tìm vị trí chèn: sub cuối cùng có start_time <= data.start_time
    insert_after_idx = 0  # index (1-based) sau đó chèn vào
    next_sub_start: Optional[float] = None

    for i, s in enumerate(all_subs):
        if s.start_time <= data.start_time:
            insert_after_idx = s.index
        else:
            # Đây là sub kế tiếp sau điểm chèn
            if next_sub_start is None:
                next_sub_start = s.start_time
            break

    # Tính end_time nếu không truyền
    end_time = data.end_time
    if end_time is None:
        if next_sub_start is not None:
            # Min(start+3s, next_sub.start - 0.1s)
            end_time = min(data.start_time + 3.0, next_sub_start - 0.1)
        else:
            end_time = data.start_time + 2.0
        # Đảm bảo end > start + 0.5s tối thiểu
        end_time = max(end_time, data.start_time + 0.5)

    new_index = insert_after_idx + 1

    # Re-index tất cả sub có index >= new_index (+1)
    db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.index >= new_index
    ).update({"index": Subtitle.index + 1}, synchronize_session=False)

    # Tạo sub mới
    s = Subtitle(
        project_id=project_id,
        index=new_index,
        start_time=round(data.start_time, 3),
        end_time=round(end_time, 3),
        text="",
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


@router.patch("/{subtitle_id}", response_model=SubtitleOut)
def update_subtitle(subtitle_id: int, data: SubtitleUpdate, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    _sync_variant_active(s)
    db.commit(); db.refresh(s)
    return s


@router.patch("/by-index/{project_id}/{subtitle_index}", response_model=SubtitleOut)
def update_subtitle_by_index(project_id: int, subtitle_index: int, data: SubtitleUpdate, db: Session = Depends(get_db)):
    """PATCH subtitle theo index SRT (số thứ tự, 1-based) thay vì DB id.
    Dùng cho QC apply fix — FE chỉ biết subtitle index từ SRT, không biết DB id.
    """
    s = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.index == subtitle_index,
    ).first()
    if not s:
        raise HTTPException(404, f"Subtitle index={subtitle_index} not found in project {project_id}")
    for k, v in data.model_dump(exclude_none=True).items():
        setattr(s, k, v)
    _sync_variant_active(s)
    db.commit(); db.refresh(s)
    return s


def _sync_variant_active(s: Subtitle) -> None:
    """Sync text active từ variant_selected. Recompute CPS.

    Logic:
    - Nếu update đến text_v1/text_v2/variant_selected → đồng bộ Subtitle.text
    - Nếu update text trực tiếp → cũng update vào variant đang active để giữ nhất quán
    """
    variant = s.variant_selected or 1
    if variant == 2 and s.text_v2:
        s.text = s.text_v2
    elif s.text_v1 is not None:
        s.text = s.text_v1
    # Recompute CPS
    duration = max(0.01, (s.end_time or 0.0) - (s.start_time or 0.0))
    text = s.text or ""
    if duration > 0 and text:
        s.cps_value = len(text.strip()) / duration
    else:
        s.cps_value = None
    # Reset TTS cache vì text có thể đã đổi
    # (chỉ reset nếu text_v1/v2 hoặc variant_selected có trong fields update)
    # → đơn giản: chỉ reset nếu cần. UI sẽ xử lý.


# ─── Backup helpers cho undo delete subtitle ─────────────────────────────────
#
# Khi xóa, BE trả về snapshot Subtitle để FE giữ. Khi user bấm "Hoàn tác",
# FE gửi snapshot ngược lên /restore → BE recreate row (giữ id cũ).
#
# LƯU Ý audio_path:
#   - File audio gốc KHÔNG bị xóa khi delete subtitle (chỉ row DB bị xóa).
#   - Vì vậy restore chỉ cần insert lại row → audio_path cũ vẫn dùng được.

_BACKUP_FIELDS = (
    "id", "project_id", "character_id", "scene_id", "index",
    "start_time", "end_time", "text", "original_text",
    "audio_path", "audio_offset", "tts_done", "wav_duration", "tts_speed",
    "audio_voice_mode",
    "speaker_zh", "speaker_confidence", "speaker_reason",
    "emotion", "intensity", "cps_value",
    "needs_review", "review_reason", "text_draft", "is_hook",
    "translation_version",
    "text_v1", "text_v2", "variant_selected",
    "is_noise", "is_cleaned", "original_raw", "clean_reason",
    "chunk_id", "tts_voice_mode",
)


def _snapshot_subtitle(s: Subtitle) -> dict:
    return {k: getattr(s, k) for k in _BACKUP_FIELDS}


@router.delete("/{subtitle_id}")
def delete_subtitle(subtitle_id: int, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")
    backup = _snapshot_subtitle(s)
    db.delete(s); db.commit()
    return {"ok": True, "backup": [backup]}


@router.post("/bulk-assign")
def bulk_assign(data: BulkAssignRequest, db: Session = Depends(get_db)):
    updated = db.query(Subtitle).filter(
        Subtitle.id.in_(data.subtitle_ids)
    ).update({"character_id": data.character_id}, synchronize_session=False)
    db.commit()
    return {"updated": updated}


@router.post("/bulk-delete")
async def bulk_delete(data: dict, db: Session = Depends(get_db)):
    ids = data.get("subtitle_ids", [])
    if not ids: return {"deleted": 0, "backup": []}
    rows = db.query(Subtitle).filter(Subtitle.id.in_(ids)).all()
    backup = [_snapshot_subtitle(s) for s in rows]
    db.query(Subtitle).filter(Subtitle.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return {"deleted": len(backup), "backup": backup}


@router.post("/restore")
def restore_subtitles(data: dict, db: Session = Depends(get_db)):
    """Khôi phục subtitles đã xóa. FE truyền backup từ /bulk-delete hoặc DELETE."""
    backup = data.get("backup", [])
    if not backup:
        raise HTTPException(400, "Empty backup")

    restored = []
    for item in backup:
        # Bỏ qua nếu id đã tồn tại (user đã restore rồi hoặc trùng)
        sid = item.get("id")
        if sid and db.query(Subtitle).filter(Subtitle.id == sid).first():
            continue
        # Lọc chỉ giữ các field hợp lệ
        kwargs = {k: v for k, v in item.items() if k in _BACKUP_FIELDS}
        s = Subtitle(**kwargs)
        db.add(s)
        restored.append(sid)
    db.commit()
    return {"restored": len(restored), "ids": restored}