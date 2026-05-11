from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path
import os, logging

from dubeditor.database import get_db
from dubeditor.models import Project, Subtitle, Character
from dubeditor.routers.ws import broadcast

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.parent.parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
EXPORTS_DIR  = PROJECTS_DIR / "_exports"
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def resolve_audio(audio_url: str) -> Path | None:
    """Chuyển /dub/projects/1/audio/x.wav → absolute path."""
    if not audio_url:
        return None
    rel = audio_url.lstrip("/").replace("dub/projects/", "data/projects/", 1)
    p = BASE_DIR / rel
    return p if p.exists() else None


def get_effective_speed(sub: Subtitle, char_speed_map: dict[int, float]) -> float:
    """sub.tts_speed → character.tts_speed → 1.0, clamp 0.5-2.0"""
    if sub.tts_speed is not None:
        speed = sub.tts_speed
    elif sub.character_id and sub.character_id in char_speed_map:
        speed = char_speed_map[sub.character_id]
    else:
        speed = 1.0
    return max(0.5, min(2.0, speed))


def format_srt_time(seconds: float) -> str:
    """0.0 → '00:00:00,000'"""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─── Request schemas ────────────────────────────────────────────────────────

class ExportAudioRequest(BaseModel):
    project_id: int

class ExportVideoRequest(BaseModel):
    project_id: int

class ExportSrtRequest(BaseModel):
    project_id: int
    only_with_audio: bool = False  # nếu True, chỉ xuất sub đã có TTS (đồng bộ với audio mix)


# ─── EXPORT AUDIO ────────────────────────────────────────────────────────────

@router.post("/audio")
async def export_audio(data: ExportAudioRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Mix tất cả TTS audio thành 1 file WAV.
    - Apply effective speed cho từng audio (sub.tts_speed → character.tts_speed → 1.0)
    - Cap output length theo video duration (không kéo dài hơn video)
    """
    p = db.query(Project).filter(Project.id == data.project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == data.project_id,
        Subtitle.tts_done == True
    ).order_by(Subtitle.index).all()

    if not subs:
        raise HTTPException(400, "Chưa có TTS audio nào")

    # Map character_id → tts_speed (default 1.0)
    chars = db.query(Character).filter(Character.project_id == data.project_id).all()
    char_speed_map = {c.id: (c.tts_speed if c.tts_speed is not None else 1.0) for c in chars}

    video_dur = p.duration or 0

    out_name = f"audio_{data.project_id}.wav"
    out_path = EXPORTS_DIR / out_name

    async def do_export():
        try:
            import numpy as np
            import soundfile as sf
            import subprocess, tempfile

            await broadcast(data.project_id, {"type": "export_progress", "pct": 0, "msg": "Đang chuẩn bị..."})

            SR = 48000

            # CAP theo video length
            if video_dur > 0:
                total_dur = video_dur
            else:
                # Không có video → fallback: dùng max end + 0.5s
                total_dur = 0
                for s in subs:
                    path = resolve_audio(s.audio_path)
                    if not path:
                        continue
                    try:
                        info = sf.info(str(path))
                        speed = get_effective_speed(s, char_speed_map)
                        eff_dur = info.duration / speed
                        end = (s.start_time + (s.audio_offset or 0)) + eff_dur
                        if end > total_dur:
                            total_dur = end
                    except Exception:
                        pass
                total_dur += 0.5

            # Tạo buffer silence
            total_samples = int(total_dur * SR)
            out = np.zeros(total_samples, dtype=np.float32)

            # Lọc các sub có audio đọc được
            valid = []
            for s in subs:
                path = resolve_audio(s.audio_path)
                if path:
                    valid.append((s, path))

            if not valid:
                await broadcast(data.project_id, {"type": "export_error", "error": "Không đọc được file audio"})
                return

            await broadcast(data.project_id, {"type": "export_progress", "pct": 10, "msg": f"Mix {len(valid)} audio..."})

            # Tạo thư mục tạm cho file đã apply atempo
            with tempfile.TemporaryDirectory() as tmpdir:
                tmpdir_path = Path(tmpdir)

                for i, (s, path) in enumerate(valid):
                    try:
                        speed = get_effective_speed(s, char_speed_map)

                        # Nếu cần đổi speed → dùng ffmpeg atempo (giữ pitch, chất lượng cao)
                        # KHÁC với np.interp (đổi pitch như chipmunk)
                        if abs(speed - 1.0) > 0.001:
                            tmp_path = tmpdir_path / f"speed_{s.id}.wav"
                            cmd = [
                                "ffmpeg", "-y", "-loglevel", "error",
                                "-i", str(path),
                                "-filter:a", f"atempo={speed:.4f}",
                                "-ar", str(SR),
                                str(tmp_path)
                            ]
                            proc = subprocess.run(cmd, capture_output=True)
                            if proc.returncode != 0:
                                logger.warning(f"atempo failed sub {s.id}: {proc.stderr.decode()[:200]}")
                                # Fallback: dùng file gốc
                                read_path = path
                            else:
                                read_path = tmp_path
                        else:
                            read_path = path

                        wav, sr = sf.read(str(read_path), dtype='float32')
                        # Mono nếu stereo
                        if wav.ndim > 1:
                            wav = wav.mean(axis=1)
                        # Resample nếu cần (rare — atempo đã ra SR)
                        if sr != SR:
                            new_len = int(len(wav) * SR / sr)
                            wav = np.interp(
                                np.linspace(0, len(wav), new_len),
                                np.arange(len(wav)), wav
                            ).astype(np.float32)

                        # Đặt audio vào đúng vị trí, CẮT nếu vượt video length
                        start = s.start_time + (s.audio_offset or 0)
                        start_sample = int(start * SR)
                        if start_sample >= total_samples:
                            continue
                        end_sample = min(start_sample + len(wav), total_samples)
                        wav_slice = wav[:end_sample - start_sample]
                        out[start_sample:end_sample] += wav_slice

                        pct = 10 + int((i + 1) / len(valid) * 80)
                        await broadcast(data.project_id, {
                            "type": "export_progress",
                            "pct": pct,
                            "msg": f"Mix {i+1}/{len(valid)}: #{s.index}"
                        })
                    except Exception as e:
                        logger.warning(f"Mix error sub {s.id}: {e}")

            # Normalize tránh clipping
            peak = np.abs(out).max()
            if peak > 1.0:
                out = out / peak * 0.95

            await broadcast(data.project_id, {"type": "export_progress", "pct": 95, "msg": "Đang lưu file..."})

            sf.write(str(out_path), out, SR)

            file_size = out_path.stat().st_size / 1024 / 1024
            logger.info(f"[Export] Audio: {out_path} ({file_size:.1f} MB, {total_dur:.1f}s)")

            await broadcast(data.project_id, {
                "type": "export_done",
                "kind": "audio",
                "path": f"/dub/exports/{out_name}",
                "duration": round(total_dur, 2),
                "size_mb": round(file_size, 1),
            })

        except Exception as e:
            logger.error(f"Export audio error: {e}", exc_info=True)
            await broadcast(data.project_id, {"type": "export_error", "error": str(e)})

    background_tasks.add_task(do_export)
    return {"status": "processing"}


# ─── EXPORT VIDEO ────────────────────────────────────────────────────────────

@router.post("/video")
async def export_video(data: ExportVideoRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Ghép TTS audio vào video gốc.
    - Apply speed cho từng audio bằng ffmpeg atempo
    - Cap audio theo video duration (-shortest)
    """
    p = db.query(Project).filter(Project.id == data.project_id).first()
    if not p or not p.video_path:
        raise HTTPException(404, "Project hoặc video không tìm thấy")

    video_rel   = p.video_path.lstrip("/").replace("dub/videos/", "data/projects/_videos/", 1)
    video_local = str(BASE_DIR / video_rel)
    if not os.path.exists(video_local):
        raise HTTPException(404, f"Video không tìm thấy: {video_local}")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == data.project_id,
        Subtitle.tts_done == True
    ).order_by(Subtitle.index).all()

    chars = db.query(Character).filter(Character.project_id == data.project_id).all()
    char_speed_map = {c.id: (c.tts_speed if c.tts_speed is not None else 1.0) for c in chars}

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
                speed = get_effective_speed(s, char_speed_map)

                input_args += ["-i", path]
                # Build filter chain cho audio này:
                # [N:a] [atempo=speed,] adelay=...,...  → [aN]
                if abs(speed - 1.0) > 0.001:
                    filter_parts.append(
                        f"[{i+1}:a]atempo={speed:.4f},adelay={delay_ms}|{delay_ms}[a{i}]"
                    )
                else:
                    filter_parts.append(
                        f"[{i+1}:a]adelay={delay_ms}|{delay_ms}[a{i}]"
                    )

            await broadcast(data.project_id, {"type": "export_progress", "pct": 20, "msg": f"Mix {len(valid)} audio vào video..."})

            if filter_parts:
                mix = "[0:a]" + "".join(f"[a{i}]" for i in range(len(filter_parts)))
                fc  = ";".join(filter_parts) + f";{mix}amix=inputs={len(filter_parts)+1}:normalize=0[outa]"
                amap = ["-filter_complex", fc, "-map", "0:v", "-map", "[outa]"]
            else:
                amap = ["-map", "0"]

            # -shortest: cap output length theo video gốc (audio không kéo dài hơn video)
            cmd = ["ffmpeg", "-y"] + input_args + amap + [
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-shortest",
                out_path
            ]

            proc = subprocess.run(cmd, capture_output=True)

            if proc.returncode == 0:
                size_mb = os.path.getsize(out_path) / 1024 / 1024
                logger.info(f"[Export] Video: {out_path} ({size_mb:.1f} MB)")
                await broadcast(data.project_id, {
                    "type": "export_done", "kind": "video",
                    "path": f"/dub/exports/{out_name}",
                    "size_mb": round(size_mb, 1),
                })
            else:
                err = proc.stderr.decode(errors='replace')[:500]
                logger.error(f"[Export] Video ffmpeg error: {err}")
                await broadcast(data.project_id, {
                    "type": "export_error",
                    "error": err
                })
        except Exception as e:
            logger.error(f"Export video error: {e}", exc_info=True)
            await broadcast(data.project_id, {"type": "export_error", "error": str(e)})

    background_tasks.add_task(do_export)
    return {"status": "processing"}


# ─── EXPORT SRT (đồng bộ với audio đã mix) ───────────────────────────────────

@router.post("/srt")
async def export_srt(data: ExportSrtRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == data.project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    query = db.query(Subtitle).filter(Subtitle.project_id == data.project_id)
    if data.only_with_audio:
        query = query.filter(Subtitle.tts_done == True)
    
    # Quan trọng: Order by index hoặc start_time để đảm bảo thứ tự thời gian
    subs = query.order_by(Subtitle.index).all()

    if not subs:
        raise HTTPException(400, "Không có phụ đề")

    chars = db.query(Character).filter(Character.project_id == data.project_id).all()
    char_speed_map = {c.id: (c.tts_speed if c.tts_speed is not None else 1.0) for c in chars}
    video_dur = p.duration or 0

    out_name = f"subtitles_{data.project_id}.srt"
    out_path = EXPORTS_DIR / out_name

    async def do_export():
        try:
            await broadcast(data.project_id, {"type": "export_progress", "pct": 10, "msg": "Đang tính toán thời gian..."})

            # Bước 1: Tính toán thời gian thực tế (có tính offset và speed) cho tất cả các sub
            processed_items = []
            for s in subs:
                offset = s.audio_offset or 0
                start = s.start_time + offset
                
                if s.tts_done and s.wav_duration:
                    speed = get_effective_speed(s, char_speed_map)
                    end = start + (s.wav_duration / speed)
                else:
                    end = s.end_time + offset

                # Giới hạn bởi thời lượng video
                if video_dur > 0:
                    if start >= video_dur: continue
                    if end > video_dur: end = video_dur

                text = (s.text or "").strip()
                if not text: continue
                
                processed_items.append({
                    "start": start,
                    "end": end,
                    "text": text
                })

            # Bước 2: Xử lý chống chồng lấn (Overlap Prevention)
            # Nếu end của sub i > start của sub i+1, thì cắt end của sub i
            for i in range(len(processed_items) - 1):
                current_sub = processed_items[i]
                next_sub = processed_items[i+1]
                
                if current_sub["end"] > next_sub["start"]:
                    # Chỉ cắt nếu sau khi cắt start vẫn nhỏ hơn end
                    if next_sub["start"] > current_sub["start"]:
                        current_sub["end"] = next_sub["start"]
                    else:
                        # Trường hợp hy hữu: sub sau bắt đầu trước cả sub trước
                        # Có thể thu hẹp sub trước về một khoảng rất nhỏ hoặc giữ nguyên
                        current_sub["end"] = current_sub["start"] + 0.1 

            # Bước 3: Build nội dung file SRT
            lines = []
            seq = 1
            for item in processed_items:
                if item["end"] <= item["start"]:
                    continue

                lines.append(f"{seq}")
                lines.append(f"{format_srt_time(item['start'])} --> {format_srt_time(item['end'])}")
                lines.append(item["text"])
                lines.append("")
                seq += 1

            content = "\n".join(lines)
            out_path.write_text(content, encoding="utf-8")

            size_kb = out_path.stat().st_size / 1024
            logger.info(f"[Export] SRT Fixed: {out_path} ({seq-1} entries)")

            await broadcast(data.project_id, {
                "type": "export_done",
                "kind": "srt",
                "path": f"/dub/exports/{out_name}",
                "entries": seq - 1,
                "size_kb": round(size_kb, 1),
            })
        except Exception as e:
            logger.error(f"Export SRT error: {e}", exc_info=True)
            await broadcast(data.project_id, {"type": "export_error", "error": str(e)})

    background_tasks.add_task(do_export)
    return {"status": "processing"}

# ─── DOWNLOAD ────────────────────────────────────────────────────────────────

@router.get("/download/{filename}")
def download_file(filename: str):
    path = EXPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(str(path), filename=filename)