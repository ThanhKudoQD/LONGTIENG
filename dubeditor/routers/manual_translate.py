"""
Router cho chế độ Dịch Thủ công.

Endpoints (mount at /dub/api):
  GET  /projects/{pid}/manual-translate/stages
        → List 8 stage có thể chạy thủ công, kèm trạng thái (đã có data chưa)

  GET  /projects/{pid}/manual-translate/units?stage=<stage>
        → List unit_key của 1 stage (vd. Stage 2 có N arc, Stage 4 có N chunk)

  POST /projects/{pid}/manual-translate/build-prompt
        body: { stage, unit_key? }
        → Trả về prompt text + meta để frontend hiển thị

  POST /projects/{pid}/manual-translate/apply-response
        body: { stage, unit_key, meta, raw_response }
        → Parse response và save vào DB

Tất cả endpoint KHÔNG cần api_key (không gọi LLM thật).
"""
from __future__ import annotations
import logging
import sys
from pathlib import Path
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from dubeditor.database import get_db
from dubeditor.models import (
    Project, Subtitle,
    Bible as DBBible, StoryArc as DBStoryArc, Chunk as DBChunk,
)

# Add srt_translator_v2 to sys.path
_TRANSLATOR_DIR = Path(__file__).parent.parent.parent / "srt_translator_v2"
if str(_TRANSLATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATOR_DIR))

from manual import build_prompt, apply_response, list_units
from config import default_config

# v3.15: persistence
from dubeditor import manual_translate_state as mts

logger = logging.getLogger(__name__)
router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────

class StageInfo(BaseModel):
    stage: str
    label: str
    description: str
    ready: bool             # đủ điều kiện chạy (đã có dependency)
    has_data: bool          # đã có data trong DB chưa
    units_count: int = 0    # với multi-unit stage
    dependency_msg: Optional[str] = None  # giải thích nếu ready=False
    # v3.15: progress thủ công
    applied_units_count: int = 0   # số unit đã apply OK
    built_units_count: int = 0     # số unit đã build prompt (chưa apply)
    failed_units_count: int = 0    # số unit apply lỗi


class UnitInfo(BaseModel):
    unit_key: str
    label: str
    status: str = "pending"  # pending | built | applied | failed
    has_prompt: bool = False
    has_response: bool = False
    applied_at: Optional[str] = None
    apply_summary: Optional[str] = None


class BuildPromptRequest(BaseModel):
    stage: str
    unit_key: Optional[str] = None
    force_rebuild: bool = False  # True = build mới ngay cả khi đã có saved prompt


class BuildPromptResponse(BaseModel):
    stage: str
    unit_key: str
    label: str
    prompt: str
    meta: dict[str, Any]
    char_count: int
    # v3.15: trạng thái lưu trữ
    status: str = "built"
    raw_response: str = ""        # nếu đã có response cũ → trả luôn
    apply_summary: Optional[str] = None
    applied_at: Optional[str] = None
    from_cache: bool = False      # True = load lại từ DB, False = build mới


class ApplyResponseRequest(BaseModel):
    stage: str
    unit_key: str
    meta: dict[str, Any] = Field(default_factory=dict)
    raw_response: str


class ApplyResponseResult(BaseModel):
    stage: str
    unit_key: str
    ok: bool
    summary: str
    counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    status: str = "applied"
    applied_at: Optional[str] = None


# v3.15: auto-save schemas
class SavePromptEditRequest(BaseModel):
    stage: str
    unit_key: str
    prompt: str


class SaveResponseDraftRequest(BaseModel):
    stage: str
    unit_key: str
    raw_response: str


class ResetUnitRequest(BaseModel):
    stage: str
    unit_key: Optional[str] = None  # None = reset cả stage


# ─────────────────────────────────────────────────────────────────
# Stage definitions (UI metadata)
# ─────────────────────────────────────────────────────────────────

_STAGE_DEFS = [
    {
        "stage": "normalize",
        "label": "Stage 0 — Chuẩn hóa",
        "description": "Phát hiện + làm sạch dòng watermark/quảng cáo/số tập. "
                        "Phim sạch có thể skip.",
        "deps": [],
    },
    {
        "stage": "bible_cast",
        "label": "Stage 1A.1 — Cast",
        "description": "Trích xuất nhân vật (tên Hán Việt, vai trò, quan hệ).",
        "deps": [],
    },
    {
        "stage": "bible_glossary",
        "label": "Stage 1A.2 — Glossary",
        "description": "Trích xuất thuật ngữ riêng + xưng hô thể loại.",
        "deps": [],
    },
    {
        "stage": "bible_world",
        "label": "Stage 1B — World + Arcs",
        "description": "Genre, era, tone, plot, chia phim thành story arcs.",
        "deps": ["bible_cast"],
    },
    {
        "stage": "chunks",
        "label": "Stage 2 — Chunks + Scenes",
        "description": "Mỗi arc chia thành chunks (chương kịch) + scenes con. "
                        "1 prompt / arc.",
        "deps": ["bible_world"],
    },
    {
        "stage": "speaker",
        "label": "Stage 3 — Speaker",
        "description": "Gán speaker cho từng dòng thoại. 1 prompt / chunk.",
        "deps": ["chunks"],
    },
    {
        "stage": "translate",
        "label": "Stage 4 — Translate ⭐",
        "description": "Dịch 5 tầng + 2 variants (v1 sát nghĩa, v2 thoát ý). "
                        "1 prompt / chunk.",
        "deps": ["speaker"],
    },
    {
        "stage": "polish",
        "label": "Stage 5 — Polish/Retry",
        "description": "Retry dòng còn TQ / rỗng. Batch 10 dòng/prompt.",
        "deps": ["translate"],
    },
]


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _get_project(db: Session, pid: int) -> Project:
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, f"Project {pid} not found")
    return p


def _check_stage_dependencies(db: Session, project_id: int, stage: str) -> tuple[bool, Optional[str]]:
    """Kiểm tra dependency đã sẵn sàng chưa. Trả (ready, msg_if_not)."""
    deps = next((s["deps"] for s in _STAGE_DEFS if s["stage"] == stage), [])

    for dep in deps:
        if dep == "bible_cast":
            bible = db.query(DBBible).filter(
                DBBible.project_id == project_id,
                DBBible.is_active == True,
            ).first()
            if not bible or not bible.cast_json or bible.cast_json in ("{}", ""):
                return False, "Cần chạy Stage 1A.1 (Cast) trước."

        elif dep == "bible_world":
            bible = db.query(DBBible).filter(
                DBBible.project_id == project_id,
                DBBible.is_active == True,
            ).first()
            has_arcs = db.query(DBStoryArc).filter(
                DBStoryArc.project_id == project_id
            ).count() > 0
            if not bible or not has_arcs:
                return False, "Cần chạy Stage 1B (World + Arcs) trước."

        elif dep == "chunks":
            chunks_count = db.query(DBChunk).filter(
                DBChunk.project_id == project_id
            ).count()
            if chunks_count == 0:
                return False, "Cần chạy Stage 2 (Chunks) trước."

        elif dep == "speaker":
            # speaker không bắt buộc nhưng khuyến khích — cho phép translate mà chưa có speaker
            speakers_count = db.query(Subtitle).filter(
                Subtitle.project_id == project_id,
                Subtitle.speaker_zh.isnot(None),
            ).count()
            if speakers_count == 0:
                return False, ("Khuyến nghị chạy Stage 3 (Speaker) trước, "
                               "nhưng có thể tiếp tục nếu chấp nhận chất lượng giảm.")

        elif dep == "translate":
            translated_count = db.query(Subtitle).filter(
                Subtitle.project_id == project_id,
                Subtitle.text_v1.isnot(None),
                Subtitle.text_v1 != "",
            ).count()
            if translated_count == 0:
                return False, "Cần chạy Stage 4 (Translate) trước."

    return True, None


def _check_stage_has_data(db: Session, project_id: int, stage: str) -> tuple[bool, int]:
    """Kiểm tra stage này đã có data chưa + số unit hiện có (cho multi-unit)."""
    if stage == "normalize":
        # Coi là có data nếu có dòng được mark is_noise hoặc đã clean
        count = db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.is_noise == True,
        ).count()
        return count > 0, 0

    if stage == "bible_cast":
        bible = db.query(DBBible).filter(
            DBBible.project_id == project_id,
            DBBible.is_active == True,
        ).first()
        has = bool(bible and bible.cast_json and bible.cast_json not in ("{}", ""))
        return has, 0

    if stage == "bible_glossary":
        bible = db.query(DBBible).filter(
            DBBible.project_id == project_id,
            DBBible.is_active == True,
        ).first()
        has = bool(bible and bible.glossary_json and bible.glossary_json not in ("{}", ""))
        return has, 0

    if stage == "bible_world":
        arcs = db.query(DBStoryArc).filter(
            DBStoryArc.project_id == project_id
        ).count()
        return arcs > 0, arcs

    if stage == "chunks":
        chunks = db.query(DBChunk).filter(
            DBChunk.project_id == project_id
        ).count()
        arcs = db.query(DBStoryArc).filter(
            DBStoryArc.project_id == project_id
        ).count()
        return chunks > 0, arcs

    if stage == "speaker":
        speakers = db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.speaker_zh.isnot(None),
        ).count()
        chunks = db.query(DBChunk).filter(
            DBChunk.project_id == project_id
        ).count()
        return speakers > 0, chunks

    if stage == "translate":
        translated = db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.text_v1.isnot(None),
            Subtitle.text_v1 != "",
        ).count()
        chunks = db.query(DBChunk).filter(
            DBChunk.project_id == project_id
        ).count()
        return translated > 0, chunks

    if stage == "polish":
        # polish: số unit = số batch cần retry hiện tại
        return False, 0

    return False, 0


# ─────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/manual-translate/stages",
             response_model=list[StageInfo])
def list_stages(pid: int, db: Session = Depends(get_db)):
    """List 8 stage có thể chạy thủ công, kèm trạng thái + progress thủ công."""
    _get_project(db, pid)

    result = []
    for s in _STAGE_DEFS:
        stage = s["stage"]
        ready, dep_msg = _check_stage_dependencies(db, pid, stage)
        has_data, units_count = _check_stage_has_data(db, pid, stage)
        # v3.15: progress thủ công từ manual_translate_units table
        summary = mts.stage_summary(db, pid, stage)
        result.append(StageInfo(
            stage=stage,
            label=s["label"],
            description=s["description"],
            ready=ready,
            has_data=has_data,
            units_count=units_count,
            dependency_msg=dep_msg,
            applied_units_count=summary["applied"],
            built_units_count=summary["built"],
            failed_units_count=summary["failed"],
        ))
    return result


@router.get("/projects/{pid}/manual-translate/units",
             response_model=list[UnitInfo])
def list_stage_units(pid: int, stage: str, db: Session = Depends(get_db)):
    """List unit_key của 1 stage. Merge trạng thái đã lưu từ DB."""
    _get_project(db, pid)
    cfg = default_config()

    try:
        units = list_units(stage, db, pid, cfg)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"list_units pid={pid} stage={stage}")
        raise HTTPException(500, f"Lỗi khi list units: {e}")

    # v3.15: merge với state đã lưu
    status_map = mts.list_status_map(db, pid, stage)
    result = []
    for u in units:
        state = status_map.get(u.unit_key, {})
        result.append(UnitInfo(
            unit_key=u.unit_key,
            label=u.label,
            status=state.get("status", "pending"),
            has_prompt=state.get("has_prompt", False),
            has_response=state.get("has_response", False),
            applied_at=state.get("applied_at"),
            apply_summary=state.get("apply_summary"),
        ))
    return result


@router.post("/projects/{pid}/manual-translate/build-prompt",
              response_model=BuildPromptResponse)
def build_prompt_endpoint(pid: int, req: BuildPromptRequest,
                           db: Session = Depends(get_db)):
    """Build prompt cho 1 unit. Frontend hiển thị cho user copy.

    v3.15: Nếu unit đã có prompt + response đã lưu (user mở lại), trả luôn
    từ DB thay vì build mới — trừ khi force_rebuild=True.
    """
    _get_project(db, pid)
    cfg = default_config()

    # Check dependency
    ready, dep_msg = _check_stage_dependencies(db, pid, req.stage)
    if not ready and dep_msg and "Khuyến nghị" not in dep_msg:
        raise HTTPException(400, dep_msg)

    if not req.unit_key:
        raise HTTPException(400, "Thiếu unit_key")

    # v3.15: Try load cached state trước
    if not req.force_rebuild:
        cached = mts.get_unit(db, pid, req.stage, req.unit_key)
        if cached and cached.prompt:
            try:
                import json
                meta = json.loads(cached.meta_json) if cached.meta_json else {}
            except Exception:
                meta = {}
            return BuildPromptResponse(
                stage=cached.stage,
                unit_key=cached.unit_key,
                label=cached.label or "",
                prompt=cached.prompt,
                meta=meta,
                char_count=len(cached.prompt),
                status=cached.status or "built",
                raw_response=cached.raw_response or "",
                apply_summary=cached.apply_summary,
                applied_at=cached.applied_at.isoformat() if cached.applied_at else None,
                from_cache=True,
            )

    # Build mới
    try:
        prompts = build_prompt(
            stage=req.stage,
            db=db,
            project_id=pid,
            config=cfg,
            unit_key=req.unit_key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"build_prompt pid={pid} stage={req.stage}")
        raise HTTPException(500, f"Lỗi build prompt: {e}")

    if not prompts:
        raise HTTPException(404, f"Không tìm thấy unit '{req.unit_key}'")

    bp = prompts[0]

    # v3.15: save prompt vào DB ngay khi build
    try:
        saved = mts.save_built_prompt(
            db, pid, bp.stage, bp.unit_key, bp.label, bp.prompt, bp.meta
        )
    except Exception as e:
        logger.warning(f"[manual] save_built_prompt failed pid={pid}: {e}")
        saved = None

    # Nếu force_rebuild → giữ lại response cũ (user có thể đã paste)
    raw_response = ""
    apply_summary = None
    applied_at = None
    status = "built"
    if req.force_rebuild:
        prev = mts.get_unit(db, pid, bp.stage, bp.unit_key)
        if prev:
            raw_response = prev.raw_response or ""
            apply_summary = prev.apply_summary
            applied_at = prev.applied_at.isoformat() if prev.applied_at else None
            # nếu đã applied trước đó thì giữ status applied
            if prev.status == "applied":
                status = "applied"

    return BuildPromptResponse(
        stage=bp.stage,
        unit_key=bp.unit_key,
        label=bp.label,
        prompt=bp.prompt,
        meta=bp.meta,
        char_count=len(bp.prompt),
        status=status,
        raw_response=raw_response,
        apply_summary=apply_summary,
        applied_at=applied_at,
        from_cache=False,
    )


@router.post("/projects/{pid}/manual-translate/apply-response",
              response_model=ApplyResponseResult)
def apply_response_endpoint(pid: int, req: ApplyResponseRequest,
                             db: Session = Depends(get_db)):
    """Parse response user paste và save vào DB.

    v3.15: Sau khi apply (thành công HAY thất bại), lưu raw_response + status
    vào manual_translate_units để user mở lại không mất data.
    """
    _get_project(db, pid)
    cfg = default_config()

    # Inject unit_key vào meta nếu chưa có (parser sẽ dùng)
    meta = dict(req.meta or {})
    meta.setdefault("unit_key", req.unit_key)

    # Nếu meta rỗng → thử load từ DB (user có thể đã build trước đó rồi mở lại)
    if not meta or len(meta) == 1:  # chỉ có unit_key
        cached = mts.get_unit(db, pid, req.stage, req.unit_key)
        if cached and cached.meta_json:
            try:
                import json
                cached_meta = json.loads(cached.meta_json)
                if cached_meta:
                    cached_meta["unit_key"] = req.unit_key
                    meta = cached_meta
            except Exception:
                pass

    result = apply_response(
        stage=req.stage,
        db=db,
        project_id=pid,
        raw_response=req.raw_response,
        meta=meta,
        config=cfg,
    )

    # v3.15: lưu state
    try:
        saved = mts.save_apply_result(
            db, pid, req.stage, req.unit_key,
            raw_response=req.raw_response,
            ok=result.ok,
            summary=result.summary,
            counts=result.counts,
            warnings=result.warnings,
            errors=result.errors,
        )
        applied_at = saved.applied_at.isoformat() if saved.applied_at else None
        final_status = saved.status
    except Exception as e:
        logger.warning(f"[manual] save_apply_result failed pid={pid}: {e}")
        applied_at = None
        final_status = "applied" if result.ok else "failed"

    return ApplyResponseResult(
        stage=result.stage,
        unit_key=result.unit_key,
        ok=result.ok,
        summary=result.summary,
        counts=result.counts,
        warnings=result.warnings,
        errors=result.errors,
        status=final_status,
        applied_at=applied_at,
    )


# ─────────────────────────────────────────────────────────────────
# v3.15: Auto-save + state endpoints
# ─────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/manual-translate/unit-state")
def get_unit_state(pid: int, stage: str, unit_key: str,
                    db: Session = Depends(get_db)):
    """Load lại state đã lưu của 1 unit (prompt + response + status + apply result).

    Frontend gọi khi user click vào unit để restore UI.
    Trả null nếu chưa có data.
    """
    _get_project(db, pid)
    row = mts.get_unit(db, pid, stage, unit_key)
    if not row:
        return None
    return mts.serialize_unit(row)


@router.post("/projects/{pid}/manual-translate/save-prompt-edit")
def save_prompt_edit(pid: int, req: SavePromptEditRequest,
                      db: Session = Depends(get_db)):
    """Auto-save khi user edit prompt trực tiếp (frontend debounce ~1s)."""
    _get_project(db, pid)
    try:
        row = mts.save_prompt_edit(db, pid, req.stage, req.unit_key, req.prompt)
        return {"ok": True, "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    except Exception as e:
        logger.exception(f"save_prompt_edit pid={pid}")
        raise HTTPException(500, f"Save lỗi: {e}")


@router.post("/projects/{pid}/manual-translate/save-response-draft")
def save_response_draft(pid: int, req: SaveResponseDraftRequest,
                         db: Session = Depends(get_db)):
    """Auto-save khi user gõ vào ô response (chưa bấm Apply).

    Frontend debounce ~1-2s để không spam server.
    """
    _get_project(db, pid)
    try:
        row = mts.save_response_text(db, pid, req.stage, req.unit_key,
                                       req.raw_response)
        return {"ok": True, "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    except Exception as e:
        logger.exception(f"save_response_draft pid={pid}")
        raise HTTPException(500, f"Save lỗi: {e}")


@router.post("/projects/{pid}/manual-translate/reset")
def reset_units(pid: int, req: ResetUnitRequest,
                 db: Session = Depends(get_db)):
    """Reset state thủ công.

    - unit_key cụ thể → xóa 1 unit
    - unit_key=None  → xóa toàn bộ stage
    """
    _get_project(db, pid)
    try:
        if req.unit_key:
            deleted = mts.delete_unit(db, pid, req.stage, req.unit_key)
            return {"ok": True, "deleted": 1 if deleted else 0}
        else:
            n = mts.clear_stage(db, pid, req.stage)
            return {"ok": True, "deleted": n}
    except Exception as e:
        logger.exception(f"reset_units pid={pid}")
        raise HTTPException(500, f"Reset lỗi: {e}")
