from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
import subprocess, os, uuid, tempfile

from database import get_db
from models import Project, Subtitle
from routers.ws import broadcast

router = APIRouter()
STORAGE = os.getenv("STORAGE_PATH", "../storage")


class ExportAudioRequest(BaseModel):
    project_id: int

class ExportVideoRequest(BaseModel):
    project_id: int
    burn_subtitles: bool = True


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
        raise HTTPException(400, "No TTS audio available")

    out_file = os.path.join(STORAGE, "exports", f"audio_{data.project_id}_{uuid.uuid4().hex[:8]}.mp3")

    async def do_export():
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            for s in subs:
                audio_local = s.audio_path.replace("/storage", STORAGE) if s.audio_path else None
                if audio_local and os.path.exists(audio_local):
                    delay_ms = int((s.start_time + s.audio_offset) * 1000)
                    f.write(f"file '{audio_local}'\n")
            inputs_file = f.name

        # Build complex filter: each audio at correct timestamp
        filter_parts = []
        input_args = []
        valid_subs = [s for s in subs if s.audio_path]

        for i, s in enumerate(valid_subs):
            audio_local = s.audio_path.replace("/storage", STORAGE)
            if not os.path.exists(audio_local):
                continue
            delay_ms = int((s.start_time + s.audio_offset) * 1000)
            input_args += ["-i", audio_local]
            filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

        if not filter_parts:
            return

        mix_inputs = "".join(f"[a{i}]" for i in range(len(filter_parts)))
        filter_complex = ";".join(filter_parts) + f";{mix_inputs}amix=inputs={len(filter_parts)}:normalize=0[out]"

        cmd = ["ffmpeg", "-y"] + input_args + [
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-ar", "44100",
            out_file
        ]

        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0:
            await broadcast(data.project_id, {
                "type": "export_done",
                "kind": "audio",
                "path": f"/storage/exports/{os.path.basename(out_file)}"
            })
        else:
            await broadcast(data.project_id, {
                "type": "export_error",
                "error": proc.stderr.decode()[:500]
            })

        os.unlink(inputs_file)

    background_tasks.add_task(do_export)
    return {"status": "processing", "message": "Export started, listen for WebSocket notification"}


@router.post("/video")
async def export_video(data: ExportVideoRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == data.project_id).first()
    if not p or not p.video_path:
        raise HTTPException(404, "Project or video not found")

    video_local = p.video_path.replace("/storage", STORAGE)
    if not os.path.exists(video_local):
        raise HTTPException(404, "Video file not found on disk")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == data.project_id,
        Subtitle.tts_done == True
    ).order_by(Subtitle.index).all()

    out_file = os.path.join(STORAGE, "exports", f"video_{data.project_id}_{uuid.uuid4().hex[:8]}.mp4")

    async def do_export():
        valid_subs = [s for s in subs if s.audio_path and os.path.exists(s.audio_path.replace("/storage", STORAGE))]

        input_args = ["-i", video_local]
        filter_parts = []

        for i, s in enumerate(valid_subs):
            audio_local = s.audio_path.replace("/storage", STORAGE)
            delay_ms = int((s.start_time + s.audio_offset) * 1000)
            input_args += ["-i", audio_local]
            filter_parts.append(f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

        if filter_parts:
            mix_inputs = "[0:a]" + "".join(f"[a{i}]" for i in range(len(filter_parts)))
            filter_complex = ";".join(filter_parts) + f";{mix_inputs}amix=inputs={len(filter_parts)+1}:normalize=0[outa]"
            audio_map = ["-filter_complex", filter_complex, "-map", "0:v", "-map", "[outa]"]
        else:
            audio_map = ["-map", "0"]

        cmd = ["ffmpeg", "-y"] + input_args + audio_map + [
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            out_file
        ]

        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0:
            await broadcast(data.project_id, {
                "type": "export_done",
                "kind": "video",
                "path": f"/storage/exports/{os.path.basename(out_file)}"
            })
        else:
            await broadcast(data.project_id, {
                "type": "export_error",
                "error": proc.stderr.decode()[:500]
            })

    background_tasks.add_task(do_export)
    return {"status": "processing"}


@router.get("/download/{filename}")
def download_file(filename: str):
    path = os.path.join(STORAGE, "exports", filename)
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=filename)
