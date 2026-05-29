from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import asyncio, logging, sys
from pathlib import Path
from pydantic import BaseModel
from typing import Optional

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


def _run_tts(text: str, role_id: str, emotion: Optional[str] = None,
             intensity: int = 5, use_emotion_voice: bool = False,
             force_mode: Optional[str] = None):
    """role_id + text + (emotion, intensity, mode) → VoxCPM.

    Args:
        text: nội dung TTS (KHÔNG có instruction prefix nữa — đã bỏ)
        role_id: VoxCPM role id
        emotion: emotion code v2 của subtitle (sad/angry/tense/...)
        intensity: 1-10
        use_emotion_voice: True → resolve ref theo emotion+intensity (qua emotion_to_mode);
                            False → luôn dùng mode "normal"
        force_mode: override (subtitle.tts_voice_mode). VD: 'sad', 'angry', 'normal'

    Mode VoxCPM:
        - Có ref_path + ref_text → Hi-Fi (giọng giống ref nhất)
        - Chỉ ref_path           → Controllable Cloning
        - Không có gì            → Voice Design (chỉ lora hoặc random)
    """
    main = sys.modules.get("__main__") or sys.modules.get("app")
    generate_sync = getattr(main, "_generate_sync", None)
    if generate_sync is None:
        raise RuntimeError("_generate_sync không tìm thấy")

    db = SessionLocal()
    try:
        role = get_role(role_id, db)
        if not role:
            raise RuntimeError(f"Không tìm thấy role {role_id}")

        # Resolve ref audio + transcript theo voice_modes
        from dubeditor.voice_modes import resolve_ref_for_emotion
        audio_url, ref_text_raw, mode_used = resolve_ref_for_emotion(
            role, emotion=emotion, intensity=intensity,
            use_emotion_voice=use_emotion_voice,
            force_mode=force_mode,
        )

        ref_path = None
        if audio_url:
            candidate = PUBLIC_DIR / audio_url.lstrip("/")
            if candidate.exists():
                ref_path = str(candidate)
            else:
                logger.warning(f"[TTS] Ref audio MISSING ({mode_used}): {candidate}")

        ref_text = (ref_text_raw or "").strip() or None

        lora_path = (role.lora_path or "").strip() or None
        use_lora  = lora_path and Path(lora_path).exists()

        # v3.13: Thêm dấu "," đầu câu để VoxCPM gen audio chuẩn hơn
        # (kỹ thuật prompt — dấu phẩy giúp model "khởi động" giọng tự nhiên,
        #  tránh bị cắt đầu hoặc burst âm thanh ở milisecond đầu).
        # Skip nếu text đã bắt đầu bằng dấu câu/khoảng trắng.
        # KHÔNG có space sau dấu phẩy.
        tts_text = (text or "").strip()
        if tts_text and tts_text[0] not in ',.!?;:，。！？；：、 ':
            tts_text = ',' + tts_text

        # Log mode được dùng (để debug)
        logger.info(
            f"[TTS-MODE] role={role_id} emotion={emotion or '-'} "
            f"intensity={intensity} → mode_used={mode_used} "
            f"ref={'✓' if ref_path else '✗'} ref_text={'✓' if ref_text else '✗'} "
            f"tts_text={tts_text!r}"[:300]
        )

        # Hi-Fi khi đủ ref + ref_text
        if ref_path and ref_text:
            return generate_sync(
                target_text=tts_text,
                reference_wav_path=ref_path,
                prompt_wav_path=ref_path,
                prompt_text=ref_text,
                cfg_value=TTS_CFG,
                lora_path=lora_path if use_lora else None,
            )
        elif ref_path:
            return generate_sync(
                target_text=tts_text,
                reference_wav_path=ref_path,
                cfg_value=TTS_CFG,
                lora_path=lora_path if use_lora else None,
            )
        else:
            return generate_sync(
                target_text=tts_text,
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

        # v3.13 FIX: Phòng vệ kép — không TTS dòng còn ký tự Trung Quốc.
        # Tránh trường hợp import SRT Trung mà chưa dịch, FE bypass filter →
        # BE phát ra audio tiếng Trung. Detect: U+4E00–U+9FFF (CJK Unified
        # Ideographs) hoặc placeholder "[CHƯA DỊCH...]".
        import re as _re
        if _re.search(r'[\u4e00-\u9fff]', text):
            raise RuntimeError(
                f"Sub {subtitle_id} còn ký tự Trung Quốc, chưa được dịch sang tiếng Việt"
            )
        if text.startswith("[CHƯA DỊCH") or text.startswith("[UNTRANSLATED"):
            raise RuntimeError(f"Sub {subtitle_id} placeholder, chưa được dịch")

        # Voice strategy: emotion voice đã bị BỎ — luôn dùng mode "normal"
        # (AI không còn gán emotion; field cũ giữ trong DB nhưng không dùng nữa).
        use_emotion_voice = False
        force_mode = None

        logger.info(
            f"[DubTTS] subtitle={subtitle_id} role={role_id} text={text!r}"[:300]
        )

        loop = asyncio.get_event_loop()
        # v3: dùng shield để chờ executor xong, sau đó check cancellation
        # (executor task không cancel được thật, chỉ có thể bỏ qua kết quả)
        try:
            wav = await asyncio.shield(loop.run_in_executor(
                None, _run_tts, text, role_id,
                s.emotion, s.intensity or 5, use_emotion_voice, force_mode,
            ))
        except asyncio.CancelledError:
            logger.info(f"[DubTTS] Cancelled before/during exec subtitle={subtitle_id}")
            raise

        # Check cancellation sau khi executor xong (worker đã được set cancelled)
        from dubeditor.tts_queue import queue_manager
        pq = queue_manager.queues.get(s.project_id)
        if pq and pq.cancelled:
            logger.info(f"[DubTTS] Skipped save (cancelled) subtitle={subtitle_id}")
            return

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
        # v3: lưu mode đã thực sự dùng để FE hiển thị icon cạnh audio
        if use_emotion_voice:
            # Resolve lại mode đã dùng cho clear
            actual_mode = force_mode
            if not actual_mode:
                from dubeditor.voice_modes import emotion_to_mode
                actual_mode = emotion_to_mode(s.emotion, s.intensity)
            s.audio_voice_mode = actual_mode
        else:
            s.audio_voice_mode = "normal"   # toggle OFF → luôn dùng normal
        db.commit()
        db.refresh(s)

        await broadcast(s.project_id, {
            "type":          "tts_done",
            "subtitle_id":   s.id,
            "audio_path":    audio_url,
            "wav_duration":  wav_dur,
            "audio_voice_mode": s.audio_voice_mode,
        })

        logger.info(f"[DubTTS] DONE subtitle={subtitle_id} dur={wav_dur:.2f}s mode={s.audio_voice_mode}")
    finally:
        db.close()


# ─── Endpoints: TTS generation ───────────────────────────────────────────────

@router.post("/generate")
async def generate_single(data: TTSRequest):
    """Single TTS — đẩy queue priority HIGH. Có thể force voice mode."""
    db = SessionLocal()
    try:
        s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_id).first()
        if not s:
            raise HTTPException(404, "Subtitle not found")
        project_id = s.project_id

        # v3: nếu force voice mode → ghi tạm tts_voice_mode + bật toggle project
        if data.force_voice_mode and data.force_voice_mode in ("normal", "sad", "angry"):
            from dubeditor.models import Project
            s.tts_voice_mode = data.force_voice_mode
            p = db.query(Project).filter(Project.id == project_id).first()
            if p and not p.use_emotion_voice:
                p.use_emotion_voice = True
            db.commit()
    finally:
        db.close()

    await queue_manager.enqueue(project_id, [data.subtitle_id], priority="high")
    return {"queued": 1, "priority": "high", "force_voice_mode": data.force_voice_mode}


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
        subs = db.query(Subtitle).filter(Subtitle.id.in_(data.subtitle_ids)).all()
        if not subs:
            raise HTTPException(404, "Subtitle not found")
        project_id = subs[0].project_id

        # v3: nếu user chỉ định force_voice_mode → set tạm tts_voice_mode
        # + bật use_emotion_voice cho project (để pipeline TTS dùng mode)
        if data.force_voice_mode and data.force_voice_mode in ("normal", "sad", "angry"):
            from dubeditor.models import Project
            for s in subs:
                s.tts_voice_mode = data.force_voice_mode
            # Bật toggle project tạm thời nếu chưa bật
            p = db.query(Project).filter(Project.id == project_id).first()
            if p and not p.use_emotion_voice:
                p.use_emotion_voice = True
            db.commit()
    finally:
        db.close()
    await queue_manager.enqueue(project_id, data.subtitle_ids, data.priority)
    return {"queued": len(data.subtitle_ids), "priority": data.priority,
            "force_voice_mode": data.force_voice_mode}


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


# ─── Delete audio (SOFT) ──────────────────────────────────────────────────────
#
# Thay vì xóa cứng file audio + reset DB, ta:
#   1. Move file audio sang thư mục `data/trash/audio/<token>/` (giữ nguyên cấu
#      trúc tương đối) — token là 1 chuỗi random để tách từng lần xóa.
#   2. Trả về `undo_token` + danh sách backup (sub_id, audio_path cũ, wav_duration)
#      để FE giữ trong toast Undo.
#   3. Khi user bấm "Hoàn tác" → FE gọi /tts/restore-audio với undo_token →
#      BE move file ngược lại + set lại DB.
#
# Bonus: GC định kỳ có thể xóa thư mục trash > N ngày (chưa làm).

import secrets
import shutil

TRASH_AUDIO_DIR = BASE_DIR / "data" / "trash" / "audio"


def _audio_abs_path(audio_path: str) -> Path:
    """Convert audio_path lưu trong DB sang absolute path trên disk."""
    rel = audio_path.lstrip("/").replace("dub/projects/", "data/projects/", 1)
    return BASE_DIR / rel


@router.post("/delete-audio")
async def delete_audio(data: dict, db: Session = Depends(get_db)):
    sub_ids = data.get("subtitle_ids", [])
    if not sub_ids:
        raise HTTPException(400, "Empty subtitle_ids")

    # Token duy nhất cho phiên xóa này — FE giữ để gọi restore
    undo_token = secrets.token_urlsafe(12)
    trash_dir  = TRASH_AUDIO_DIR / undo_token
    trash_dir.mkdir(parents=True, exist_ok=True)

    backup = []   # [{sub_id, audio_path, wav_duration, trash_file}]
    for sid in sub_ids:
        s = db.query(Subtitle).filter(Subtitle.id == sid).first()
        if not s or not s.audio_path:
            continue
        old_audio_path = s.audio_path
        old_wav_dur    = s.wav_duration
        trash_file     = None
        try:
            src = _audio_abs_path(old_audio_path)
            if src.exists():
                # Lưu vào trash với tên = sub id + ext gốc
                trash_file = trash_dir / f"{sid}{src.suffix}"
                shutil.move(str(src), str(trash_file))
        except Exception as e:
            logger.warning(f"Move audio to trash failed (sub={sid}): {e}")
        s.audio_path   = None
        s.tts_done     = False
        s.wav_duration = None
        backup.append({
            "sub_id":       sid,
            "audio_path":   old_audio_path,
            "wav_duration": old_wav_dur,
            "trash_file":   str(trash_file.relative_to(BASE_DIR)) if trash_file else None,
        })
    db.commit()
    return {
        "deleted":    len(backup),
        "undo_token": undo_token,
        "backup":     backup,
    }


@router.post("/restore-audio")
async def restore_audio(data: dict, db: Session = Depends(get_db)):
    """Khôi phục audio đã xóa qua undo_token + backup từ /tts/delete-audio."""
    backup = data.get("backup", [])
    if not backup:
        raise HTTPException(400, "Empty backup")

    restored = 0
    for item in backup:
        sid          = item.get("sub_id")
        audio_path   = item.get("audio_path")
        wav_duration = item.get("wav_duration")
        trash_file   = item.get("trash_file")
        s = db.query(Subtitle).filter(Subtitle.id == sid).first()
        if not s:
            continue
        # Move file từ trash về vị trí cũ (nếu còn)
        try:
            if trash_file and audio_path:
                src = BASE_DIR / trash_file
                dst = _audio_abs_path(audio_path)
                if src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
        except Exception as e:
            logger.warning(f"Restore audio failed (sub={sid}): {e}")
            continue
        s.audio_path   = audio_path
        s.tts_done     = True
        s.wav_duration = wav_duration
        restored += 1
    db.commit()

    # Cleanup trash dir nếu rỗng (best-effort)
    undo_token = data.get("undo_token")
    if undo_token:
        trash_dir = TRASH_AUDIO_DIR / undo_token
        try:
            if trash_dir.exists() and not any(trash_dir.iterdir()):
                trash_dir.rmdir()
        except Exception:
            pass

    return {"restored": restored}


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

    # v3.4: phân nhánh theo có subtitle_ids hay không
    #
    # Có subtitle_ids (frontend đang lọc đoạn):
    #   - KHÔNG đổi Character.tts_speed (giữ nguyên tốc độ chung của NV)
    #   - SET tts_speed = speed cho TỪNG sub trong list (override per-sub)
    #   - Chỉ động vào subs thuộc list + có character_id = char_id
    #
    # Không có subtitle_ids (toàn phim như cũ):
    #   - ĐỔI Character.tts_speed thành speed
    #   - Nếu apply_to_subs → reset override (tts_speed=NULL) cho mọi sub
    #     của NV này để chúng kế thừa tốc độ NV mới
    if data.subtitle_ids:
        # Scoped mode — không đổi tốc độ character, chỉ override các sub trong list
        affected_subs = db.query(Subtitle).filter(
            Subtitle.id.in_(data.subtitle_ids),
            Subtitle.character_id == char_id,
        ).update({"tts_speed": speed}, synchronize_session=False)
        db.commit()
        return {
            "character_id": char_id,
            "tts_speed": speed,
            "subs_updated": affected_subs,
            "scoped": True,
        }

    # Full mode — behavior cũ
    char.tts_speed = speed
    affected_subs = 0
    if data.apply_to_subs:
        affected_subs = db.query(Subtitle).filter(
            Subtitle.character_id == char_id,
            Subtitle.tts_speed.isnot(None)
        ).update({"tts_speed": None}, synchronize_session=False)

    db.commit()
    return {"character_id": char_id, "tts_speed": speed, "subs_cleared": affected_subs}