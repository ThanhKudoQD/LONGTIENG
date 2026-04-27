from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path
import os, uuid, logging

from dubeditor.database import get_db
from dubeditor.models import Project, Subtitle
from dubeditor.routers.ws import broadcast

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent.parent.parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
EXPORTS_DIR  = PROJECTS_DIR / "_exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def resolve_audio(audio_url: str) -> Path | None:
    """Chuyển /dub/projects/1/audio/x.wav → absolute path."""
    if not audio_url:
        return None
    rel = audio_url.lstrip("/").replace("dub/projects/", "data/projects/", 1)
    p = BASE_DIR / rel
    return p if p.exists() else None


class ExportAudioRequest(BaseModel):
    project_id: int

class ExportVideoRequest(BaseModel):
    project_id: int


@router.post("/audio")
async def export_audio(data: ExportAudioRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == data.project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == data.project_id,
        Subtitle.tts_done == True
    ).order_by(Subtitle.index).all()

    if not subs:
        raise HTTPException(400, "Chưa có TTS audio nào")

    # Lấy duration video để biết độ dài output
    video_dur = p.duration or 0

    out_name = f"audio_{data.project_id}.wav"
    out_path = EXPORTS_DIR / out_name

    async def do_export():
        try:
            import numpy as np
            import soundfile as sf

            await broadcast(data.project_id, {"type": "export_progress", "pct": 0, "msg": "Đang chuẩn bị..."})

            SR = 48000

            # Tính tổng độ dài output = max(video_dur, last audio end)
            total_dur = video_dur
            valid = []
            for s in subs:
                path = resolve_audio(s.audio_path)
                if not path:
                    continue
                try:
                    info = sf.info(str(path))
                    wav_dur = info.duration
                    start   = s.start_time + (s.audio_offset or 0)
                    end     = start + wav_dur
                    total_dur = max(total_dur, end + 0.5)
                    valid.append((s, path, start, wav_dur))
                except Exception as e:
                    logger.warning(f"Skip {s.id}: {e}")

            if not valid:
                await broadcast(data.project_id, {"type": "export_error", "error": "Không đọc được file audio"})
                return

            # Tạo buffer silence
            total_samples = int(total_dur * SR)
            out = np.zeros(total_samples, dtype=np.float32)

            await broadcast(data.project_id, {"type": "export_progress", "pct": 10, "msg": f"Mix {len(valid)} audio..."})

            for i, (s, path, start, wav_dur) in enumerate(valid):
                try:
                    wav, sr = sf.read(str(path), dtype='float32')
                    # Mono nếu stereo
                    if wav.ndim > 1:
                        wav = wav.mean(axis=1)
                    # Resample nếu cần
                    if sr != SR:
                        # Simple resample bằng numpy interpolation
                        new_len = int(len(wav) * SR / sr)
                        wav = np.interp(
                            np.linspace(0, len(wav), new_len),
                            np.arange(len(wav)), wav
                        ).astype(np.float32)

                    # Đặt audio vào đúng vị trí
                    start_sample = int(start * SR)
                    end_sample   = min(start_sample + len(wav), total_samples)
                    wav_slice    = wav[:end_sample - start_sample]
                    out[start_sample:end_sample] += wav_slice

                    pct = 10 + int((i + 1) / len(valid) * 80)
                    await broadcast(data.project_id, {
                        "type": "export_progress",
                        "pct": pct,
                        "msg": f"Mix {i+1}/{len(valid)}: #{s.index}"
                    })
                except Exception as e:
                    logger.warning(f"Mix error sub {s.id}: {e}")

            # Normalize để tránh clipping
            peak = np.abs(out).max()
            if peak > 1.0:
                out = out / peak * 0.95

            await broadcast(data.project_id, {"type": "export_progress", "pct": 95, "msg": "Đang lưu file..."})

            sf.write(str(out_path), out, SR)

            file_size = out_path.stat().st_size / 1024 / 1024
            logger.info(f"[Export] Done: {out_path} ({file_size:.1f} MB, {total_dur:.1f}s)")

            await broadcast(data.project_id, {
                "type": "export_done",
                "kind": "audio",
                "path": f"/dub/exports/{out_name}",
                "duration": round(total_dur, 2),
                "size_mb": round(file_size, 1),
            })

        except Exception as e:
            logger.error(f"Export error: {e}", exc_info=True)
            await broadcast(data.project_id, {"type": "export_error", "error": str(e)})

    background_tasks.add_task(do_export)
    return {"status": "processing"}


@router.post("/video")
async def export_video(data: ExportVideoRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == data.project_id).first()
    if not p or not p.video_path:
        raise HTTPException(404, "Project hoặc video không tìm thấy")

    # Resolve video path
    video_rel   = p.video_path.lstrip("/").replace("dub/videos/", "data/projects/_videos/", 1)
    video_local = str(BASE_DIR / video_rel)
    if not os.path.exists(video_local):
        raise HTTPException(404, f"Video không tìm thấy: {video_local}")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == data.project_id,
        Subtitle.tts_done == True
    ).order_by(Subtitle.index).all()

    out_name = f"video_{data.project_id}.mp4"
    out_path = str(EXPORTS_DIR / out_name)

    async def do_export():
        import subprocess
        try:
            await broadcast(data.project_id, {"type": "export_progress", "pct": 0, "msg": "Đang chuẩn bị video..."})

            valid = []
            for s in subs:
                path = resolve_audio(s.audio_path)
                if path:
                    valid.append((s, str(path)))

            input_args   = ["-i", video_local]
            filter_parts = []

            for i, (s, path) in enumerate(valid):
                delay_ms = int((s.start_time + (s.audio_offset or 0)) * 1000)
                input_args += ["-i", path]
                filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

            await broadcast(data.project_id, {"type": "export_progress", "pct": 20, "msg": f"Mix {len(valid)} audio vào video..."})

            if filter_parts:
                mix   = "[0:a]" + "".join(f"[a{i}]" for i in range(len(filter_parts)))
                fc    = ";".join(filter_parts) + f";{mix}amix=inputs={len(filter_parts)+1}:normalize=0[outa]"
                amap  = ["-filter_complex", fc, "-map", "0:v", "-map", "[outa]"]
            else:
                amap  = ["-map", "0"]

            cmd = ["ffmpeg", "-y"] + input_args + amap + [
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_path
            ]

            proc = subprocess.run(cmd, capture_output=True)

            if proc.returncode == 0:
                await broadcast(data.project_id, {
                    "type": "export_done", "kind": "video",
                    "path": f"/dub/exports/{out_name}",
                })
            else:
                await broadcast(data.project_id, {
                    "type": "export_error",
                    "error": proc.stderr.decode()[:500]
                })
        except Exception as e:
            await broadcast(data.project_id, {"type": "export_error", "error": str(e)})

    background_tasks.add_task(do_export)
    return {"status": "processing"}


@router.get("/download/{filename}")
def download_file(filename: str):
    path = EXPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), filename=filename)
