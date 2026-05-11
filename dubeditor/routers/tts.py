from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import asyncio, logging, sys
from pathlib import Path
from pydantic import BaseModel

from dubeditor.database import get_db, SessionLocal
from dubeditor.models import Subtitle, Character, Role
from dubeditor.schemas import (
    TTSRequest, BulkTTSRequest,
    BulkSetSpeedRequest, CharacterSetSpeedRequest, TTSEnqueueRequest,
)
from dubeditor.routers.ws import broadcast
from dubeditor.tts_queue import queue_manager

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.parent.parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
PUBLIC_DIR   = BASE_DIR / "public"

TTS_CFG  = 3.0
TTS_MODE = "ultimate"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _trim_silence(wav, threshold_db: float = -35, sr: int = 48000, pad_ms: int = 30):
    """Cắt khoảng lặng đầu/cuối. threshold_db=-35 là tối ưu cho TTS tiếng Việt."""
    import numpy as np
    if len(wav) == 0:
        return wav
    threshold = 10 ** (threshold_db / 20)
    amp = np.abs(wav)
    nonsilent = np.where(amp > threshold)[0]
    if len(nonsilent) == 0:
        return wav
    pad   = int(pad_ms * sr / 1000)
    start = max(0, nonsilent[0] - pad)
    end   = min(len(wav), nonsilent[-1] + pad)
    trimmed = wav[start:end]
    logger.info(f"[Trim] {len(wav)/sr:.3f}s → {len(trimmed)/sr:.3f}s (cắt {(len(wav)-len(trimmed))/sr:.3f}s)")
    return trimmed


def get_role(role_id: str, db: Session) -> Role | None:
    """Lấy role từ DB dùng chung (SQLAlchemy)."""
    return db.query(Role).filter(Role.id == role_id).first()


def _run_tts(text: str, role_id: str):
    """role_id + text → _generate_sync (lấy từ app module)."""
    main = sys.modules.get("__main__") or sys.modules.get("app")
    generate_sync = getattr(main, "_generate_sync", None)
    if generate_sync is None:
        raise RuntimeError("_generate_sync không tìm thấy")

    db = SessionLocal()
    try:
        role = get_role(role_id, db)
        if not role:
            raise RuntimeError(f"Không tìm thấy role {role_id}")

        audio_url = role.audio or ""
        ref_path  = None
        if audio_url:
            candidate = PUBLIC_DIR / audio_url.lstrip("/")
            if candidate.exists():
                ref_path = str(candidate)

        lora_path = (role.lora_path or "").strip() or None
        ref_text  = (role.reference_audio_text or "").strip() or None
        use_lora  = lora_path and Path(lora_path).exists()

        if ref_path and ref_text:
            return generate_sync(
                target_text=text,
                reference_wav_path=ref_path,
                prompt_wav_path=ref_path,
                prompt_text=ref_text,
                cfg_value=TTS_CFG,
                lora_path=lora_path if use_lora else None,
            )
        elif ref_path:
            return generate_sync(
                target_text=text,
                reference_wav_path=ref_path,
                cfg_value=TTS_CFG,
                lora_path=lora_path if use_lora else None,
            )
        else:
            return generate_sync(
                target_text=text,
                cfg_value=TTS_CFG,
                lora_path=lora_path if use_lora else None,
            )
    finally:
        db.close()


# ─── Core: do_generate ───────────────────────────────────────────────────────

async def do_generate(subtitle_id: int):
    """
    Gen 1 sub. Tạo session DB mới riêng (vì gọi từ worker async).
    Audio luôn lưu ở 1.0x — speed apply lúc playback (frontend).
    """
    import soundfile as sf

    db = SessionLocal()
    try:
        s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
        if not s:
            raise RuntimeError(f"Sub {subtitle_id} not found")
        if not s.character_id:
            raise RuntimeError(f"Sub {subtitle_id} chưa gán nhân vật")

        char = db.query(Character).filter(Character.id == s.character_id).first()
        if not char or not char.voxcpm_role_id:
            raise RuntimeError("Nhân vật chưa có voice")

        role_id = char.voxcpm_role_id
        text = (s.text or "").strip()
        if not text:
            raise RuntimeError(f"Sub {subtitle_id} không có text")

        logger.info(f"[DubTTS] subtitle={subtitle_id} role={role_id} text={text!r}"[:160])

        loop = asyncio.get_event_loop()
        wav  = await loop.run_in_executor(None, _run_tts, text, role_id)
        wav  = _trim_silence(wav, sr=48000)

        sr      = 48000
        out_dir = PROJECTS_DIR / str(s.project_id) / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename  = f"{s.id}.wav"
        out_path  = out_dir / filename
        sf.write(str(out_path), wav, sr)
        wav_dur   = float(len(wav) / sr)

        audio_url    = f"/dub/projects/{s.project_id}/audio/{filename}"
        s.audio_path  = audio_url
        s.tts_done    = True
        s.wav_duration = wav_dur
        db.commit()
        db.refresh(s)

        await broadcast(s.project_id, {
            "type":        "tts_done",
            "subtitle_id": s.id,
            "audio_path":  audio_url,
            "wav_duration": wav_dur,
        })

        logger.info(f"[DubTTS] DONE subtitle={subtitle_id} dur={wav_dur:.2f}s")
    finally:
        db.close()


# ─── Endpoints: TTS generation ───────────────────────────────────────────────

@router.post("/generate")
async def generate_single(data: TTSRequest):
    """Single TTS — đẩy queue priority HIGH."""
    db = SessionLocal()
    try:
        s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_id).first()
        if not s:
            raise HTTPException(404, "Subtitle not found")
        project_id = s.project_id
    finally:
        db.close()

    await queue_manager.enqueue(project_id, [data.subtitle_id], priority="high")
    return {"queued": 1, "priority": "high"}


@router.post("/bulk")
async def bulk_tts(data: BulkTTSRequest):
    """Bulk TTS — đẩy queue priority NORMAL."""
    if not data.subtitle_ids:
        raise HTTPException(400, "Empty subtitle_ids")
    db = SessionLocal()
    try:
        s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_ids[0]).first()
        if not s:
            raise HTTPException(404, "Subtitle not found")
        project_id = s.project_id
    finally:
        db.close()
    await queue_manager.enqueue(project_id, data.subtitle_ids, priority="normal")
    return {"queued": len(data.subtitle_ids), "priority": "normal"}


@router.post("/queue/enqueue")
async def queue_enqueue(data: TTSEnqueueRequest):
    if not data.subtitle_ids:
        raise HTTPException(400, "Empty subtitle_ids")
    db = SessionLocal()
    try:
        s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_ids[0]).first()
        if not s:
            raise HTTPException(404, "Subtitle not found")
        project_id = s.project_id
    finally:
        db.close()
    await queue_manager.enqueue(project_id, data.subtitle_ids, data.priority)
    return {"queued": len(data.subtitle_ids), "priority": data.priority}


@router.get("/queue/{project_id}")
def queue_state(project_id: int):
    return queue_manager.get_state(project_id)


@router.post("/queue/cancel/{project_id}")
async def queue_cancel(project_id: int):
    await queue_manager.cancel_all(project_id)
    return {"cancelled": True}


@router.post("/bulk/cancel/{project_id}")
async def bulk_cancel_compat(project_id: int):
    await queue_manager.cancel_all(project_id)
    return {"cancelled": True}


# ─── Voices (actors + roles từ DB dùng chung) ────────────────────────────────

@router.get("/voices")
async def list_voices(db: Session = Depends(get_db)):
    from dubeditor.models import Actor
    actors = db.query(Actor).order_by(Actor.name).all()
    result = []
    for a in actors:
        result.append({
            "id":     a.id,
            "name":   a.name,
            "gender": a.gender,
            "avatar": a.avatar,
            "roles": [
                {
                    "id":                   r.id,
                    "character_name":       r.character_name,
                    "show_name":            r.show_name,
                    "type":                 r.type,
                    "genre":                r.genre,
                    "audio":                r.audio,
                    "lora_path":            r.lora_path,
                    "reference_audio_text": r.reference_audio_text,
                }
                for r in a.roles
            ],
        })
    return {"actors": result}


# ─── Trim silence ─────────────────────────────────────────────────────────────

class TrimRequest(BaseModel):
    subtitle_id:  int
    threshold_db: float = -35

class TrimBulkRequest(BaseModel):
    subtitle_ids: list[int]
    threshold_db: float = -35


@router.post("/trim")
async def trim_audio(data: TrimRequest, db: Session = Depends(get_db)):
    import soundfile as sf

    s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_id).first()
    if not s or not s.audio_path:
        raise HTTPException(404, "Subtitle không có audio")

    audio_dir = PROJECTS_DIR / str(s.project_id) / "audio"
    filename  = f"{s.id}.wav"
    path      = audio_dir / filename
    if not path.exists():
        old_name = s.audio_path.split("/")[-1]
        path = audio_dir / old_name
        if not path.exists():
            raise HTTPException(404, "File audio không tìm thấy")

    wav, sr   = sf.read(str(path))
    before_s  = len(wav) / sr
    trimmed   = _trim_silence(wav, threshold_db=data.threshold_db, sr=sr)
    after_s   = len(trimmed) / sr

    sf.write(str(audio_dir / filename), trimmed, sr)
    audio_url      = f"/dub/projects/{s.project_id}/audio/{filename}"
    s.audio_path   = audio_url
    s.wav_duration = after_s
    db.commit()

    await broadcast(s.project_id, {
        "type":        "tts_done",
        "subtitle_id": s.id,
        "audio_path":  audio_url,
        "wav_duration": after_s,
    })
    return {"before_s": before_s, "after_s": after_s, "audio_path": audio_url}


@router.post("/trim-bulk")
async def trim_bulk(data: TrimBulkRequest, db: Session = Depends(get_db)):
    import soundfile as sf

    subs = db.query(Subtitle).filter(Subtitle.id.in_(data.subtitle_ids)).all()
    trimmed_count = 0

    for s in subs:
        if not s.audio_path:
            continue
        audio_dir = PROJECTS_DIR / str(s.project_id) / "audio"
        filename  = f"{s.id}.wav"
        path      = audio_dir / filename
        if not path.exists():
            path = audio_dir / s.audio_path.split("/")[-1]
        if not path.exists():
            continue
        try:
            wav, sr = sf.read(str(path))
            trimmed = _trim_silence(wav, threshold_db=data.threshold_db, sr=sr)
            sf.write(str(audio_dir / filename), trimmed, sr)
            s.audio_path   = f"/dub/projects/{s.project_id}/audio/{filename}"
            s.wav_duration = len(trimmed) / sr
            trimmed_count += 1
        except Exception as e:
            logger.error(f"Trim error sub {s.id}: {e}")

    db.commit()
    for s in subs:
        if s.audio_path and s.wav_duration:
            await broadcast(s.project_id, {
                "type":        "tts_done",
                "subtitle_id": s.id,
                "audio_path":  s.audio_path,
                "wav_duration": s.wav_duration,
            })
    return {"trimmed": trimmed_count, "total": len(subs)}


# ─── Delete audio ─────────────────────────────────────────────────────────────

@router.post("/delete-audio")
async def delete_audio(data: dict, db: Session = Depends(get_db)):
    sub_ids = data.get("subtitle_ids", [])
    if not sub_ids:
        raise HTTPException(400, "Empty subtitle_ids")

    deleted = 0
    for sid in sub_ids:
        s = db.query(Subtitle).filter(Subtitle.id == sid).first()
        if not s or not s.audio_path:
            continue
        try:
            rel  = s.audio_path.lstrip("/").replace("dub/projects/", "data/projects/", 1)
            path = BASE_DIR / rel
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.warning(f"Delete audio file failed: {e}")
        s.audio_path  = None
        s.tts_done    = False
        s.wav_duration = None
        deleted += 1
    db.commit()
    return {"deleted": deleted}


# ─── Speed endpoints ──────────────────────────────────────────────────────────

@router.post("/bulk-set-speed")
async def bulk_set_speed(data: BulkSetSpeedRequest, db: Session = Depends(get_db)):
    if not data.subtitle_ids:
        raise HTTPException(400, "Empty subtitle_ids")
    speed = data.tts_speed
    if speed is not None:
        speed = max(0.5, min(2.0, speed))
    updated = 0
    for sid in data.subtitle_ids:
        s = db.query(Subtitle).filter(Subtitle.id == sid).first()
        if s:
            s.tts_speed = speed
            updated += 1
    db.commit()
    return {"updated": updated, "tts_speed": speed}


@router.post("/character/{char_id}/set-speed")
async def character_set_speed(char_id: int, data: CharacterSetSpeedRequest, db: Session = Depends(get_db)):
    char = db.query(Character).filter(Character.id == char_id).first()
    if not char:
        raise HTTPException(404, "Character not found")

    speed = max(0.5, min(2.0, data.tts_speed))
    char.tts_speed = speed

    affected_subs = 0
    if data.apply_to_subs:
        affected_subs = db.query(Subtitle).filter(
            Subtitle.character_id == char_id,
            Subtitle.tts_speed.isnot(None)
        ).update({"tts_speed": None}, synchronize_session=False)

    db.commit()
    return {"character_id": char_id, "tts_speed": speed, "subs_cleared": affected_subs}