from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import func
from pathlib import Path
import json, shutil, uuid

from dubeditor.database import get_db
from dubeditor.models import Project, Subtitle, Bible, Scene
from dubeditor.schemas import ProjectCreate, ProjectOut

router = APIRouter()

BASE_DIR    = Path(__file__).parent.parent.parent
STORAGE     = BASE_DIR / "data" / "projects"
VIDEO_DIR   = STORAGE / "_videos"
EXPORTS_DIR = STORAGE / "_exports"

for d in [STORAGE, VIDEO_DIR, EXPORTS_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def _enrich_project_out(p: Project, db: Session) -> ProjectOut:
    """Build ProjectOut từ Project + tính các counts."""
    total = db.query(func.count(Subtitle.id)).filter(Subtitle.project_id == p.id).scalar()
    done  = db.query(func.count(Subtitle.id)).filter(
        Subtitle.project_id == p.id, Subtitle.tts_done == True  # noqa: E712
    ).scalar()
    scene_count = db.query(func.count(Scene.id)).filter(Scene.project_id == p.id).scalar()
    has_bible = db.query(Bible).filter(
        Bible.project_id == p.id, Bible.is_active == True  # noqa: E712
    ).first() is not None

    # v3.9: parse last_filter_chapter_ids từ Text JSON → list[int].
    # Pydantic v2 không tự parse JSON string → list nên phải làm tay TRƯỚC khi validate.
    parsed_filter_ids = None
    try:
        raw = (p.last_filter_chapter_ids or "").strip()
        if raw:
            v = json.loads(raw)
            if isinstance(v, list):
                tmp = [int(x) for x in v if isinstance(x, (int, float))
                       or (isinstance(x, str) and x.lstrip("-").isdigit())]
                parsed_filter_ids = tmp if tmp else None
    except Exception:
        parsed_filter_ids = None

    # Dùng model_construct() + gán field thủ công thay vì model_validate(p)
    # để tránh đụng cột JSON-text vào kiểu list của Pydantic.
    out = ProjectOut(
        id=p.id,
        name=p.name,
        video_path=p.video_path,
        video_name=p.video_name,
        duration=p.duration or 0.0,
        created_at=p.created_at,
        subtitle_count=total or 0,
        tts_done_count=done or 0,
        current_chapter_id=p.current_chapter_id,
        source_lang=p.source_lang or 'vi',
        project_type=p.project_type or 'short_drama',
        genre_pack=p.genre_pack,
        translate_status=p.translate_status or 'idle',
        translate_progress=p.translate_progress or 0.0,
        translate_error=p.translate_error,
        has_bible=has_bible,
        scene_count=scene_count or 0,
        use_emotion_voice=bool(p.use_emotion_voice),
        tts_voice_mode=p.tts_voice_mode,
        last_filter_chapter_ids=parsed_filter_ids,
        last_subtitle_index=p.last_subtitle_index,
    )
    return out


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.updated_at.desc()).all()
    return [_enrich_project_out(p, db) for p in projects]


@router.post("/", response_model=ProjectOut)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(name=data.name, project_type=data.project_type or 'short_drama')
    db.add(p); db.commit(); db.refresh(p)
    (STORAGE / str(p.id) / "audio").mkdir(parents=True, exist_ok=True)
    return _enrich_project_out(p, db)


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")
    return _enrich_project_out(p, db)


@router.patch("/{project_id}")
def update_project(project_id: int, body: dict, db: Session = Depends(get_db)):
    """Update các field cấu hình của project. Hiện tại hỗ trợ:
      - use_emotion_voice (bool): bật/tắt multi-mode voice cho TTS
      - tts_voice_mode (str|null): override mode global
      - name (str): đổi tên project
      - last_filter_chapter_ids (list[int]|null): lưu filter chapter để resume
      - last_subtitle_index (int|null): lưu sub đang làm dở để resume scroll
    """
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    # Whitelist các field được phép update
    if "use_emotion_voice" in body:
        p.use_emotion_voice = bool(body["use_emotion_voice"])
    if "tts_voice_mode" in body:
        # null/empty string = clear override (auto theo emotion)
        v = body["tts_voice_mode"]
        p.tts_voice_mode = v if (v and str(v).strip()) else None
    if "name" in body:
        p.name = str(body["name"])
    # v3.9: Editor resume state
    if "last_filter_chapter_ids" in body:
        v = body["last_filter_chapter_ids"]
        if v is None or (isinstance(v, list) and len(v) == 0):
            p.last_filter_chapter_ids = None
        elif isinstance(v, list):
            # Chỉ giữ int hợp lệ, dump compact JSON
            clean = [int(x) for x in v if isinstance(x, (int, float)) or
                     (isinstance(x, str) and x.lstrip("-").isdigit())]
            p.last_filter_chapter_ids = json.dumps(clean) if clean else None
        else:
            raise HTTPException(400, "last_filter_chapter_ids phải là list[int] hoặc null")
    if "last_subtitle_index" in body:
        v = body["last_subtitle_index"]
        if v is None:
            p.last_subtitle_index = None
        else:
            try:
                p.last_subtitle_index = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, "last_subtitle_index phải là int hoặc null")

    db.commit(); db.refresh(p)
    # Parse lại JSON để trả về
    try:
        raw = (p.last_filter_chapter_ids or "").strip()
        parsed_ids = json.loads(raw) if raw else None
    except Exception:
        parsed_ids = None
    return {
        "ok": True,
        "use_emotion_voice": bool(p.use_emotion_voice),
        "tts_voice_mode": p.tts_voice_mode,
        "last_filter_chapter_ids": parsed_ids,
        "last_subtitle_index": p.last_subtitle_index,
    }


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
async def import_srt(
    project_id: int,
    file: UploadFile = File(...),
    force: bool = False,                 # giữ lại để backward-compatible
    lang_override: str | None = None,    # 'vi' = user xác nhận import như SRT Việt
    db: Session = Depends(get_db),
):
    """Import SRT vào project.

    Tự động detect language qua tỉ lệ ký tự CJK.
    - is_chinese=True (CJK ≥ 30%): set source_lang='zh', dùng cho pipeline v2
    - is_chinese=False:
        + Nếu lang_override='vi' (hoặc force=True): import như SRT tiếng Việt,
          source_lang='vi'. Phụ đề được lưu thẳng vào `text` (đã dịch sẵn).
        + Ngược lại: trả 400 với mã DETECTED_NON_CHINESE để FE confirm.
    """
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    raw = await file.read()
    # Thử nhiều encoding — SRT có thể là utf-8, utf-8-sig (BOM), gbk, gb18030
    content = None
    used_encoding = None
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            content = raw.decode(encoding)
            used_encoding = encoding
            break
        except UnicodeDecodeError:
            continue
    if content is None:
        raise HTTPException(400, "Không decode được SRT (đã thử utf-8/utf-8-sig/gbk/gb18030)")

    # Detect language qua tỉ lệ ký tự CJK — CHỈ count trên TEXT LINES
    # (bỏ qua SRT index lines + timestamp lines, vì chúng toàn ASCII)
    import re as _re

    # Lọc ra các dòng text thuần (không phải số STT, không phải timestamp)
    TS_RE = _re.compile(r'^\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->')
    INDEX_RE = _re.compile(r'^\d+$')
    text_only_lines = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if INDEX_RE.match(stripped):
            continue
        if TS_RE.match(stripped):
            continue
        text_only_lines.append(stripped)

    text_blob = "\n".join(text_only_lines)
    cjk_count = len(_re.findall(r'[\u4e00-\u9fff]', text_blob))
    text_chars = len(_re.findall(r'\S', text_blob))
    cjk_ratio = cjk_count / max(text_chars, 1)
    is_chinese = cjk_ratio >= 0.3   # 30% trở lên ≈ chắc chắn là Trung

    # User đã xác nhận import như SRT Việt (qua dialog FE) hoặc force cũ
    as_vietnamese = (lang_override == "vi") or force

    # Block nếu không phải tiếng Trung (trừ khi user đã xác nhận as_vietnamese)
    if not is_chinese and not as_vietnamese:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "DETECTED_NON_CHINESE",
                "message": (
                    f"File này không phải SRT tiếng Trung "
                    f"(chỉ {cjk_count} ký tự Trung / {text_chars} ký tự = "
                    f"{cjk_ratio*100:.1f}%, cần ≥ 30%). "
                    f"Bạn có muốn import như SRT tiếng Việt (đã dịch sẵn) không?"
                ),
                "cjk_count": cjk_count,
                "total_chars": text_chars,
                "cjk_ratio": round(cjk_ratio, 3),
                "encoding": used_encoding,
            },
        )

    # Parse SRT — nếu as_vietnamese thì coi như đã dịch (không cần TQ)
    subs = parse_srt(content, is_chinese=is_chinese)
    if not subs:
        raise HTTPException(400, "SRT không có dòng hợp lệ nào (không match được timestamp).")

    db.query(Subtitle).filter(Subtitle.project_id == project_id).delete()
    for i, s in enumerate(subs):
        if as_vietnamese:
            # SRT Việt: text = nội dung (đã dịch), original_text = None (không có TQ gốc).
            # → FE biết để ẩn row TQ, không hiện "Chưa dịch".
            sub_data = {
                "start_time":    s["start_time"],
                "end_time":      s["end_time"],
                "text":          s["text"],
                "original_text": None,
            }
        else:
            # SRT Trung: lưu cùng text vào cả `text` (sẽ thay bằng bản dịch sau)
            # và `original_text` (bản gốc — không bao giờ thay đổi).
            sub_data = {
                "start_time":    s["start_time"],
                "end_time":      s["end_time"],
                "text":          s["text"],
                "original_text": s["text"],
            }
        db.add(Subtitle(project_id=project_id, index=i+1, **sub_data))

    p.source_lang = "vi" if as_vietnamese else ("zh" if is_chinese else "vi")
    db.commit()
    return {
        "imported": len(subs),
        "source_lang": p.source_lang,
        "detected_chinese": is_chinese,
        "cjk_ratio": round(cjk_ratio, 3),
        "encoding": used_encoding,
        "as_vietnamese": as_vietnamese,
    }


def parse_srt(content: str, is_chinese: bool = False) -> list[dict]:
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
                # Format text: chỉ áp dụng cho tiếng Việt/Latin, KHÔNG cho tiếng Trung
                if not is_chinese:
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


@router.post("/{project_id}/backfill-original-text")
def backfill_original_text(project_id: int, db: Session = Depends(get_db)):
    """Backfill original_text từ text cho subtitles cũ chưa có gốc.

    Dùng khi project đã import SRT trước khi fix bug original_text.
    Chỉ áp cho subtitles có translation_version=1 (chưa qua pipeline v2).
    """
    p = db.query(Project).filter(Project.id == project_id).first()
    if not p:
        raise HTTPException(404, "Project not found")

    updated = 0
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id,
        Subtitle.original_text.is_(None),
    ).all()
    for s in subs:
        if s.text:
            s.original_text = s.text
            updated += 1
    db.commit()
    return {"backfilled": updated, "total": len(subs)}