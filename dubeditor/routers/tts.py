from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
import asyncio, uuid, logging, sqlite3, sys
from pathlib import Path

from dubeditor.database import get_db
from dubeditor.models import Subtitle, Character
from dubeditor.schemas import TTSRequest, BulkTTSRequest
from dubeditor.routers.ws import broadcast

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.parent.parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
VOXCPM_DB    = str(BASE_DIR / "data" / "voicecast.db")
PUBLIC_DIR   = BASE_DIR / "public"

# Config cố định giống VoiceCast
TTS_CFG      = 3.0
TTS_MODE     = "ultimate"  # dùng ref audio + prompt


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
    pad = int(pad_ms * sr / 1000)
    start = max(0, nonsilent[0] - pad)
    end   = min(len(wav), nonsilent[-1] + pad)
    trimmed = wav[start:end]
    logger.info(f"[Trim] {len(wav)/sr:.3f}s → {len(trimmed)/sr:.3f}s (cắt {(len(wav)-len(trimmed))/sr:.3f}s)")
    return trimmed


def get_role(role_id: str) -> dict | None:
    try:
        conn = sqlite3.connect(VOXCPM_DB)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM roles WHERE id=?", (role_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        logger.error(f"VoiceCast DB error: {e}")
        return None


def _run_tts(text: str, role_id: str):
    """Giống hệt VoiceCast: role_id + text → _generate_sync."""
    main = sys.modules.get("__main__") or sys.modules.get("app")
    generate_sync = getattr(main, "_generate_sync", None)
    if generate_sync is None:
        raise RuntimeError("_generate_sync không tìm thấy")

    role = get_role(role_id)
    if not role:
        raise RuntimeError(f"Không tìm thấy role {role_id}")

    audio_url = role.get("audio", "")
    ref_path  = None
    if audio_url:
        candidate = PUBLIC_DIR / audio_url.lstrip("/")
        if candidate.exists():
            ref_path = str(candidate)

    lora_path = role.get("lora_path", "").strip() or None
    ref_text  = role.get("reference_audio_text", "").strip() or None

    # Chỉ dùng lora_path nếu file tồn tại
    use_lora = lora_path and Path(lora_path).exists()

    # Ultimate mode: có ref audio + prompt text
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


async def do_generate(subtitle_id: int, db: Session):
    s = db.query(Subtitle).filter(Subtitle.id == subtitle_id).first()
    if not s or not s.text.strip():
        return

    # Lấy role_id từ character
    char    = db.query(Character).filter(Character.id == s.character_id).first() if s.character_id else None
    role_id = char.voxcpm_role_id if char else None

    if not role_id:
        await broadcast(s.project_id, {"type": "tts_error", "subtitle_id": s.id, "error": "Chưa gán role VoiceCast"})
        return

    audio_dir = PROJECTS_DIR / str(s.project_id) / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    # Filename cố định theo subtitle_id — gen lại sẽ ghi đè
    filename  = f"{s.id}.wav"
    out_path  = audio_dir / filename
    audio_url = f"/dub/projects/{s.project_id}/audio/{filename}"
    # Xóa file cũ nếu tên khác (file random cũ)
    if s.audio_path:
        old_name = s.audio_path.split("/")[-1]
        if old_name != filename:
            old_file = audio_dir / old_name
            if old_file.exists():
                old_file.unlink()
                logger.info(f"[DubTTS] Xóa file cũ: {old_name}")

    try:
        import soundfile as sf
        logger.info(f"[DubTTS] subtitle={s.id} role={role_id} text='{s.text[:30]}'")

        loop = asyncio.get_event_loop()
        wav  = await loop.run_in_executor(None, _run_tts, s.text.strip(), role_id)

        wav = _trim_silence(wav, threshold_db=-35, sr=48000)
        sf.write(str(out_path), wav, 48000)
        wav_dur = len(wav) / 48000
        logger.info(f"[DubTTS] DONE → {filename} ({wav_dur:.2f}s)")

        s.audio_path   = audio_url
        s.tts_done     = True
        s.wav_duration = wav_dur
        db.commit()

        await broadcast(s.project_id, {"type": "tts_done", "subtitle_id": s.id, "audio_path": audio_url})

    except Exception as e:
        logger.error(f"[DubTTS] ERROR subtitle={s.id}: {e}", exc_info=True)
        await broadcast(s.project_id, {"type": "tts_error", "subtitle_id": s.id, "error": str(e)})


@router.post("/generate")
async def generate_tts(data: TTSRequest, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")
    await do_generate(data.subtitle_id, db)
    db.refresh(s)
    return {"subtitle_id": s.id, "audio_path": s.audio_path}


@router.post("/bulk")
async def bulk_tts(data: BulkTTSRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    subs = db.query(Subtitle).filter(Subtitle.id.in_(data.subtitle_ids)).all()
    if not subs:
        raise HTTPException(404, "No subtitles found")

    async def process():
        for s in subs:
            await do_generate(s.id, db)
            await asyncio.sleep(0.1)

    background_tasks.add_task(process)
    return {"queued": len(subs)}


@router.get("/voices")
async def list_voices():
    try:
        conn = sqlite3.connect(VOXCPM_DB)
        conn.row_factory = sqlite3.Row
        actors = [dict(r) for r in conn.execute("SELECT * FROM actors ORDER BY name")]
        for a in actors:
            a["roles"] = [dict(r) for r in conn.execute(
                "SELECT id, character_name, show_name, type, genre, audio, lora_path, reference_audio_text FROM roles WHERE actor_id=? ORDER BY sort_order",
                (a["id"],)
            )]
        conn.close()
        return {"actors": actors}
    except Exception as e:
        raise HTTPException(500, str(e))


from pydantic import BaseModel

class TrimRequest(BaseModel):
    subtitle_id: int
    threshold_db: float = -35

class TrimBulkRequest(BaseModel):
    subtitle_ids: list[int]
    threshold_db: float = -35

@router.post("/trim")
async def trim_audio(data: TrimRequest, db: Session = Depends(get_db)):
    """Trim silence đầu/cuối 1 subtitle."""
    from dubeditor.models import Subtitle
    import soundfile as sf, numpy as np

    s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_id).first()
    if not s or not s.audio_path:
        raise HTTPException(404, "Subtitle không có audio")

    audio_dir = PROJECTS_DIR / str(s.project_id) / "audio"
    filename  = f"{s.id}.wav"
    path      = audio_dir / filename

    if not path.exists():
        # Tìm file theo audio_path
        old_name = s.audio_path.split("/")[-1]
        path = audio_dir / old_name
        if not path.exists():
            raise HTTPException(404, "File audio không tìm thấy")

    wav, sr = sf.read(str(path))
    before_s = len(wav) / sr

    trimmed = _trim_silence(wav, threshold_db=data.threshold_db, sr=sr)
    after_s = len(trimmed) / sr

    sf.write(str(audio_dir / filename), trimmed, sr)

    # Cập nhật audio_path nếu cần
    audio_url = f"/dub/projects/{s.project_id}/audio/{filename}"
    s.audio_path = audio_url
    db.commit()

    return {"before_s": before_s, "after_s": after_s, "audio_path": audio_url}


@router.post("/trim-bulk")
async def trim_bulk(data: TrimBulkRequest, db: Session = Depends(get_db)):
    """Trim silence cho nhiều subtitle."""
    import soundfile as sf

    from dubeditor.models import Subtitle
    subs = db.query(Subtitle).filter(Subtitle.id.in_(data.subtitle_ids)).all()
    trimmed_count = 0

    for s in subs:
        if not s.audio_path: continue
        audio_dir = PROJECTS_DIR / str(s.project_id) / "audio"
        filename  = f"{s.id}.wav"
        old_name  = s.audio_path.split("/")[-1]

        path = audio_dir / filename
        if not path.exists():
            path = audio_dir / old_name
        if not path.exists(): continue

        try:
            wav, sr = sf.read(str(path))
            trimmed = _trim_silence(wav, threshold_db=data.threshold_db, sr=sr)
            sf.write(str(audio_dir / filename), trimmed, sr)
            audio_url = f"/dub/projects/{s.project_id}/audio/{filename}"
            s.audio_path   = audio_url
            s.wav_duration = len(trimmed) / sr
            trimmed_count += 1
        except Exception as e:
            logger.error(f"Trim error sub {s.id}: {e}")

    db.commit()
    return {"trimmed": trimmed_count, "total": len(subs)}


@router.post("/delete-audio")
async def delete_audio(data: dict, db: Session = Depends(get_db)):
    """Xóa audio của 1 hoặc nhiều subtitle."""
    from dubeditor.models import Subtitle
    ids = data.get("subtitle_ids", [])
    if not ids:
        return {"deleted": 0}
    
    subs = db.query(Subtitle).filter(Subtitle.id.in_(ids)).all()
    deleted = 0
    for s in subs:
        if s.audio_path:
            rel = s.audio_path.lstrip("/").replace("dub/projects/", "data/projects/", 1)
            path = Path(__file__).parent.parent.parent / rel
            if path.exists():
                path.unlink()
            s.audio_path   = None
            s.tts_done     = False
            s.wav_duration = None
            deleted += 1
    db.commit()
    return {"deleted": deleted}
