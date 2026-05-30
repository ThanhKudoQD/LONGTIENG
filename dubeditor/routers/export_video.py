"""
Export Video API endpoints.

Routes (under /api/export_video):
  POST   /run/{project_id}                  → tạo job + queue
  GET    /jobs/{project_id}                 → list jobs của project
  GET    /jobs/{project_id}/job/{job_id}    → detail 1 job
  POST   /jobs/{job_id}/cancel              → cancel
  DELETE /jobs/{job_id}                     → xóa khỏi list (chỉ với job đã done/error/cancelled)

  POST   /upload-asset/{project_id}         → upload audio/image (cho BGM/watermark)

  GET    /presets                           → list global presets
  POST   /presets                           → tạo preset
  DELETE /presets/{id}                      → xóa preset
"""
import json
import os
import shutil
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import ExportJob, ExportPreset, Project
from dubeditor.export.config_types import (
    ExportConfig, RunExportIn, CreatePresetIn,
    ExportJobOut, ExportPresetOut,
)
from dubeditor.export.service import (
    submit_job, cancel_job, UPLOADS_DIR, EXPORTS_DIR,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _job_to_dict(j: ExportJob) -> dict:
    try:
        cfg = json.loads(j.config_json) if j.config_json else {}
    except Exception:
        cfg = {}
    return {
        'id': j.id,
        'project_id': j.project_id,
        'status': j.status,
        'progress': j.progress or 0,
        'config': cfg,
        'output_url': j.output_url,
        'output_size': j.output_size or 0,
        'error_msg': j.error_msg,
        'eta_sec': j.eta_sec or 0,
        'created_at':  (j.created_at.isoformat()  + 'Z') if j.created_at  else None,
        'started_at':  (j.started_at.isoformat()  + 'Z') if j.started_at  else None,
        'finished_at': (j.finished_at.isoformat() + 'Z') if j.finished_at else None,
    }


def _preset_to_dict(p: ExportPreset) -> dict:
    try:
        cfg = json.loads(p.config_json) if p.config_json else {}
    except Exception:
        cfg = {}
    return {
        'id': p.id,
        'name': p.name,
        'config': cfg,
        'created_at': p.created_at.isoformat() if p.created_at else None,
    }


# ─── Run / list / cancel ──────────────────────────────────────────────────────

@router.post("/run/{project_id}")
def run_export(project_id: int, body: RunExportIn, db: Session = Depends(get_db)):
    """Submit export job."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project không tồn tại")
    if not project.video_path:
        raise HTTPException(400, "Project chưa có video file")

    job_id = submit_job(project_id, body.config)
    job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
    if not job:
        raise HTTPException(500, "Không tạo được job")
    return _job_to_dict(job)


@router.get("/jobs/{project_id}")
def list_jobs(project_id: int, db: Session = Depends(get_db)):
    """List tất cả job của project, mới nhất trước."""
    jobs = (db.query(ExportJob)
              .filter(ExportJob.project_id == project_id)
              .order_by(ExportJob.id.desc()).all())
    return [_job_to_dict(j) for j in jobs]


@router.get("/jobs/{project_id}/job/{job_id}")
def get_job(project_id: int, job_id: int, db: Session = Depends(get_db)):
    """Get 1 job detail."""
    job = db.query(ExportJob).filter(ExportJob.id == job_id,
                                       ExportJob.project_id == project_id).first()
    if not job:
        raise HTTPException(404, "Job không tồn tại")
    return _job_to_dict(job)


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db)):
    """Cancel job đang chạy hoặc đang pending."""
    ok = cancel_job(job_id)
    if not ok:
        raise HTTPException(400, "Không thể cancel (job đã xong hoặc không tồn tại)")
    job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
    return _job_to_dict(job) if job else {'ok': True}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db)):
    """Xóa job khỏi DB. Job đang running không được xóa — phải cancel trước."""
    job = db.query(ExportJob).filter(ExportJob.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job không tồn tại")
    if job.status == 'running':
        raise HTTPException(400, "Job đang chạy — hãy cancel trước khi xóa")
    # Xóa file output nếu còn
    if job.output_path and os.path.exists(job.output_path):
        try:
            os.unlink(job.output_path)
        except Exception:
            pass
    db.delete(job)
    db.commit()
    return {'ok': True}


# ─── Upload asset (BGM audio / watermark image) ───────────────────────────────

ALLOWED_EXT = {'.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac',  # audio
               '.png', '.jpg', '.jpeg', '.webp', '.gif'}          # image


@router.post("/upload-asset/{project_id}")
async def upload_asset(project_id: int, file: UploadFile = File(...),
                       kind: str = Form('audio'), db: Session = Depends(get_db)):
    """
    Upload audio (BGM) hoặc image (watermark) cho export.
    kind: 'audio' | 'image'
    Returns: { url, name, size, duration?, width?, height? }
    """
    if not file.filename:
        raise HTTPException(400, "Tên file không hợp lệ")
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Định dạng không hỗ trợ: {ext}")
    if kind not in ('audio', 'image'):
        raise HTTPException(400, "kind phải là 'audio' hoặc 'image'")

    # Save với unique name để tránh trùng
    safe_name = f"{uuid.uuid4().hex[:12]}_{Path(file.filename).name}"
    save_path = UPLOADS_DIR / safe_name
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    with open(save_path, 'wb') as out:
        shutil.copyfileobj(file.file, out)
    size = save_path.stat().st_size

    result = {
        'url': f"/dub/export_uploads/{safe_name}",
        'name': file.filename,
        'size': size,
    }

    # Get metadata
    if kind == 'audio':
        try:
            import subprocess
            out = subprocess.check_output([
                'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(save_path),
            ], timeout=10).decode().strip()
            result['duration'] = float(out)
        except Exception:
            result['duration'] = 0
    elif kind == 'image':
        try:
            from PIL import Image
            with Image.open(save_path) as im:
                result['width'] = im.width
                result['height'] = im.height
        except Exception:
            pass

    return result


# ─── Presets ──────────────────────────────────────────────────────────────────

@router.get("/presets")
def list_presets(db: Session = Depends(get_db)):
    presets = db.query(ExportPreset).order_by(ExportPreset.id.desc()).all()
    return [_preset_to_dict(p) for p in presets]


@router.post("/presets")
def create_preset(body: CreatePresetIn, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Tên preset không được rỗng")

    existing = db.query(ExportPreset).filter(ExportPreset.name == name).first()
    if existing:
        # Update existing
        existing.config_json = json.dumps(body.config)
        db.commit()
        db.refresh(existing)
        return _preset_to_dict(existing)

    p = ExportPreset(name=name, config_json=json.dumps(body.config))
    db.add(p)
    db.commit()
    db.refresh(p)
    return _preset_to_dict(p)


@router.delete("/presets/{preset_id}")
def delete_preset(preset_id: int, db: Session = Depends(get_db)):
    p = db.query(ExportPreset).filter(ExportPreset.id == preset_id).first()
    if not p:
        raise HTTPException(404, "Preset không tồn tại")
    db.delete(p)
    db.commit()
    return {'ok': True}


# ─── Per-project config auto-save (v4.0) ──────────────────────────────────────

@router.get("/config/{project_id}")
def get_project_config(project_id: int, db: Session = Depends(get_db)):
    """
    Load saved export config của project (nếu có).
    Returns: {config: <ExportConfig dict>} hoặc {config: null} nếu chưa lưu.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project không tồn tại")
    raw = getattr(project, 'last_export_config_json', None)
    if not raw:
        return {'config': None}
    try:
        return {'config': json.loads(raw)}
    except Exception:
        return {'config': None}


@router.put("/config/{project_id}")
def save_project_config(project_id: int, body: dict, db: Session = Depends(get_db)):
    """
    Auto-save export config của project. Body = {config: <ExportConfig dict>}.
    Ghi đè toàn bộ. FE call debounced khi user thay đổi.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(404, "Project không tồn tại")
    cfg = body.get('config')
    if cfg is None:
        raise HTTPException(400, "Body phải có 'config'")
    try:
        # Validate qua Pydantic để chắc cấu trúc đúng
        ExportConfig(**cfg)
    except Exception as e:
        raise HTTPException(400, f"Config không hợp lệ: {e}")

    project.last_export_config_json = json.dumps(cfg)
    db.commit()
    return {'ok': True}
