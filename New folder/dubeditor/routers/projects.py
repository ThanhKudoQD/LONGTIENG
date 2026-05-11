from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
import shutil, uuid

from dubeditor.database import get_db
from dubeditor.models import Project, Subtitle
from dubeditor.schemas import ProjectCreate, ProjectOut

router = APIRouter()

BASE_DIR    = Path(__file__).parent.parent.parent
STORAGE     = BASE_DIR / "data" / "projects"
VIDEO_DIR   = STORAGE / "_videos"
EXPORTS_DIR = STORAGE / "_exports"

for d in [STORAGE, VIDEO_DIR, EXPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    result = []
    for p in projects:
        total = db.query(func.count(Subtitle.id)).filter(Subtitle.project_id == p.id).scalar()
        done  = db.query(func.count(Subtitle.id)).filter(Subtitle.project_id == p.id, Subtitle.tts_done == True).scalar()
        out = ProjectOut.model_validate(p)
        out.subtitle_count = total or 0
        out.tts_done_count = done or 0
        result.append(out)
    return result


@router.post("/", response_model=ProjectOut)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(name=data.name)
    db.add(p); db.commit(); db.refresh(p)
    (STORAGE / str(p.id) / "audio").mkdir(parents=True, exist_ok=True)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    total = db.query(func.count(Subtitle.id)).filter(Subtitle.project_id == p.id).scalar()
    done  = db.query(func.count(Subtitle.id)).filter(Subtitle.project_id == p.id, Subtitle.tts_done == True).scalar()
    out = ProjectOut.model_validate(p)
    out.subtitle_count = total or 0
    out.tts_done_count = done or 0
    return out


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    db.delete(p); db.commit()
    return {"ok": True}


@router.post("/{project_id}/upload-video")
async def upload_video(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    import subprocess, logging
    from dubeditor.routers.ws import broadcast
    logger = logging.getLogger(__name__)

    out_name = f"{uuid.uuid4()}{Path(file.filename).suffix}"
    out_path = VIDEO_DIR / out_name

    total_size = int(file.size or 0)
    saved = 0
    last_pct = -1
    chunk_size = 2 * 1024 * 1024  # 2MB

    await broadcast(project_id, {"type": "video_upload", "status": "saving", "msg": "Bắt đầu upload...", "pct": 0})

    with open(out_path, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
            saved += len(chunk)
            if total_size > 0:
                pct = int(saved / total_size * 100)
                if pct >= last_pct + 5:
                    last_pct = pct
                    await broadcast(project_id, {
                        "type": "video_upload", "status": "saving",
                        "msg": f"Đang upload {pct}% ({saved//1024//1024}/{total_size//1024//1024}MB)",
                        "pct": pct
                    })

    # Lấy duration
    try:
        dur_proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(out_path)],
            capture_output=True, text=True
        )
        video_duration = float(dur_proc.stdout.strip())
    except:
        video_duration = 0.0

    out_mb = out_path.stat().st_size / 1024 / 1024
    logger.info(f"[Video] Saved: {out_name} ({out_mb:.1f}MB, {video_duration:.0f}s)")

    p.video_path = f"/dub/videos/{out_name}"
    p.video_name = file.filename
    p.duration   = video_duration
    db.commit(); db.refresh(p)

    await broadcast(project_id, {
        "type": "video_upload", "status": "done",
        "msg": f"Upload xong! {out_mb:.0f}MB",
        "video_path": p.video_path,
        "video_name": p.video_name,
        "duration": video_duration,
        "pct": 100,
    })
    return {"video_path": p.video_path, "video_name": p.video_name, "duration": video_duration}

@router.post("/{project_id}/import-srt")
async def import_srt(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    content = (await file.read()).decode("utf-8")
    subs = parse_srt(content)

    db.query(Subtitle).filter(Subtitle.project_id == project_id).delete()
    for i, s in enumerate(subs):
        db.add(Subtitle(project_id=project_id, index=i+1, **s))
    db.commit()
    return {"imported": len(subs)}


def parse_srt(content: str) -> list[dict]:
    import re
    result = []
    TIME_RE = re.compile(r"(\d+:\d+:\d+[,.]\d+)\s*-->\s*(\d+:\d+:\d+[,.]\d+)")

    # Chuẩn hóa line endings
    content = content.replace("\r\n", "\n").replace("\r", "\n").strip()

    # Split thành blocks bằng dòng trống
    blocks = re.split(r"\n\s*\n", content)

    for block in blocks:
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue

        # Tìm dòng có timestamp
        time_idx = None
        for i, line in enumerate(lines):
            if TIME_RE.match(line):
                time_idx = i
                break

        if time_idx is None:
            continue

        try:
            m = TIME_RE.match(lines[time_idx])
            start = _srt_to_sec(m.group(1))
            end   = _srt_to_sec(m.group(2))

            # Text = tất cả dòng sau timestamp (bỏ số thứ tự nếu có)
            text_lines = lines[time_idx + 1:]
            # Loại bỏ dòng chỉ là số (số thứ tự)
            text_lines = [l for l in text_lines if not re.match(r"^\d+$", l)]
            text = " ".join(text_lines).strip()

            if text:
                # Format: viết hoa chữ đầu + dấu cuối câu
                text = text[0].upper() + text[1:] if text else text
                if text:
                    if text[-1] in ',，':
                        text = text[:-1] + '.'
                    elif text[-1] not in '.!?…！？':
                        text = text + '.'
                result.append({"start_time": start, "end_time": end, "text": text})
        except Exception:
            continue

    return result


def _srt_to_sec(t: str) -> float:
    t = t.replace(",", ".")
    h, m, rest = t.split(":")
    s, ms = rest.split(".")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
