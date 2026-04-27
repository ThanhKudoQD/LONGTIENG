"""
DubEditor — Auto Assign Router
Pipeline: Demucs → Pyannote (subprocess) → Match SRT → InsightFace → Fusion
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel
from pathlib import Path
from typing import Optional
import logging, asyncio, time, os, json, subprocess, sys, tempfile

from dubeditor.database import get_db
from dubeditor.models import Project, Subtitle, Character
from dubeditor.routers.ws import broadcast

router = APIRouter()
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).parent.parent.parent
PROJECTS_DIR = BASE_DIR / "data" / "projects"
VIDEO_DIR    = PROJECTS_DIR / "_videos"
WORK_DIR     = BASE_DIR / "data" / "auto_assign_work"
WORK_DIR.mkdir(parents=True, exist_ok=True)

_auto_assign_running = False
_auto_assign_jobs: dict[int, dict] = {}

def is_running() -> bool:
    return _auto_assign_running

def _get_hf_token() -> str:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line.startswith("HF_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("HF_TOKEN", "")

class AutoAssignRequest(BaseModel):
    project_id: int
    min_speakers: int = 2
    max_speakers: int = 15
    lip_threshold: float = 0.0

class ConfirmGroupRequest(BaseModel):
    project_id: int
    cluster_id: str
    character_id: int

@router.post("/projects/{project_id}/auto-assign/start")
async def start_auto_assign(project_id: int, data: AutoAssignRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    global _auto_assign_running
    if _auto_assign_running:
        raise HTTPException(409, "Đang có pipeline khác đang chạy.")
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p: raise HTTPException(404, "Project not found")
    if not p.video_path: raise HTTPException(400, "Project chưa có video")
    subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).order_by(Subtitle.index).all()
    if not subs: raise HTTPException(400, "Project chưa có phụ đề")
    hf_token = _get_hf_token()
    if not hf_token: raise HTTPException(400, "Chưa có HF_TOKEN trong .env")

    _auto_assign_jobs[project_id] = {"status":"queued","progress":0,"step":"Đang chuẩn bị...","error":None,"result":None,"started_at":time.time()}
    srt_data = [{"id":s.id,"index":s.index,"start":s.start_time,"end":s.end_time,"text":s.text} for s in subs]
    video_name = p.video_path.split("/")[-1]
    video_path = VIDEO_DIR / video_name
    background_tasks.add_task(run_pipeline, project_id=project_id, video_path=video_path, srt_data=srt_data, settings=data, hf_token=hf_token)
    return {"status":"started","subtitle_count":len(subs)}

@router.get("/projects/{project_id}/auto-assign/status")
def get_status(project_id: int):
    job = _auto_assign_jobs.get(project_id)
    if not job: raise HTTPException(404, "Không có job")
    return job

@router.post("/projects/{project_id}/auto-assign/confirm-group")
def confirm_group(project_id: int, data: ConfirmGroupRequest, db: Session = Depends(get_db)):
    job = _auto_assign_jobs.get(project_id)
    if not job or not job.get("result"): raise HTTPException(400, "Chưa có kết quả")
    result  = job["result"]
    cluster = next((c for c in result["clusters"] if c["cluster_id"] == data.cluster_id), None)
    if not cluster: raise HTTPException(404, f"Cluster không tồn tại")
    char = db.query(Character).filter(Character.id == data.character_id).first()
    if not char: raise HTTPException(404, "Character not found")
    updated = db.query(Subtitle).filter(Subtitle.id.in_(cluster["subtitle_ids"]), Subtitle.project_id == project_id).update({"character_id":data.character_id}, synchronize_session=False)
    db.commit()
    result.setdefault("char_map",{})[data.cluster_id] = data.character_id
    return {"updated":updated,"character":char.name}

@router.post("/projects/{project_id}/auto-assign/apply-all")
def apply_all_high(project_id: int, db: Session = Depends(get_db)):
    job = _auto_assign_jobs.get(project_id)
    if not job or not job.get("result"): raise HTTPException(400, "Chưa có kết quả")
    char_map = job["result"].get("char_map",{})
    if not char_map: raise HTTPException(400, "Chưa map cluster → character")
    total = 0
    for a in job["result"].get("assignments",[]):
        if a["conf_level"] != "high": continue
        char_id = char_map.get(a["cluster_id"])
        if not char_id: continue
        db.query(Subtitle).filter(Subtitle.id == a["subtitle_id"]).update({"character_id":char_id}, synchronize_session=False)
        total += 1
    db.commit()
    return {"applied":total}

@router.post("/projects/{project_id}/auto-assign/cancel")
def cancel_job(project_id: int):
    job = _auto_assign_jobs.get(project_id)
    if job: job["status"] = "cancelled"
    return {"ok":True}

async def run_pipeline(project_id: int, video_path: Path, srt_data: list, settings: AutoAssignRequest, hf_token: str):
    global _auto_assign_running
    _auto_assign_running = True
    job = _auto_assign_jobs[project_id]
    def set_prog(pct, step):
        job.update({"progress":pct,"step":step,"status":"running"})
        asyncio.create_task(broadcast(project_id,{"type":"auto_assign_progress","pct":pct,"step":step}))
    try:
        job_dir = WORK_DIR / str(project_id)
        job_dir.mkdir(exist_ok=True)
        (job_dir/"faces").mkdir(exist_ok=True)
        set_prog(2,"Giải phóng VRAM..."); await _unload_voxcpm2(); await asyncio.sleep(0.5)
        set_prog(5,"Demucs: Tách giọng...")
        vocals_path = await step_demucs(video_path, job_dir)
        set_prog(22,"Demucs xong!")
        set_prog(24,"Pyannote: Phân tách giọng nói...")
        diar_segments = await step_diarize(vocals_path, settings, hf_token)
        n_spk = len(set(s["speaker"] for s in diar_segments))
        set_prog(55,f"Diarization xong → {n_spk} speaker")
        set_prog(57,"Matching SRT timestamps...")
        srt_data = step_match_srt(srt_data, diar_segments)
        speakers = sorted(set(l.get("cluster_id","?") for l in srt_data if l.get("cluster_id")))
        set_prog(62,f"Match xong → {', '.join(speakers)}")
        set_prog(64,"InsightFace: Verify lip sync...")
        srt_data = await step_lip_scan(video_path, srt_data, settings, job_dir)
        set_prog(80,"Lip sync xong")
        set_prog(82,"Tính confidence...")
        result = step_fusion(srt_data, speakers)
        result["clusters"]      = _build_cluster_info(srt_data, speakers, job_dir, project_id)
        result["subtitle_count"] = len(srt_data)
        if not result["clusters"]:
            raise ValueError(f"Không tìm được nhóm nào. {n_spk} speaker nhưng không match được với SRT.")
        job["result"]=result; job["status"]="done"; job["progress"]=100
        job["step"]=f"Hoàn thành! {len(result['clusters'])} nhân vật · {len(srt_data)} dòng"
        await broadcast(project_id,{"type":"auto_assign_done","clusters":result["clusters"],"conf_stats":result["conf_stats"]})
    except Exception as e:
        logger.error(f"[AutoAssign] ERROR: {e}", exc_info=True)
        job["status"]="error"; job["error"]=str(e)
        await broadcast(project_id,{"type":"auto_assign_error","error":str(e)})
    finally:
        _auto_assign_running = False
        try: set_prog(98,"Reload VoxCPM2..."); await _reload_voxcpm2()
        except Exception as e: logger.error(f"Reload error: {e}")

async def _unload_voxcpm2():
    import sys, gc
    try:
        import torch
        main = sys.modules.get("__main__") or sys.modules.get("app")
        if main and hasattr(main,"_nano_server") and main._nano_server is not None:
            try: main._nano_server.stop()
            except: pass
            del main._nano_server; main._nano_server = None
            gc.collect()
            if torch.cuda.is_available(): torch.cuda.empty_cache()
            logger.info("[AutoAssign] VoxCPM2 unloaded")
        else: logger.info("[AutoAssign] VoxCPM2 không có trong bộ nhớ")
    except Exception as e: logger.warning(f"Unload warning: {e}")

async def _reload_voxcpm2():
    import sys
    try:
        main = sys.modules.get("__main__") or sys.modules.get("app")
        loop = asyncio.get_event_loop()
        if main and hasattr(main,"_load_model"):
            await loop.run_in_executor(None, main._load_model)
        elif main and hasattr(main,"_start_nano"):
            await loop.run_in_executor(None, main._start_nano)
        logger.info("[AutoAssign] VoxCPM2 reloaded")
    except Exception as e: logger.error(f"Reload error: {e}")

async def step_demucs(video_path: Path, out_dir: Path) -> Path:
    import shutil
    vocals_wav = out_dir/"vocals.wav"
    if vocals_wav.exists(): logger.info("[Demucs] Cache hit"); return vocals_wav
    audio_tmp = out_dir/"audio_tmp.wav"
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: subprocess.run(["ffmpeg","-i",str(video_path),"-vn","-acodec","pcm_s16le","-ar","44100","-ac","2",str(audio_tmp),"-y","-loglevel","quiet"], check=True))
    await loop.run_in_executor(None, lambda: subprocess.run([sys.executable,"-m","demucs","--two-stems=vocals","-n","htdemucs_ft","-o",str(out_dir/"demucs_out"),str(audio_tmp)], check=True))
    found = list((out_dir/"demucs_out").rglob("vocals.wav"))
    shutil.copy(found[0] if found else audio_tmp, vocals_wav)
    if audio_tmp.exists(): audio_tmp.unlink()
    shutil.rmtree(out_dir/"demucs_out", ignore_errors=True)
    return vocals_wav

async def step_diarize(vocals_path: Path, settings: AutoAssignRequest, hf_token: str) -> list:
    # Cache: lưu theo vocals_path + min/max speakers
    cache_key = f"{vocals_path.stem}_{settings.min_speakers}_{settings.max_speakers}"
    cache_file = vocals_path.parent / f"diarize_cache_{cache_key}.json"

    if cache_file.exists():
        with open(cache_file) as f:
            segments = json.load(f)
        logger.info(f"[Diarize] Cache hit → {len(segments)} segments")
        return segments

    loop = asyncio.get_event_loop()
    def _run():
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp: output_json = tmp.name
        worker_script = BASE_DIR/"diarize_worker.py"
        if not worker_script.exists(): raise FileNotFoundError(f"diarize_worker.py không tìm thấy tại {worker_script}")
        proc = subprocess.run([sys.executable,str(worker_script),str(vocals_path),hf_token,str(settings.min_speakers),str(settings.max_speakers),output_json], capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0: raise RuntimeError(f"Diarize failed: {proc.stderr[-500:]}")
        logger.info(f"[Diarize] {proc.stdout.strip()}")
        with open(output_json) as f: segments = json.load(f)
        os.unlink(output_json)
        # Lưu cache
        with open(cache_file, 'w') as f: json.dump(segments, f)
        logger.info(f"[Diarize] Saved cache → {cache_file}")
        return segments
    return await loop.run_in_executor(None, _run)

def step_match_srt(srt_data: list, diar_segments: list) -> list:
    for line in srt_data:
        best_speaker=None; best_overlap=0.0
        for seg in diar_segments:
            overlap = max(0.0, min(line["end"],seg["end"])-max(line["start"],seg["start"]))
            if overlap>best_overlap: best_overlap=overlap; best_speaker=seg["speaker"]
        line["cluster_id"]=best_speaker; line["overlap_sec"]=round(best_overlap,3)
        line["has_speaker"]=best_speaker is not None and best_overlap>0.1
    return srt_data

async def step_lip_scan(video_path: Path, srt_data: list, settings: AutoAssignRequest, job_dir: Path) -> list:
    import gc
    loop = asyncio.get_event_loop()
    def _run():
        import cv2, numpy as np
        from insightface.app import FaceAnalysis
        app_face = FaceAnalysis(providers=["CUDAExecutionProvider","CPUExecutionProvider"])
        app_face.prepare(ctx_id=0,det_size=(640,640))
        cap=cv2.VideoCapture(str(video_path)); fps=cap.get(cv2.CAP_PROP_FPS) or 25
        total_frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        samples=sorted([((l["start"]+l["end"])/2,i) for i,l in enumerate(srt_data)],key=lambda x:x[0])
        all_gaps=[]; frame_cache={}; fi=0
        for target_t,idx in samples:
            target_f=min(int(target_t*fps),total_frames-1)
            while fi<target_f: cap.grab(); fi+=1
            ret,frame=cap.read()
            if not ret: continue
            frame_cache[idx]=frame.copy(); fi+=1
            for face in app_face.get(frame):
                if face.det_score>=0.5: all_gaps.append(_calc_lip_gap(face))
        cap.release()
        lip_thr=float(np.percentile(all_gaps,70)) if all_gaps and settings.lip_threshold==0 else (settings.lip_threshold or 6.0)
        logger.info(f"[Lip] Threshold: {lip_thr:.2f}")
        face_idx=0
        for _,srt_idx in samples:
            line=srt_data[srt_idx]; frame=frame_cache.get(srt_idx)
            if frame is None: line["has_lip"]=False; line["lip_count"]=0; line["best_thumb"]=None; continue
            h,w=frame.shape[:2]
            speaking=[f for f in app_face.get(frame) if f.det_score>=0.5 and _calc_lip_gap(f)>lip_thr]
            line["has_lip"]=len(speaking)>0; line["lip_count"]=len(speaking); line["best_thumb"]=None
            if speaking:
                face=speaking[0]; bbox=face.bbox.astype(int); fw=bbox[2]-bbox[0]; fh=bbox[3]-bbox[1]
                crop=frame[max(0,bbox[1]-int(fh*.5)):min(h,bbox[3]+int(fh*.4)),max(0,bbox[0]-int(fw*.3)):min(w,bbox[2]+int(fw*.3))]
                if crop.size>0:
                    fname=f"face_{face_idx:05d}.jpg"; cv2.imwrite(str(job_dir/"faces"/fname),crop,[cv2.IMWRITE_JPEG_QUALITY,85])
                    line["best_thumb"]=fname; face_idx+=1
        del app_face; gc.collect()
        return srt_data
    return await loop.run_in_executor(None, _run)

def _calc_lip_gap(face) -> float:
    try:
        if hasattr(face,"landmark_2d_106") and face.landmark_2d_106 is not None:
            lm=face.landmark_2d_106; return float(abs(lm[57][1]-lm[52][1]))
    except: pass
    return 0.0

def step_fusion(srt_data: list, speakers: list) -> dict:
    conf_stats={"high":0,"medium":0,"low":0}
    for line in srt_data:
        cid=line.get("cluster_id"); overlap=line.get("overlap_sec",0)
        has_lip=line.get("has_lip",False); lip_cnt=line.get("lip_count",0)
        sub_dur=line["end"]-line["start"]
        if not cid or not line.get("has_speaker"): line["conf_pct"]=0; line["conf_level"]="low"
        elif overlap>=sub_dur*0.6:
            if has_lip and lip_cnt==1: line["conf_pct"]=100; line["conf_level"]="high"
            elif has_lip: line["conf_pct"]=80; line["conf_level"]="medium"
            else: line["conf_pct"]=75; line["conf_level"]="medium"
        elif overlap>=sub_dur*0.3: line["conf_pct"]=60; line["conf_level"]="medium"
        else: line["conf_pct"]=40; line["conf_level"]="low"
        conf_stats[line["conf_level"]]+=1
    assignments=[{"subtitle_id":l["id"],"cluster_id":l.get("cluster_id"),"conf_pct":l.get("conf_pct",0),"conf_level":l.get("conf_level","low")} for l in srt_data]
    return {"assignments":assignments,"conf_stats":conf_stats,"char_map":{}}

def _build_cluster_info(srt_data, speakers, job_dir, project_id) -> list:
    result=[]
    for speaker in speakers:
        lines=[l for l in srt_data if l.get("cluster_id")==speaker]
        if not lines: continue
        high=sum(1 for l in lines if l.get("conf_level")=="high")
        medium=sum(1 for l in lines if l.get("conf_level")=="medium")
        low=sum(1 for l in lines if l.get("conf_level")=="low")
        samples=sorted(lines,key=lambda l:-(l.get("conf_pct") or 0))[:5]
        thumb=next((f"/dub/auto-assign/{project_id}/face/{l['best_thumb']}" for l in lines if l.get("best_thumb")),None)
        result.append({"cluster_id":speaker,"line_count":len(lines),"subtitle_ids":[l["id"] for l in lines],"high_count":high,"medium_count":medium,"low_count":low,"sample_texts":[l["text"][:60] for l in samples],"sample_starts":[l["start"] for l in samples],"thumbnail":thumb})
    result.sort(key=lambda x:-x["line_count"])
    return result


@router.post("/projects/{project_id}/auto-assign/auto-apply")
def auto_apply(project_id: int, db: Session = Depends(get_db)):
    """Tự động tạo nhân vật cho từng speaker và apply vào phụ đề."""
    job = _auto_assign_jobs.get(project_id)
    if not job or not job.get("result"):
        raise HTTPException(400, "Chưa có kết quả")

    clusters = job["result"].get("clusters", [])
    if not clusters:
        raise HTTPException(400, "Không có cluster nào")

    COLORS = ['#4f7ef8','#10c47a','#f6a623','#f04848','#a855f7',
              '#f97316','#06b6d4','#ec4899','#84cc16','#14b8a6']

    total = 0
    created_chars = []
    for i, cluster in enumerate(clusters):
        # Tạo nhân vật mới
        char = Character(
            project_id=project_id,
            name=cluster["cluster_id"],  # SPEAKER_00, SPEAKER_01...
            color=COLORS[i % len(COLORS)],
            description="Auto-assigned by AI",
        )
        db.add(char); db.flush()

        # Gán vào subtitles
        updated = db.query(Subtitle).filter(
            Subtitle.id.in_(cluster["subtitle_ids"]),
            Subtitle.project_id == project_id
        ).update({"character_id": char.id}, synchronize_session=False)

        created_chars.append({"id": char.id, "name": char.name, "color": char.color})
        total += updated

    db.commit()
    logger.info(f"[AutoAssign] Auto-apply: {len(clusters)} speakers, {total} subtitles")
    return {"created": len(clusters), "assigned": total, "characters": created_chars}

@router.delete("/projects/{project_id}/auto-assign/cache")
def clear_cache(project_id: int):
    """Xóa cache diarization của project."""
    job_dir = WORK_DIR / str(project_id)
    deleted = 0
    for f in job_dir.glob("diarize_cache_*.json"):
        f.unlink(); deleted += 1
    # Xóa cả vocals.wav cache
    vocals = job_dir / "vocals.wav"
    if vocals.exists(): vocals.unlink(); deleted += 1
    return {"deleted": deleted}

@router.get("/auto-assign/{project_id}/face/{filename}")
def get_face(project_id: int, filename: str):
    path = WORK_DIR/str(project_id)/"faces"/filename
    if not path.exists(): raise HTTPException(404,"Face not found")
    return FileResponse(str(path))