"""
DubEditor — Auto Assign Router v2
Pipeline: SRT-based chunking → ffmpeg cut → Pyannote → Speaker Embedding → Global Cluster → Apply DB
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import logging, asyncio, time, os, json, subprocess, sys, tempfile, shutil
import numpy as np

from dubeditor.database import get_db, SessionLocal
from dubeditor.models import Project, Subtitle, Character
from dubeditor.routers.ws import broadcast

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.parent.parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
VIDEO_DIR    = PROJECTS_DIR / "_videos"
WORK_DIR     = BASE_DIR / "data" / "auto_assign_work"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# ── Job state ──────────────────────────────────────────────────────────────
_running_tasks: dict[int, asyncio.Task] = {}

def _job_file(project_id: int) -> Path:
    return WORK_DIR / str(project_id) / "job.json"

def _load_job(project_id: int) -> dict | None:
    f = _job_file(project_id)
    if f.exists():
        try: return json.loads(f.read_text())
        except: return None
    return None

def _save_job(job: dict):
    f = _job_file(job["project_id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(job, ensure_ascii=False, indent=2))

def _log(job: dict, msg: str):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    logger.info(f"[AutoAssign p{job['project_id']}] {msg}")
    job.setdefault("logs", []).append(line)
    job["logs"] = job["logs"][-20:]  # giữ 20 dòng cuối
    _save_job(job)

def _get_hf_token() -> str:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("HF_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("HF_TOKEN", "")

# ── Request models ──────────────────────────────────────────────────────────
class AutoAssignRequest(BaseModel):
    project_id: int
    batch_size: int = 50          # số dòng SRT mỗi batch
    min_speakers: int = 2
    max_speakers: int = 15
    match_existing: bool = True   # match vào nhân vật cũ nếu có
    use_demucs: bool = False      # dùng Demucs tách vocals trước

class CancelRequest(BaseModel):
    project_id: int

# ── Endpoints ───────────────────────────────────────────────────────────────
@router.post("/projects/{project_id}/auto-assign/start")
async def start_auto_assign(
    project_id: int,
    data: AutoAssignRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    # Check job đang chạy
    existing = _load_job(project_id)
    if existing and existing.get("status") == "running":
        raise HTTPException(409, "Job đang chạy. Hủy trước khi chạy lại.")

    p = db.query(Project).filter(Project.id == project_id).first()
    if not p: raise HTTPException(404, "Project not found")
    if not p.video_path: raise HTTPException(400, "Project chưa có video")

    subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).order_by(Subtitle.index).all()
    if not subs: raise HTTPException(400, "Project chưa có phụ đề")

    hf_token = _get_hf_token()
    if not hf_token: raise HTTPException(400, "Chưa có HF_TOKEN trong .env")

    # Lấy nhân vật hiện có
    existing_chars = db.query(Character).filter(Character.project_id == project_id).all()
    existing_chars_data = [{"id": c.id, "name": c.name, "color": c.color} for c in existing_chars]

    video_name = p.video_path.split("/")[-1]
    video_path = str(VIDEO_DIR / video_name)

    srt_data = [{"id": s.id, "index": s.index, "start": s.start_time, "end": s.end_time, "text": s.text} for s in subs]
    total_batches = (len(srt_data) + data.batch_size - 1) // data.batch_size

    # Tạo job mới
    job = {
        "project_id": project_id,
        "status": "running",
        "total_batches": total_batches,
        "done_batches": 0,
        "total_lines": len(srt_data),
        "done_lines": 0,
        "batch_size": data.batch_size,
        "min_speakers": data.min_speakers,
        "max_speakers": data.max_speakers,
        "match_existing": data.match_existing,
        "use_demucs": data.use_demucs,
        "video_path": video_path,
        "global_speakers": {},   # embedding_key → {name, char_id, color, embedding}
        "logs": [],
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checkpoint_batch": 0,
    }
    # Xóa cache vocals cũ để đảm bảo dùng đúng cấu hình Demucs
    old_vocals = WORK_DIR / str(project_id) / "full_vocals.wav"
    old_raw    = WORK_DIR / str(project_id) / "raw_audio.wav"
    if old_vocals.exists(): old_vocals.unlink()
    if old_raw.exists(): old_raw.unlink()
    _save_job(job)

    background_tasks.add_task(
        run_pipeline,
        project_id=project_id,
        srt_data=srt_data,
        existing_chars=existing_chars_data,
        hf_token=hf_token,
    )
    return {"status": "started", "total_batches": total_batches, "total_lines": len(srt_data)}


@router.get("/projects/{project_id}/auto-assign/status")
def get_status(project_id: int):
    job = _load_job(project_id)
    if not job: raise HTTPException(404, "Không có job")
    # Trả về không có embedding (nặng)
    safe = {k: v for k, v in job.items() if k != "global_speakers"}
    safe["speaker_count"] = len(job.get("global_speakers", {}))
    return safe


@router.post("/projects/{project_id}/auto-assign/cancel")
def cancel_job(project_id: int):
    job = _load_job(project_id)
    if not job: raise HTTPException(404, "Không có job")
    job["status"] = "cancelled"
    _save_job(job)
    return {"ok": True}


@router.delete("/projects/{project_id}/auto-assign/reset")
def reset_job(project_id: int):
    """Xóa toàn bộ job + cache để chạy lại từ đầu."""
    job_dir = WORK_DIR / str(project_id)
    if job_dir.exists():
        shutil.rmtree(job_dir)
    return {"ok": True}


@router.get("/auto-assign/{project_id}/face/{filename}")
def get_face(project_id: int, filename: str):
    path = WORK_DIR / str(project_id) / "faces" / filename
    if not path.exists(): raise HTTPException(404, "Face not found")
    return FileResponse(str(path))


# ── Pipeline ─────────────────────────────────────────────────────────────────
async def run_pipeline(project_id: int, srt_data: list, existing_chars: list, hf_token: str):
    job = _load_job(project_id)
    job_dir = WORK_DIR / str(project_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "batch_audio").mkdir(exist_ok=True)

    async def prog(pct: int, msg: str):
        job["progress"] = pct
        _log(job, msg)
        await broadcast(project_id, {
            "type": "auto_assign_progress",
            "pct": pct,
            "step": msg,
            "done_batches": job["done_batches"],
            "total_batches": job["total_batches"],
            "done_lines": job["done_lines"],
            "total_lines": job["total_lines"],
            "logs": job["logs"],
        })

    try:
        await prog(2, "Giải phóng VRAM...")
        await _unload_voxcpm2()
        await asyncio.sleep(0.3)

        # Bước 1: Cắt audio toàn bộ
        await prog(5, f"Cắt audio toàn bộ {len(srt_data)} dòng SRT...")
        raw_audio  = job_dir / "raw_audio.wav"
        full_audio = job_dir / "full_vocals.wav"
        if not raw_audio.exists():
            await _cut_full_audio(job["video_path"], srt_data, raw_audio)
        size_mb = raw_audio.stat().st_size // 1024 // 1024
        _log(job, f"Audio thô: {size_mb}MB")

        # Bước 1b: Demucs tách vocals (nếu bật)
        if job.get("use_demucs", False):
            if not full_audio.exists():
                await prog(10, "Demucs tách vocals khỏi nhạc nền...")
                await _demucs_vocals(raw_audio, full_audio, job_dir)
                _log(job, f"Demucs xong: {full_audio.stat().st_size//1024//1024}MB vocals")
            else:
                _log(job, "Demucs cache hit")
        else:
            # Không dùng Demucs — dùng thẳng raw audio
            import shutil as _shutil
            if not full_audio.exists():
                _shutil.copy(raw_audio, full_audio)
            _log(job, "Bỏ qua Demucs — dùng raw audio")

        # Bước 2: Pyannote diarize toàn bộ
        await prog(25, f"Pyannote diarize {len(srt_data)} dòng...")
        diar_segments = await _diarize_batch(full_audio, job, hf_token, 0)
        n_spk = len(set(s["speaker"] for s in diar_segments))
        _log(job, f"Diarize xong → {n_spk} speakers, {len(diar_segments)} segments")

        # Kiểm tra cancelled
        job = _load_job(project_id)
        if job["status"] == "cancelled":
            await prog(50, "Đã hủy")
            return

        # Bước 3: Match SRT với diarization
        await prog(60, f"Match {len(srt_data)} dòng SRT với {n_spk} speakers...")
        audio_offset = max(0, srt_data[0]["start"] - 0.5)
        matched = _match_srt_to_diar(srt_data, diar_segments, audio_offset)

        # Bước 4: Tạo global speakers từ pyannote
        await prog(70, "Tạo nhân vật...")
        speakers = sorted(set(s["speaker"] for s in diar_segments))
        COLORS = ['#4f7ef8','#10c47a','#f6a623','#f04848','#a855f7',
                  '#f97316','#06b6d4','#ec4899','#84cc16','#14b8a6',
                  '#8b5cf6','#f59e0b','#3b82f6','#ef4444','#10b981',
                  '#6366f1','#ec4899','#14b8a6','#f97316','#84cc16']
        for i, spk in enumerate(speakers):
            job["global_speakers"][f"global_spk_{i}"] = {
                "name": spk, "char_id": None,
                "color": COLORS[i % len(COLORS)],
                "embedding": [], "created": True,
            }
        _save_job(job)
        speaker_map = {spk: job["global_speakers"][f"global_spk_{i}"]
                       for i, spk in enumerate(speakers)}

        # Bước 5: Apply vào DB
        await prog(80, f"Apply {len(matched)} dòng vào DB...")
        applied = await _apply_to_db(project_id, matched, speaker_map, job)
        _log(job, f"Applied {applied} / {len(srt_data)} dòng")

        # Broadcast
        await broadcast(project_id, {
            "type": "auto_assign_batch_done",
            "batch": 1, "total": 1,
            "applied": applied,
            "speaker_map": {k: {"name": v["name"], "char_id": v["char_id"], "color": v["color"]}
                            for k, v in speaker_map.items()},
        })

        # Xong
        job = _load_job(project_id)
        job["status"]      = "done"
        job["progress"]    = 100
        job["done_batches"] = 1
        job["done_lines"]   = applied
        _log(job, f"Hoàn thành! {applied} dòng · {len(speakers)} nhân vật")
        await broadcast(project_id, {
            "type": "auto_assign_done",
            "total_lines": applied,
            "speaker_count": len(speakers),
            "logs": job["logs"],
        })

    except Exception as e:
        logger.error(f"[AutoAssign] ERROR: {e}", exc_info=True)
        job = _load_job(project_id)
        job["status"] = "error"
        job["error"]  = str(e)
        _log(job, f"LỖI: {e}")
        await broadcast(project_id, {"type": "auto_assign_error", "error": str(e)})
    finally:
        logger.info("[AutoAssign] Pipeline xong — model KHÔNG tự reload, user tự load khi cần")


# ── Step functions ────────────────────────────────────────────────────────────

async def _demucs_vocals(audio_path: Path, out_path: Path, work_dir: Path):
    """Tách vocals bằng Demucs — loại nhạc nền để Pyannote chính xác hơn."""
    import shutil
    loop = asyncio.get_event_loop()
    def _run():
        demucs_out = work_dir / "demucs_out"
        subprocess.run([
            sys.executable, "-m", "demucs",
            "--two-stems=vocals", "-n", "htdemucs_ft",
            "--segment", "7", "--overlap", "0.1",
            "-o", str(demucs_out), str(audio_path)
        ], check=True)
        found = list(demucs_out.rglob("vocals.wav"))
        if found:
            shutil.copy(found[0], out_path)
        else:
            shutil.copy(audio_path, out_path)  # fallback
        shutil.rmtree(demucs_out, ignore_errors=True)
    await loop.run_in_executor(None, _run)

async def _cut_full_audio(video_path: str, srt_data: list, out_path: Path):
    """Cắt audio liên tục từ start SRT đầu đến end SRT cuối."""
    loop = asyncio.get_event_loop()
    def _run():
        start = max(0, srt_data[0]["start"] - 0.5)
        end   = srt_data[-1]["end"] + 0.5
        dur   = end - start
        subprocess.run([
            "ffmpeg", "-ss", str(start), "-i", video_path,
            "-t", str(dur), "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1", str(out_path),
            "-y", "-loglevel", "quiet"
        ], check=True)
    await loop.run_in_executor(None, _run)

async def _cut_and_merge_audio(video_path: str, batch: list, out_path: Path):
    """Cắt 1 đoạn liên tục từ start batch đến end batch — embedding chất lượng hơn."""
    loop = asyncio.get_event_loop()

    def _run():
        # Lấy đoạn liên tục từ đầu đến cuối batch
        start = max(0, batch[0]["start"] - 0.5)
        end   = batch[-1]["end"] + 0.5
        dur   = end - start
        subprocess.run([
            "ffmpeg", "-ss", str(start), "-i", video_path,
            "-t", str(dur), "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1", str(out_path),
            "-y", "-loglevel", "quiet"
        ], check=True)

    await loop.run_in_executor(None, _run)


async def _diarize_batch(audio_path: Path, job: dict, hf_token: str, batch_idx: int) -> list:
    """Pyannote diarize 1 batch audio."""
    loop = asyncio.get_event_loop()
    def _run():
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            output_json = tmp.name
        worker_script = BASE_DIR / "diarize_worker.py"
        proc = subprocess.run([
            sys.executable, str(worker_script),
            str(audio_path), hf_token,
            str(job["min_speakers"]), str(job["max_speakers"]),
            output_json
        ], capture_output=True, text=True, timeout=600)
        if proc.returncode != 0:
            raise RuntimeError(f"Diarize batch {batch_idx} failed: {proc.stderr[-300:]}")
        with open(output_json) as f: segments = json.load(f)
        os.unlink(output_json)
        return segments
    return await loop.run_in_executor(None, _run)


def _match_srt_to_diar(batch: list, diar_segments: list, batch_offset: float) -> list:
    """Match từng dòng SRT với speaker trong diarization (có offset)."""
    result = []
    for line in batch:
        # Thời gian tương đối trong batch audio
        rel_start = line["start"] - batch_offset
        rel_end   = line["end"]   - batch_offset
        best_speaker = None; best_overlap = 0.0
        for seg in diar_segments:
            overlap = max(0.0, min(rel_end, seg["end"]) - max(rel_start, seg["start"]))
            if overlap > best_overlap:
                best_overlap = overlap; best_speaker = seg["speaker"]
        result.append({**line, "local_speaker": best_speaker, "overlap": best_overlap})
    return result


async def _extract_embeddings(audio_path: Path, diar_segments: list, job: dict) -> dict:
    """Extract embedding vector cho mỗi local speaker."""
    loop = asyncio.get_event_loop()
    def _run():
        try:
            from pyannote.audio import Model, Inference
            import torch
            hf_token = _get_hf_token()
            model = Model.from_pretrained(
                "pyannote/wespeaker-voxceleb-resnet34-LM",
                use_auth_token=hf_token
            )
            inference = Inference(model, window="whole")
            # Group segments by speaker
            by_speaker: dict[str, list] = {}
            for seg in diar_segments:
                by_speaker.setdefault(seg["speaker"], []).append(seg)

            embeddings = {}
            import soundfile as sf
            wav, sr = sf.read(str(audio_path))
            for speaker, segs in by_speaker.items():
                vecs = []
                for seg in segs[:5]:  # tối đa 5 đoạn mỗi speaker
                    s = int(seg["start"] * sr)
                    e = int(seg["end"]   * sr)
                    chunk = wav[s:e]
                    if len(chunk) < sr * 0.5: continue  # skip < 0.5s
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                        sf.write(tf.name, chunk, sr)
                        try:
                            emb = inference(tf.name)
                            vecs.append(emb)
                        except: pass
                        finally: os.unlink(tf.name)
                if vecs:
                    embeddings[speaker] = np.mean(vecs, axis=0).tolist()
            return embeddings
        except Exception as e:
            logger.warning(f"Embedding extraction failed: {e}, dùng fallback")
            return {}
    return await loop.run_in_executor(None, _run)


def _cosine_sim(a: list, b: list) -> float:
    a, b = np.array(a), np.array(b)
    n = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / n) if n > 0 else 0.0


def _match_to_global(local_embeddings: dict, job: dict) -> dict:
    """
    Map local speaker → global speaker.
    Trả về: {local_speaker_id: {name, char_id, color, embedding}}
    """
    THRESHOLD = 0.75
    global_spk = job.get("global_speakers", {})
    COLORS = ['#4f7ef8','#10c47a','#f6a623','#f04848','#a855f7',
              '#f97316','#06b6d4','#ec4899','#84cc16','#14b8a6',
              '#8b5cf6','#f59e0b','#3b82f6','#ef4444','#10b981',
              '#6366f1','#ec4899','#14b8a6','#f97316','#84cc16']
    speaker_map = {}

    for local_spk, local_emb in local_embeddings.items():
        best_key  = None
        best_sim  = THRESHOLD
        # So sánh với tất cả global speakers
        for gkey, gdata in global_spk.items():
            if gdata.get("embedding"):
                sim = _cosine_sim(local_emb, gdata["embedding"])
                if sim > best_sim:
                    best_sim = sim; best_key = gkey

        if best_key:
            # Match với speaker cũ
            speaker_map[local_spk] = global_spk[best_key]
            # Update embedding (running average)
            old_emb = np.array(global_spk[best_key]["embedding"])
            new_emb = np.array(local_emb)
            global_spk[best_key]["embedding"] = ((old_emb * 0.7 + new_emb * 0.3)).tolist()
        else:
            # Speaker mới
            idx   = len(global_spk)
            gkey  = f"global_spk_{idx}"
            color = COLORS[idx % len(COLORS)]
            name  = f"SPEAKER_{idx:02d}"
            new_entry = {
                "name": name, "char_id": None,
                "color": color, "embedding": local_emb,
                "created": True,
            }
            global_spk[gkey] = new_entry
            speaker_map[local_spk] = new_entry

    job["global_speakers"] = global_spk
    _save_job(job)
    return speaker_map


async def _load_existing_char_embeddings(job: dict, existing_chars: list, job_dir: Path, hf_token: str):
    """Load embedding từ audio mẫu của nhân vật cũ để match."""
    # TODO: nếu char có audio mẫu thì extract embedding
    # Hiện tại bỏ qua — sẽ tạo speaker mới và user tự merge sau
    pass


async def _apply_to_db(project_id: int, matched: list, speaker_map: dict, job: dict) -> int:
    """Tạo Character mới nếu cần + gán character_id vào subtitles."""
    db = SessionLocal()
    try:
        applied = 0
        for line in matched:
            local_spk = line.get("local_speaker")
            if not local_spk or line.get("overlap", 0) < 0.1:
                continue
            gdata = speaker_map.get(local_spk)
            if not gdata: continue

            # Tạo Character nếu chưa có
            if not gdata.get("char_id"):
                char = Character(
                    project_id=project_id,
                    name=gdata["name"],
                    color=gdata["color"],
                    description="Auto-assigned by AI",
                )
                db.add(char); db.flush()
                gdata["char_id"] = char.id
                # Update trong global_speakers
                job = _load_job(project_id)
                for gkey, gs in job["global_speakers"].items():
                    if gs["name"] == gdata["name"] and not gs.get("char_id"):
                        gs["char_id"] = char.id
                _save_job(job)
                _log(job, f"Tạo nhân vật mới: {gdata['name']} (id={char.id})")

            # Gán vào subtitle
            db.query(Subtitle).filter(
                Subtitle.id == line["id"],
                Subtitle.project_id == project_id
            ).update({"character_id": gdata["char_id"]}, synchronize_session=False)
            applied += 1

        db.commit()
        return applied
    finally:
        db.close()


async def _unload_voxcpm2():
    import gc
    try:
        import torch
        main = sys.modules.get("__main__") or sys.modules.get("app")
        if main and hasattr(main, "_nano_server") and main._nano_server is not None:
            try: main._nano_server.stop()
            except: pass
            del main._nano_server; main._nano_server = None
            gc.collect()
            if torch.cuda.is_available(): torch.cuda.empty_cache()
            logger.info("[AutoAssign] VoxCPM2 unloaded")
    except Exception as e:
        logger.warning(f"Unload warning: {e}")


async def _reload_voxcpm2():
    try:
        main = sys.modules.get("__main__") or sys.modules.get("app")
        loop = asyncio.get_event_loop()
        if main and hasattr(main, "_load_model"):
            await loop.run_in_executor(None, main._load_model)
        elif main and hasattr(main, "_start_nano"):
            await loop.run_in_executor(None, main._start_nano)
        logger.info("[AutoAssign] VoxCPM2 reloaded")
    except Exception as e:
        logger.error(f"Reload error: {e}")