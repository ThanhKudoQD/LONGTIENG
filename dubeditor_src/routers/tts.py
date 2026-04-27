from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
import asyncio, os, uuid

from database import get_db
from models import Subtitle, Character
from schemas import TTSRequest, BulkTTSRequest
from routers.ws import broadcast

router = APIRouter()
STORAGE = os.getenv("STORAGE_PATH", "../storage")


async def run_tts(text: str, voice_id: str, rate: str, pitch: str, out_path: str):
    import edge_tts
    communicate = edge_tts.Communicate(text, voice_id, rate=rate, pitch=pitch)
    await communicate.save(out_path)


@router.get("/voices")
async def list_voices():
    import edge_tts
    voices = await edge_tts.list_voices()
    vi_voices = [v for v in voices if v["Locale"].startswith("vi-")]
    return vi_voices


@router.post("/generate")
async def generate_tts(data: TTSRequest, db: Session = Depends(get_db)):
    s = db.query(Subtitle).filter(Subtitle.id == data.subtitle_id).first()
    if not s:
        raise HTTPException(404, "Subtitle not found")

    voice = data.voice_id
    if not voice and s.character_id:
        char = db.query(Character).filter(Character.id == s.character_id).first()
        if char:
            voice = char.voice_id
    voice = voice or "vi-VN-HoaiMyNeural"

    if not s.text.strip():
        raise HTTPException(400, "Subtitle text is empty")

    filename = f"{uuid.uuid4()}.mp3"
    out_path = os.path.join(STORAGE, "audio", filename)

    await run_tts(s.text, voice, data.rate, data.pitch, out_path)

    s.audio_path = f"/storage/audio/{filename}"
    s.tts_done = True
    db.commit(); db.refresh(s)

    await broadcast(s.project_id, {
        "type": "tts_done",
        "subtitle_id": s.id,
        "audio_path": s.audio_path
    })

    return {"subtitle_id": s.id, "audio_path": s.audio_path}


@router.post("/bulk")
async def bulk_tts(data: BulkTTSRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    subs = db.query(Subtitle).filter(Subtitle.id.in_(data.subtitle_ids)).all()
    if not subs:
        raise HTTPException(404, "No subtitles found")

    async def process():
        for s in subs:
            voice = data.voice_id
            if not voice and s.character_id:
                char = db.query(Character).filter(Character.id == s.character_id).first()
                if char:
                    voice = char.voice_id
            voice = voice or "vi-VN-HoaiMyNeural"

            if not s.text.strip():
                continue

            filename = f"{uuid.uuid4()}.mp3"
            out_path = os.path.join(STORAGE, "audio", filename)
            try:
                await run_tts(s.text, voice, "+0%", "+0Hz", out_path)
                s.audio_path = f"/storage/audio/{filename}"
                s.tts_done = True
                db.commit()
                await broadcast(s.project_id, {
                    "type": "tts_done",
                    "subtitle_id": s.id,
                    "audio_path": s.audio_path
                })
            except Exception as e:
                await broadcast(s.project_id, {
                    "type": "tts_error",
                    "subtitle_id": s.id,
                    "error": str(e)
                })
            await asyncio.sleep(0.05)

    background_tasks.add_task(process)
    return {"queued": len(subs)}
