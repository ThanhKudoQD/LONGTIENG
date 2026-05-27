"""
Router cho chế độ Dịch Thủ công — MEGA-CHUNK MODE (v4).

Endpoints (mount at /dub/api):
  GET  /projects/{pid}/manual-translate-mega/stages
  GET  /projects/{pid}/manual-translate-mega/units?stage=<stage>
  POST /projects/{pid}/manual-translate-mega/build-prompt
  POST /projects/{pid}/manual-translate-mega/apply-response

Stages mới (chỉ 5, gọn hơn 8 của v3):
  - bible_unified     (1 paste, gộp cast+world+glossary)
  - chunks_full       (1 paste, toàn phim)
  - translate_mega    (4-5 paste, mega 1500 dòng, gộp speaker)
  - review_pass1      (1 paste, consistency scan)
  - review_pass2      (3-5 paste, per-arc polish)

Tổng: ~10-13 paste/phim 6000 dòng.

Tách thành file riêng (KHÔNG sửa manual_translate.py cũ) để dễ rollback.
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

from manual import (
    build_prompt_mega, apply_response_mega, list_units_mega,
    BuiltPrompt, StageUnit, ApplyResult,
)
from config import default_config

# Reuse persistence layer của v3 (cùng store)
from dubeditor import manual_translate_state as mts

logger = logging.getLogger(__name__)
router = APIRouter()

# Route prefix để FE phân biệt với manual-translate cũ
PREFIX = "/projects/{pid}/manual-translate-mega"


# ═════════════════════════════════════════════════════════════════
# Stage definitions
# ═════════════════════════════════════════════════════════════════

_MEGA_STAGE_DEFS = [
    {
        "stage": "bible_unified",
        "label": "1. Bible (Cast + World + Glossary + Arcs)",
        "description": "1 prompt duy nhất — AI trích xuất toàn bộ nhân vật, bối cảnh, "
                       "story arcs (cover toàn phim) và thuật ngữ. "
                       "Arcs là đơn vị xương sống cho dịch.",
        "deps": [],
        "expected_units": 1,
    },
    # v4.2: stage "chunks_full" đã bị BỎ. Dịch trực tiếp dựa vào arcs trong Bible.
    {
        "stage": "translate_mega",
        "label": "2. Translate ⭐ (mega-chunk theo Arc, ~500 dòng/paste)",
        "description": "Dịch + gán speaker + phát hiện thuật ngữ mới TRONG 1 LƯỢT. "
                       "Mega chia theo Arc của Bible — arc dài thì chia step, "
                       "arc ngắn thì gộp. v1 = sát nghĩa, v2 = thoát ý (đều BẮT BUỘC).",
        "deps": ["bible_unified"],
        "expected_units": 5,
    },
    {
        "stage": "review_pass1",
        "label": "3. Review Pass 1 — Consistency (1 paste)",
        "description": "Tool scan code-based các issue (xưng hô shift, glossary, "
                       "residual Chinese, CPS quá cao) → AI quyết định fix hay keep.",
        "deps": ["translate_mega"],
        "expected_units": 1,
    },
    {
        "stage": "review_pass2",
        "label": "4. Review Pass 2 — Per-arc Polish",
        "description": "Editor cấp cao review từng arc — phát hiện câu cứng, "
                       "tone lệch, flow không tự nhiên. 1 paste/arc.",
        "deps": ["translate_mega"],
        "expected_units": 5,
    },
]


# ═════════════════════════════════════════════════════════════════
# Schemas
# ═════════════════════════════════════════════════════════════════

class StageInfo(BaseModel):
    stage: str
    label: str
    description: str
    ready: bool
    has_data: bool
    units_count: int = 0
    expected_units: int = 0
    dependency_msg: Optional[str] = None
    applied_units_count: int = 0
    built_units_count: int = 0
    failed_units_count: int = 0


class UnitInfo(BaseModel):
    unit_key: str
    label: str
    status: str = "pending"
    has_prompt: bool = False
    has_response: bool = False
    applied_at: Optional[str] = None
    apply_summary: Optional[str] = None


class BuildPromptRequest(BaseModel):
    stage: str
    unit_key: Optional[str] = None
    # v4.1: stage-specific options (preset, advanced flags...)
    # Hiện tại chỉ bible_unified dùng:
    #   {"preset": "balanced", "advanced": {...}}
    options: Optional[dict] = None


class BuildPromptResponse(BaseModel):
    stage: str
    unit_key: str
    label: str
    prompt: str
    meta: dict
    char_count: int
    estimated_tokens: int


class ApplyResponseRequest(BaseModel):
    stage: str
    unit_key: str
    meta: dict
    raw_response: str


class ApplyResponseOut(BaseModel):
    stage: str
    unit_key: str
    ok: bool
    summary: str
    counts: dict
    warnings: list[str] = []
    errors: list[str] = []


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════

def _get_project(db: Session, pid: int) -> Project:
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, f"Project {pid} not found")
    return p


def _check_deps(db: Session, pid: int, stage: str) -> tuple[bool, Optional[str]]:
    deps = next((s["deps"] for s in _MEGA_STAGE_DEFS if s["stage"] == stage), [])
    if not deps:
        return True, None
    for dep in deps:
        ready, _ = _check_has_data(db, pid, dep)
        if not ready:
            dep_label = next((s["label"] for s in _MEGA_STAGE_DEFS if s["stage"] == dep), dep)
            return False, f"Cần làm xong {dep_label} trước"
    return True, None


def _check_has_data(db: Session, pid: int, stage: str) -> tuple[bool, int]:
    """Kiểm tra DB đã có data cho stage chưa. Trả (has_data, count)."""
    if stage == "bible_unified":
        count = db.query(DBBible).filter(
            DBBible.project_id == pid,
            DBBible.is_active == True,
        ).count()
        # v4.2: phải có cả Bible với arcs cover full
        if count > 0:
            # Verify arcs có cover toàn phim
            total_subs = db.query(Subtitle).filter(Subtitle.project_id == pid).count()
            arcs = (db.query(DBStoryArc)
                      .filter(DBStoryArc.project_id == pid)
                      .order_by(DBStoryArc.start_line).all())
            if not arcs or not total_subs:
                return count > 0, count
            # Check arcs cover [1, total_subs]
            if arcs[0].start_line == 1 and arcs[-1].end_line >= total_subs:
                return True, count
            # Bible có nhưng arcs không cover full — vẫn return True để user có thể
            # rebuild, chỉ cảnh báo qua dependency_msg
            return True, count
        return count > 0, count
    if stage == "translate_mega":
        # Check có dòng nào đã dịch chưa (dùng text_v1 cho v4)
        count = db.query(Subtitle).filter(
            Subtitle.project_id == pid,
            Subtitle.text_v1.isnot(None),
            Subtitle.text_v1 != "",
        ).count()
        return count > 0, count
    if stage in ("review_pass1", "review_pass2"):
        # Review chỉ check khi translate_mega đã có data
        return _check_has_data(db, pid, "translate_mega")
    return False, 0


def _estimate_tokens(text: str) -> int:
    """Ước lượng token đơn giản — ~3.5 chars/token cho mix VN+TQ."""
    return max(1, int(len(text) / 3.5))


# ═════════════════════════════════════════════════════════════════
# Endpoints
# ═════════════════════════════════════════════════════════════════

@router.get(PREFIX + "/stages",
            response_model=list[StageInfo],
            tags=["manual_translate_mega"])
def mega_list_stages(pid: int, db: Session = Depends(get_db)):
    _get_project(db, pid)
    out = []
    for s in _MEGA_STAGE_DEFS:
        ready, msg = _check_deps(db, pid, s["stage"])
        has_data, _ = _check_has_data(db, pid, s["stage"])
        units_count = 0
        if ready:
            try:
                units = list_units_mega(s["stage"], db, pid, default_config())
                units_count = len(units)
            except Exception:
                units_count = 0

        # Progress từ mts
        applied = 0
        built = 0
        failed = 0
        try:
            status_map = mts.list_status_map(db, pid, s["stage"] + "_mega")
            for _, st in status_map.items():
                status = st.get("status")
                if status == "applied":
                    applied += 1
                elif status == "built":
                    built += 1
                elif status == "failed":
                    failed += 1
        except Exception:
            pass

        out.append(StageInfo(
            stage=s["stage"],
            label=s["label"],
            description=s["description"],
            ready=ready,
            has_data=has_data,
            units_count=units_count,
            expected_units=s.get("expected_units", 1),
            dependency_msg=msg,
            applied_units_count=applied,
            built_units_count=built,
            failed_units_count=failed,
        ))
    return out


@router.get(PREFIX + "/units",
            response_model=list[UnitInfo],
            tags=["manual_translate_mega"])
def mega_list_units(pid: int, stage: str, db: Session = Depends(get_db)):
    _get_project(db, pid)
    ready, msg = _check_deps(db, pid, stage)
    if not ready:
        raise HTTPException(400, msg or "Dependency chưa sẵn sàng")
    try:
        units = list_units_mega(stage, db, pid, default_config())
    except Exception as e:
        raise HTTPException(400, str(e))

    # Merge với state DB
    status_map = {}
    try:
        status_map = mts.list_status_map(db, pid, stage + "_mega")
    except Exception:
        pass

    out = []
    for u in units:
        st = status_map.get(u.unit_key, {})
        out.append(UnitInfo(
            unit_key=u.unit_key,
            label=u.label,
            status=st.get("status", "pending"),
            has_prompt=st.get("has_prompt", False),
            has_response=st.get("has_response", False),
            applied_at=st.get("applied_at"),
            apply_summary=st.get("apply_summary"),
        ))
    return out


@router.post(PREFIX + "/build-prompt",
             response_model=BuildPromptResponse,
             tags=["manual_translate_mega"])
def mega_build_prompt(
    pid: int, req: BuildPromptRequest,
    db: Session = Depends(get_db),
):
    _get_project(db, pid)
    ready, msg = _check_deps(db, pid, req.stage)
    if not ready:
        raise HTTPException(400, msg or "Dependency chưa sẵn sàng")

    try:
        prompts = build_prompt_mega(req.stage, db, pid, default_config(),
                                     unit_key=req.unit_key,
                                     options=req.options)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[mega build-prompt] failed")
        raise HTTPException(500, f"Build prompt error: {e}")

    if not prompts:
        raise HTTPException(400, "Không build được prompt nào.")

    # Multi-unit stage mà không truyền unit_key → trả unit đầu tiên
    p = prompts[0]

    # Save prompt vào state để user có thể review/edit
    try:
        mts.save_built_prompt(db, pid, req.stage + "_mega", p.unit_key,
                              p.label, p.prompt, p.meta)
    except Exception as e:
        logger.warning(f"[mega] save_built_prompt failed: {e}")

    return BuildPromptResponse(
        stage=p.stage,
        unit_key=p.unit_key,
        label=p.label,
        prompt=p.prompt,
        meta=p.meta,
        char_count=len(p.prompt),
        estimated_tokens=_estimate_tokens(p.prompt),
    )


@router.post(PREFIX + "/apply-response",
             response_model=ApplyResponseOut,
             tags=["manual_translate_mega"])
def mega_apply_response(
    pid: int, req: ApplyResponseRequest,
    db: Session = Depends(get_db),
):
    _get_project(db, pid)

    if not req.raw_response or not req.raw_response.strip():
        raise HTTPException(400, "raw_response rỗng")

    # Save raw response vào state TRƯỚC khi parse (đề phòng parse fail vẫn giữ data)
    try:
        mts.save_response_text(db, pid, req.stage + "_mega", req.unit_key,
                               req.raw_response)
    except Exception as e:
        logger.warning(f"[mega] save_response_text failed: {e}")

    try:
        result = apply_response_mega(
            req.stage, db, pid, req.raw_response, req.meta, default_config()
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("[mega apply-response] failed")
        try:
            mts.save_apply_result(
                db, pid, req.stage + "_mega", req.unit_key,
                req.raw_response, ok=False,
                summary=f"Exception: {e}",
                counts={}, warnings=[], errors=[str(e)],
            )
        except Exception:
            pass
        raise HTTPException(500, f"Apply error: {e}")

    # Save final state
    try:
        mts.save_apply_result(
            db, pid, req.stage + "_mega", req.unit_key,
            req.raw_response,
            ok=result.ok,
            summary=result.summary,
            counts=result.counts,
            warnings=result.warnings,
            errors=result.errors,
        )
    except Exception as e:
        logger.warning(f"[mega] save_apply_result failed: {e}")

    return ApplyResponseOut(
        stage=result.stage,
        unit_key=result.unit_key,
        ok=result.ok,
        summary=result.summary,
        counts=result.counts,
        warnings=result.warnings,
        errors=result.errors,
    )


# ═════════════════════════════════════════════════════════════════
# v4.1: STAGE OPTIONS (presets + advanced)
# ═════════════════════════════════════════════════════════════════

@router.get(PREFIX + "/stage-options",
            tags=["manual_translate_mega"])
def mega_stage_options(stage: str):
    """Trả về options schema cho 1 stage (FE dùng để render UI).

    Hiện tại chỉ bible_unified có options. Stage khác trả null.
    """
    if stage == "bible_unified":
        from manual.prompt_builders_mega import BIBLE_PRESETS, BIBLE_ADVANCED_DEFAULTS
        return {
            "stage": stage,
            "presets": [
                {
                    "key": key,
                    "label": preset["label"],
                    "description": preset["description"],
                }
                for key, preset in BIBLE_PRESETS.items()
            ],
            "default_preset": "balanced",
            "advanced": [
                {"key": "include_unnamed_with_role",
                 "label": "Đưa nhân vật không có tên (vd 'mẹ', 'cha dượng')",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["include_unnamed_with_role"]},
                {"key": "include_single_line_named",
                 "label": "Đưa nhân vật có tên nhưng chỉ 1 dòng thoại",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["include_single_line_named"]},
                {"key": "include_cameo",
                 "label": "Đưa cameo (xuất hiện ngắn nhưng quan trọng plot)",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["include_cameo"]},
                {"key": "glossary_titles",
                 "label": "Glossary: Chức vụ / Danh xưng",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["glossary_titles"]},
                {"key": "glossary_places_orgs",
                 "label": "Glossary: Địa danh / Tổ chức",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["glossary_places_orgs"]},
                {"key": "glossary_concepts",
                 "label": "Glossary: Khái niệm",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["glossary_concepts"]},
                {"key": "glossary_cliches",
                 "label": "Glossary: Cliché / Tropes",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["glossary_cliches"]},
                {"key": "glossary_idioms",
                 "label": "Glossary: Thành ngữ / Nói đểu",
                 "type": "bool",
                 "default": BIBLE_ADVANCED_DEFAULTS["glossary_idioms"]},
            ],
        }
    # v4.3: translate_mega có speaker_mode preset
    if stage == "translate_mega":
        from manual.speaker_modes import MODE_INFO
        return {
            "stage": stage,
            "presets": [
                {"key": key, "label": info["label"], "description": info["description"]}
                for key, info in MODE_INFO.items()
            ],
            "default_preset": "medium",
            "preset_field": "speaker_mode",   # FE đọc field này để biết key gửi backend
            "advanced": [],
        }
    # Stages khác chưa có options
    return {"stage": stage, "presets": [], "advanced": []}


# ═════════════════════════════════════════════════════════════════
# v4.2: RESET BIBLE — xóa Bible + Characters + arcs để rebuild
# ═════════════════════════════════════════════════════════════════

@router.delete(PREFIX + "/bible",
               tags=["manual_translate_mega"])
def mega_reset_bible(pid: int, db: Session = Depends(get_db)):
    """Xóa Bible + Characters + StoryArcs + clear character_id của Subtitles.

    Dùng khi user muốn rebuild Bible từ đầu (vd Bible cũ có arcs sai range).
    KHÔNG xóa text dịch (Subtitle.text/text_v1/text_v2) hay speaker_zh.
    """
    _get_project(db, pid)

    counts = {
        "bible_deleted": 0,
        "characters_deleted": 0,
        "story_arcs_deleted": 0,
        "glossary_deleted": 0,
        "subtitles_unlinked": 0,
        "manual_state_cleared": 0,
    }

    try:
        # 1. Unlink character_id từ Subtitles
        from sqlalchemy import update
        result = db.execute(
            update(Subtitle)
            .where(Subtitle.project_id == pid)
            .values(character_id=None)
        )
        counts["subtitles_unlinked"] = result.rowcount or 0

        # 2. Xóa Characters (nếu có model)
        try:
            from dubeditor.models import Character
            n = db.query(Character).filter(Character.project_id == pid).delete()
            counts["characters_deleted"] = n
        except Exception as e:
            logger.warning(f"[mega reset] delete Characters skipped: {e}")

        # 3. Xóa StoryArcs
        n = db.query(DBStoryArc).filter(DBStoryArc.project_id == pid).delete()
        counts["story_arcs_deleted"] = n

        # 4. Xóa GlossaryTerm nếu có
        try:
            from dubeditor.models import GlossaryTerm as DBGlossaryTerm
            n = db.query(DBGlossaryTerm).filter(DBGlossaryTerm.project_id == pid).delete()
            counts["glossary_deleted"] = n
        except Exception as e:
            logger.warning(f"[mega reset] delete GlossaryTerm skipped: {e}")

        # 5. Xóa Bible
        n = db.query(DBBible).filter(DBBible.project_id == pid).delete()
        counts["bible_deleted"] = n

        # 6. Xóa manual_translate_state cho stage bible_unified
        try:
            from dubeditor.models import ManualTranslateUnit
            n = (db.query(ManualTranslateUnit)
                   .filter(ManualTranslateUnit.project_id == pid,
                           ManualTranslateUnit.stage == "bible_unified_mega")
                   .delete())
            counts["manual_state_cleared"] = n
        except Exception as e:
            logger.warning(f"[mega reset] delete ManualTranslateUnit skipped: {e}")

        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("[mega reset bible] failed")
        raise HTTPException(500, f"Reset Bible failed: {e}")

    return {
        "ok": True,
        "summary": (f"Đã reset Bible: {counts['bible_deleted']} bible, "
                    f"{counts['characters_deleted']} nhân vật, "
                    f"{counts['story_arcs_deleted']} arcs, "
                    f"{counts['glossary_deleted']} terms"),
        "counts": counts,
    }


# ═════════════════════════════════════════════════════════════════
# v4.2: MEGA TARGET CONFIG — cấu hình số dòng/mega
# ═════════════════════════════════════════════════════════════════

class MegaTargetSetRequest(BaseModel):
    target: int = Field(..., ge=200, le=2000)


@router.get(PREFIX + "/mega-target",
            tags=["manual_translate_mega"])
def mega_get_target(pid: int, db: Session = Depends(get_db)):
    """Lấy target lines/mega của project.

    Default: 500. Range: 200-2000.
    """
    p = _get_project(db, pid)
    from manual.prompt_builders_mega import (
        DEFAULT_MEGA_TARGET_LINES, MEGA_TARGET_MIN, MEGA_TARGET_MAX,
    )
    val = getattr(p, "mega_target_lines", None) or DEFAULT_MEGA_TARGET_LINES
    return {
        "target": int(val),
        "default": DEFAULT_MEGA_TARGET_LINES,
        "min": MEGA_TARGET_MIN,
        "max": MEGA_TARGET_MAX,
    }


@router.put(PREFIX + "/mega-target",
            tags=["manual_translate_mega"])
def mega_set_target(pid: int, req: MegaTargetSetRequest,
                     db: Session = Depends(get_db)):
    """Cập nhật target lines/mega của project.

    Sau khi đổi, số mega cần rebuild (FE nên refresh units).
    """
    p = _get_project(db, pid)
    try:
        # Đảm bảo field tồn tại (migration tự tạo column nếu chưa)
        if hasattr(p, "mega_target_lines"):
            p.mega_target_lines = req.target
            db.commit()
            return {"ok": True, "target": req.target}
        else:
            raise HTTPException(
                500,
                "Field Project.mega_target_lines chưa migrate. "
                "Cần restart sau khi update models.py."
            )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Set target failed: {e}")
