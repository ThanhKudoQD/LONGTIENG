from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
import shutil, os, uuid

from database import get_db
from models import Project, Subtitle
from schemas import ProjectCreate, ProjectOut

router = APIRouter()
STORAGE = os.getenv("STORAGE_PATH", "../storage")


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

    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4()}{ext}"
    dest = os.path.join(STORAGE, "videos", filename)

    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    p.video_path = f"/storage/videos/{filename}"
    p.video_name = file.filename
    db.commit(); db.refresh(p)
    return {"video_path": p.video_path, "video_name": p.video_name}


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
    blocks = re.split(r"\n\n+", content.strip())
    result = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 3:
            continue
        try:
            time_line = lines[1]
            match = re.match(r"(\d+:\d+:\d+[,\.]\d+)\s*-->\s*(\d+:\d+:\d+[,\.]\d+)", time_line)
            if not match:
                continue
            start = srt_time_to_sec(match.group(1))
            end   = srt_time_to_sec(match.group(2))
            text  = "\n".join(lines[2:]).strip()
            result.append({"start_time": start, "end_time": end, "text": text})
        except Exception:
            continue
    return result


def srt_time_to_sec(t: str) -> float:
    t = t.replace(",", ".")
    h, m, rest = t.split(":")
    s, ms = rest.split(".")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000
