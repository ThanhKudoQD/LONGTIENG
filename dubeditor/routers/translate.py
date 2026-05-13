"""
dubeditor/routers/translate.py
Translate API v2 — refactored hoàn toàn.

Endpoints:
  GET  /dub/api/projects/{pid}/translate/status      → trạng thái + stats
  POST /dub/api/projects/{pid}/translate/start       → chạy full pipeline (background + SSE)
  POST /dub/api/projects/{pid}/translate/run-stage   → chạy 1 stage cụ thể
  POST /dub/api/projects/{pid}/translate/cancel      → hủy
  POST /dub/api/projects/{pid}/translate/reset       → xóa Bible + Scenes
  GET  /dub/api/projects/{pid}/translate/progress    → SSE stream

  GET  /dub/api/projects/{pid}/bible                 → Bible active
  PUT  /dub/api/projects/{pid}/bible                 → edit Bible thủ công
  GET  /dub/api/projects/{pid}/bibles                → list versions

  GET  /dub/api/projects/{pid}/scenes                → list scenes
  GET  /dub/api/projects/{pid}/scenes/{scene_id}     → 1 scene + subtitles
  GET  /dub/api/projects/{pid}/story-arcs            → list arcs

  GET  /dub/api/projects/{pid}/polish-issues         → list issues
  POST /dub/api/projects/{pid}/polish-issues/{id}/apply  → apply suggested
  POST /dub/api/projects/{pid}/polish-issues/{id}/dismiss

  POST /dub/api/projects/{pid}/translate/retranslate → dịch lại 1 dòng

  GET  /dub/api/translate/genre-packs                → list packs available
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from dubeditor.database import get_db, SessionLocal
from dubeditor.models import (
    Project, Subtitle, Character,
    Bible as DBBible, Scene as DBScene, StoryArc as DBStoryArc,
    PolishIssue as DBPolishIssue,
)
from dubeditor.schemas import (
    TranslateStartRequest, TranslateStageRequest, RetranslateRequest,
    BibleOut, SceneOut, StoryArcOut, PolishIssueOut,
    TranslateStatusOut, GenrePackInfo,
)
from dubeditor.translate_service import (
    TranslateRunner, build_pipeline_config, get_available_genre_packs,
    load_active_bible_from_db, load_scenes_from_db,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── SSE infrastructure ───────────────────────────────────────────────────────

_progress_subscribers: dict[int, list[asyncio.Queue]] = {}
_active_runners: dict[int, TranslateRunner] = {}


async def _publish_progress(pid: int, stage: str, progress: float,
                             message: str, detail: Optional[dict] = None):
    """Broadcast 1 progress event tới tất cả SSE subscribers của project."""
    payload = {
        "stage": stage,
        "progress": progress,
        "message": message,
        "detail": detail or {},
    }
    msg = f"event: progress\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    for q in list(_progress_subscribers.get(pid, [])):
        try:
            await q.put(msg)
        except Exception:
            pass


async def _publish_llm_call(pid: int, payload: dict):
    """Broadcast 1 LLM call event (prompt + response) tới SSE subscribers."""
    msg = f"event: llm_call\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    for q in list(_progress_subscribers.get(pid, [])):
        try:
            await q.put(msg)
        except Exception:
            pass


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_project(db: Session, pid: int) -> Project:
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, f"Project {pid} not found")
    return p


def _db_scene_to_out(s: DBScene) -> SceneOut:
    try:
        chars = json.loads(s.characters_present or "[]")
    except json.JSONDecodeError:
        chars = []
    return SceneOut(
        id=s.id, project_id=s.project_id, scene_index=s.scene_index,
        start_line=s.start_line, end_line=s.end_line,
        start_time_sec=s.start_time_sec or 0.0, end_time_sec=s.end_time_sec or 0.0,
        location=s.location or "", time_of_day=s.time_of_day,
        characters_present=chars,
        emotion_primary=s.emotion_primary or "neutral",
        emotion_arc=s.emotion_arc or "",
        summary=s.summary or "", purpose=s.purpose or "",
        story_arc_id=s.story_arc_id,
        is_hook=bool(s.is_hook), is_emotion_peak=bool(s.is_emotion_peak),
        status=s.status or "pending", error_message=s.error_message,
        line_count=s.end_line - s.start_line + 1,
    )


def _db_bible_to_out(b: DBBible) -> BibleOut:
    return BibleOut(
        id=b.id, version=b.version, is_active=bool(b.is_active),
        cast=json.loads(b.cast_json or "{}"),
        world=json.loads(b.world_json or "{}"),
        glossary=json.loads(b.glossary_json or "{}"),
        genre_pack_id=b.genre_pack_id,
        tokens_in=b.tokens_in or 0, tokens_out=b.tokens_out or 0,
        cost_usd=b.cost_usd or 0.0, created_at=b.created_at,
    )


def _db_arc_to_out(a: DBStoryArc, scene_count: int = 0) -> StoryArcOut:
    try:
        events = json.loads(a.key_events or "[]")
    except json.JSONDecodeError:
        events = []
    return StoryArcOut(
        id=a.id, arc_index=a.arc_index, title=a.title or "",
        summary=a.summary or "", start_line=a.start_line, end_line=a.end_line,
        emotional_tone=a.emotional_tone or "",
        key_events=events, scene_count=scene_count,
    )


# ─── Status ───────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/translate/status", response_model=TranslateStatusOut)
def get_status(pid: int, db: Session = Depends(get_db)):
    """Trạng thái translate hiện tại của project."""
    p = _get_project(db, pid)

    active_bible = db.query(DBBible).filter(
        DBBible.project_id == pid,
        DBBible.is_active == True,  # noqa: E712
    ).first()

    scene_count = db.query(DBScene).filter(DBScene.project_id == pid).count()

    subs = db.query(Subtitle).filter(Subtitle.project_id == pid).all()

    # "translated" = đã được pipeline v2 dịch (KHÔNG tính text từ SRT upload ban đầu).
    # Dấu hiệu: subtitle có translation_version > 1 HOẶC có text khác original_text.
    # Cả 2 đều set bởi save_translations_to_db() trong translate_service.
    def is_translated(s: Subtitle) -> bool:
        if (s.translation_version or 1) > 1:
            return True
        # Fallback: text khác original_text (đảm bảo có dịch thật, không phải copy SRT)
        if s.text and s.original_text and s.text.strip() != s.original_text.strip():
            return True
        return False

    translated = sum(1 for s in subs if is_translated(s))
    review = sum(1 for s in subs if s.needs_review)

    # Speaker assigned = có speaker_zh hoặc character_id từ pipeline v2
    # (character_id có thể đã được gán từ Diarization cũ → ưu tiên speaker_zh)
    speaker_assigned = sum(1 for s in subs if s.speaker_zh)

    cps_vals = [s.cps_value for s in subs if s.cps_value]
    avg_cps = sum(cps_vals) / len(cps_vals) if cps_vals else 0.0

    # Tổng cost + tokens xuyên pipeline (Bible + Scenes — đại diện cho tổng)
    cost = 0.0
    tokens_in = 0
    tokens_out = 0
    for b in db.query(DBBible).filter(DBBible.project_id == pid).all():
        cost += b.cost_usd or 0.0
        tokens_in += b.tokens_in or 0
        tokens_out += b.tokens_out or 0
    for s in db.query(DBScene).filter(DBScene.project_id == pid).all():
        cost += s.cost_usd or 0.0
        tokens_in += s.tokens_in or 0
        tokens_out += s.tokens_out or 0

    return TranslateStatusOut(
        project_id=pid,
        status=p.translate_status or "idle",
        current_stage=None,
        progress=p.translate_progress or 0.0,
        has_bible=bool(active_bible),
        scene_count=scene_count,
        speaker_assigned_count=speaker_assigned,
        translated_count=translated,
        review_count=review,
        avg_cps=round(avg_cps, 2),
        cost_usd=round(cost, 4),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        error_message=p.translate_error,
    )


# ─── Pipeline control ─────────────────────────────────────────────────────────

async def _run_pipeline_background(pid: int, runner: TranslateRunner,
                                    only_stage: Optional[str] = None):
    """Chạy pipeline trong background task."""
    # Cài LLM observer cho stage riêng (run_full đã tự cài trong runner)
    if only_stage is not None:
        runner._install_llm_observer()
    try:
        if only_stage is None:
            await runner.run_full()
        else:
            # Resume mode — load state cần thiết từ DB
            if only_stage == "bible":
                await runner.run_bible()
            else:
                v2_bible = load_active_bible_from_db(runner.db, pid)
                if not v2_bible:
                    raise ValueError("Chưa có Bible. Chạy stage 'bible' trước.")

                if only_stage == "scenes":
                    await runner.run_scenes(v2_bible)
                else:
                    v2_scene_map = load_scenes_from_db(runner.db, pid)
                    if not v2_scene_map.scenes:
                        raise ValueError("Chưa có Scenes. Chạy stage 'scenes' trước.")

                    if only_stage == "speaker":
                        await runner.run_speaker(v2_bible, v2_scene_map)
                    elif only_stage == "translate":
                        # Build speaker_map từ DB
                        subs = runner.db.query(Subtitle).filter(
                            Subtitle.project_id == pid
                        ).all()
                        speaker_map = {}
                        for s in subs:
                            if s.speaker_zh:
                                speaker_map[s.index] = {
                                    "speaker_zh": s.speaker_zh,
                                    "confidence": s.speaker_confidence,
                                    "reason": s.speaker_reason or "",
                                    "speaker_vi": s.character.name if s.character else "",
                                }
                        await runner.run_translate(v2_bible, v2_scene_map, speaker_map)
                    elif only_stage == "polish":
                        await runner.run_polish(v2_bible)
                    else:
                        raise ValueError(f"Unknown stage: {only_stage}")

            # Update final status + emit "done" event để FE biết stage đã xong
            runner._save_status("done", 100.0)
            await _publish_progress(
                pid, "done", 100.0,
                f"✅ Stage '{only_stage}' hoàn tất",
                {"only_stage": only_stage,
                 "cost_usd": runner.tracker.total_cost_usd},
            )
    except asyncio.CancelledError:
        runner._save_status("idle", 0.0, error="Cancelled by user")
        await _publish_progress(pid, "cancelled", 0.0, "Đã hủy")
    except Exception as e:
        logger.error(f"[Pipeline pid={pid}] {e}", exc_info=True)
        runner._save_status("error", 0.0, error=str(e))
        await _publish_progress(
            pid, "error", 0.0, f"Lỗi: {str(e)[:200]}",
            {"error": str(e)},
        )
    finally:
        if only_stage is not None:
            runner._uninstall_llm_observer()
        _active_runners.pop(pid, None)


@router.post("/projects/{pid}/translate/start")
async def start_translate(pid: int, req: TranslateStartRequest,
                           background: BackgroundTasks,
                           db: Session = Depends(get_db)):
    """Khởi chạy full pipeline 5 stage. Chạy nền + push SSE."""
    p = _get_project(db, pid)

    subs_count = db.query(Subtitle).filter(Subtitle.project_id == pid).count()
    if subs_count == 0:
        raise HTTPException(400, "Project chưa có subtitles")

    if pid in _active_runners:
        raise HTTPException(409, "Pipeline đang chạy. Cancel trước khi start lại.")

    # SAFETY: kiểm tra original_text có thật sự là tiếng Trung không.
    # Bug cũ: nếu pipeline đã chạy 1 lần thì original_text có thể đã bị overwrite
    # với tiếng Việt (do code import_srt cũ không lưu gốc).
    # → Sample 20 dòng đầu, đếm CJK ratio.
    sample = db.query(Subtitle).filter(
        Subtitle.project_id == pid
    ).order_by(Subtitle.index).limit(20).all()
    import re as _re
    sample_text = " ".join((s.original_text or s.text or "") for s in sample)
    cjk_count = len(_re.findall(r'[\u4e00-\u9fff]', sample_text))
    text_chars = len(_re.findall(r'\S', sample_text))
    cjk_ratio = cjk_count / max(text_chars, 1)

    if cjk_ratio < 0.3:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SOURCE_NOT_CHINESE",
                "message": (
                    f"Subtitles của project này không có nội dung tiếng Trung "
                    f"(CJK ratio = {cjk_ratio*100:.1f}%, cần ≥ 30%). "
                    f"Pipeline v2 chỉ dịch Trung→Việt. "
                    f"Nếu original_text đã bị overwrite bởi pipeline chạy trước "
                    f"(bug cũ), bạn cần re-import SRT tiếng Trung gốc."
                ),
                "cjk_ratio": round(cjk_ratio, 3),
            },
        )

    # Persist project config
    p.project_type = req.project_type
    p.source_lang = req.source_lang
    p.genre_pack = req.genre_pack
    db.commit()

    # Build config
    cfg = build_pipeline_config(req)
    if not cfg.api_key:
        raise HTTPException(400, "Thiếu api_key")

    # Tạo runner với session DB MỚI (background task không share session với request)
    async def on_progress(stage: str, progress: float, message: str, detail):
        await _publish_progress(pid, stage, progress, message, detail)

    async def on_llm_call(payload: dict):
        await _publish_llm_call(pid, payload)

    bg_db = SessionLocal()
    runner = TranslateRunner(bg_db, pid, cfg, on_progress=on_progress,
                              on_llm_call=on_llm_call)
    _active_runners[pid] = runner

    async def task():
        try:
            await _run_pipeline_background(pid, runner)
        finally:
            bg_db.close()

    background.add_task(task)
    return {"ok": True, "message": "Pipeline started", "subtitles": subs_count}


@router.post("/projects/{pid}/translate/run-stage")
async def run_stage(pid: int, req: TranslateStageRequest,
                     background: BackgroundTasks,
                     db: Session = Depends(get_db)):
    """Chạy 1 stage cụ thể (resume từ state hiện tại)."""
    _get_project(db, pid)

    if pid in _active_runners:
        raise HTTPException(409, "Pipeline đang chạy")

    cfg = build_pipeline_config(req)
    if not cfg.api_key:
        raise HTTPException(400, "Thiếu api_key")

    async def on_progress(stage: str, progress: float, message: str, detail):
        await _publish_progress(pid, stage, progress, message, detail)

    async def on_llm_call(payload: dict):
        await _publish_llm_call(pid, payload)

    bg_db = SessionLocal()
    runner = TranslateRunner(bg_db, pid, cfg, on_progress=on_progress,
                              on_llm_call=on_llm_call)
    _active_runners[pid] = runner

    async def task():
        try:
            await _run_pipeline_background(pid, runner, only_stage=req.stage)
        finally:
            bg_db.close()

    background.add_task(task)
    return {"ok": True, "stage": req.stage, "message": f"Stage {req.stage} started"}


@router.post("/projects/{pid}/translate/cancel")
def cancel_translate(pid: int):
    """Hủy pipeline đang chạy."""
    runner = _active_runners.get(pid)
    if not runner:
        return {"ok": False, "message": "Không có pipeline đang chạy"}
    runner.cancel()
    return {"ok": True, "message": "Đã gửi cancel signal"}


@router.post("/projects/{pid}/translate/reset")
def reset_translate(pid: int, db: Session = Depends(get_db)):
    """Xóa Bible + Scenes + Issues, KHÔNG xóa Subtitles/Characters."""
    if pid in _active_runners:
        raise HTTPException(409, "Đang chạy, cancel trước.")

    _get_project(db, pid)

    db.query(DBPolishIssue).filter(DBPolishIssue.project_id == pid).delete()
    db.query(DBScene).filter(DBScene.project_id == pid).delete()
    db.query(DBStoryArc).filter(DBStoryArc.project_id == pid).delete()
    db.query(DBBible).filter(DBBible.project_id == pid).delete()

    # Reset subtitles
    db.query(Subtitle).filter(Subtitle.project_id == pid).update({
        "scene_id": None,
        "speaker_zh": None,
        "speaker_confidence": "low",
        "speaker_reason": "",
        "emotion": None,
        "intensity": 5,
        "cps_value": None,
        "needs_review": False,
        "review_reason": "",
        "text_draft": None,
        "is_hook": False,
    })

    p = db.query(Project).filter(Project.id == pid).first()
    if p:
        p.translate_status = "idle"
        p.translate_progress = 0.0
        p.translate_error = None

    db.commit()
    return {"ok": True, "message": "Đã reset translate state"}


# ─── SSE progress stream ──────────────────────────────────────────────────────

@router.get("/projects/{pid}/translate/progress")
async def progress_sse(pid: int):
    """SSE stream gửi progress events."""
    queue: asyncio.Queue = asyncio.Queue()
    _progress_subscribers.setdefault(pid, []).append(queue)

    async def event_gen():
        try:
            # Initial event
            yield f"event: ready\ndata: {json.dumps({'project_id': pid})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    # Heartbeat để giữ connection
                    yield ": heartbeat\n\n"
        finally:
            try:
                _progress_subscribers.get(pid, []).remove(queue)
            except ValueError:
                pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")


# ─── Bible endpoints ──────────────────────────────────────────────────────────

@router.get("/projects/{pid}/bible", response_model=Optional[BibleOut])
def get_active_bible(pid: int, db: Session = Depends(get_db)):
    """Get Bible đang active của project."""
    _get_project(db, pid)
    bible = db.query(DBBible).filter(
        DBBible.project_id == pid,
        DBBible.is_active == True,  # noqa: E712
    ).first()
    if not bible:
        return None
    return _db_bible_to_out(bible)


@router.put("/projects/{pid}/bible")
def update_bible(pid: int, payload: dict, db: Session = Depends(get_db)):
    """Edit Bible (cast/world/glossary) thủ công.

    Body: {"cast": {...}, "world": {...}, "glossary": {...}}
    Bất kỳ trường nào không truyền sẽ giữ nguyên.
    """
    _get_project(db, pid)
    bible = db.query(DBBible).filter(
        DBBible.project_id == pid,
        DBBible.is_active == True,  # noqa: E712
    ).first()
    if not bible:
        raise HTTPException(404, "Chưa có Bible. Chạy Stage 1 trước.")

    if "cast" in payload:
        bible.cast_json = json.dumps(payload["cast"], ensure_ascii=False)
    if "world" in payload:
        bible.world_json = json.dumps(payload["world"], ensure_ascii=False)
    if "glossary" in payload:
        bible.glossary_json = json.dumps(payload["glossary"], ensure_ascii=False)
    if "genre_pack_id" in payload:
        bible.genre_pack_id = payload["genre_pack_id"]

    db.commit()
    db.refresh(bible)
    return _db_bible_to_out(bible)


@router.get("/projects/{pid}/bibles", response_model=list[BibleOut])
def list_bible_versions(pid: int, db: Session = Depends(get_db)):
    """List tất cả Bible versions của project (xem lịch sử)."""
    _get_project(db, pid)
    bibles = db.query(DBBible).filter(
        DBBible.project_id == pid
    ).order_by(DBBible.version.desc()).all()
    return [_db_bible_to_out(b) for b in bibles]


# ─── Scenes endpoints ─────────────────────────────────────────────────────────

@router.get("/projects/{pid}/scenes", response_model=list[SceneOut])
def list_scenes(pid: int, db: Session = Depends(get_db)):
    """List tất cả scenes của project."""
    _get_project(db, pid)
    scenes = db.query(DBScene).filter(
        DBScene.project_id == pid
    ).order_by(DBScene.scene_index).all()
    return [_db_scene_to_out(s) for s in scenes]


@router.get("/projects/{pid}/scenes/{scene_id}")
def get_scene_detail(pid: int, scene_id: int, db: Session = Depends(get_db)):
    """Get 1 scene chi tiết + subtitles trong scene."""
    _get_project(db, pid)
    scene = db.query(DBScene).filter(
        DBScene.id == scene_id, DBScene.project_id == pid
    ).first()
    if not scene:
        raise HTTPException(404, "Scene not found")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index >= scene.start_line,
        Subtitle.index <= scene.end_line,
    ).order_by(Subtitle.index).all()

    return {
        "scene": _db_scene_to_out(scene),
        "subtitles": [
            {
                "id": s.id, "index": s.index,
                "start_time": s.start_time, "end_time": s.end_time,
                "text_zh": s.original_text or "",
                "text_vi": s.text or "",
                "speaker_zh": s.speaker_zh,
                "speaker_vi": s.character.name if s.character else None,
                "speaker_confidence": s.speaker_confidence or "low",
                "speaker_reason": s.speaker_reason or "",
                "emotion": s.emotion, "intensity": s.intensity or 5,
                "cps_value": s.cps_value,
                "needs_review": bool(s.needs_review),
                "review_reason": s.review_reason or "",
                "character_id": s.character_id,
                "is_hook": bool(s.is_hook),
            } for s in subs
        ],
    }


@router.get("/projects/{pid}/story-arcs", response_model=list[StoryArcOut])
def list_story_arcs(pid: int, db: Session = Depends(get_db)):
    """List story arcs."""
    _get_project(db, pid)
    arcs = db.query(DBStoryArc).filter(
        DBStoryArc.project_id == pid
    ).order_by(DBStoryArc.arc_index).all()

    # Đếm scenes/arc
    scene_count_by_arc: dict[int, int] = {}
    for s in db.query(DBScene).filter(DBScene.project_id == pid).all():
        if s.story_arc_id:
            scene_count_by_arc[s.story_arc_id] = scene_count_by_arc.get(s.story_arc_id, 0) + 1

    return [_db_arc_to_out(a, scene_count_by_arc.get(a.id, 0)) for a in arcs]


# ─── Polish issues ────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/polish-issues", response_model=list[PolishIssueOut])
def list_polish_issues(pid: int,
                        resolved: Optional[bool] = None,
                        issue_type: Optional[str] = None,
                        db: Session = Depends(get_db)):
    """List polish issues, có thể filter theo resolved/type."""
    _get_project(db, pid)
    q = db.query(DBPolishIssue).filter(DBPolishIssue.project_id == pid)
    if resolved is not None:
        q = q.filter(DBPolishIssue.resolved == resolved)
    if issue_type:
        q = q.filter(DBPolishIssue.issue_type == issue_type)
    return q.order_by(DBPolishIssue.line_index).all()


@router.post("/projects/{pid}/polish-issues/{issue_id}/apply")
def apply_issue_suggestion(pid: int, issue_id: int,
                            db: Session = Depends(get_db)):
    """Apply suggested_text vào subtitle, đánh dấu issue resolved."""
    _get_project(db, pid)
    iss = db.query(DBPolishIssue).filter(
        DBPolishIssue.id == issue_id,
        DBPolishIssue.project_id == pid,
    ).first()
    if not iss:
        raise HTTPException(404, "Issue not found")

    if iss.suggested_text and iss.subtitle_id:
        sub = db.query(Subtitle).filter(Subtitle.id == iss.subtitle_id).first()
        if sub:
            sub.text = iss.suggested_text
            duration = sub.end_time - sub.start_time
            from core.srt_parser import calculate_cps
            if duration > 0:
                sub.cps_value = round(calculate_cps(iss.suggested_text, duration), 2)

    iss.resolved = True
    db.commit()
    return {"ok": True}


@router.post("/projects/{pid}/polish-issues/{issue_id}/dismiss")
def dismiss_issue(pid: int, issue_id: int, db: Session = Depends(get_db)):
    """Bỏ qua issue, không apply."""
    _get_project(db, pid)
    iss = db.query(DBPolishIssue).filter(
        DBPolishIssue.id == issue_id,
        DBPolishIssue.project_id == pid,
    ).first()
    if not iss:
        raise HTTPException(404, "Issue not found")
    iss.resolved = True
    db.commit()
    return {"ok": True}


# ─── Retranslate 1 dòng ───────────────────────────────────────────────────────

@router.post("/projects/{pid}/translate/retranslate")
async def retranslate_single(pid: int, req: RetranslateRequest,
                              db: Session = Depends(get_db)):
    """Dịch lại 1 subtitle. Dùng Bible + scene context."""
    _get_project(db, pid)
    sub = db.query(Subtitle).filter(
        Subtitle.id == req.subtitle_id,
        Subtitle.project_id == pid,
    ).first()
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    bible = load_active_bible_from_db(db, pid)
    if not bible:
        raise HTTPException(400, "Project chưa có Bible. Chạy Stage 1 trước.")

    # Build prompt đơn giản
    from core.llm_client import LLMRequest, call_llm
    import httpx

    bible_brief = {
        "characters": [
            {"vi": c.vi, "zh": c.zh, "self_address": c.self_address.default}
            for c in bible.cast.characters[:8]
        ],
        "glossary": [
            {"zh": t.zh, "vi": t.vi}
            for t in bible.glossary.terms[:15]
        ],
        "tone": bible.world.tone_overall,
    }

    # Context: 3 dòng trước/sau
    ctx_before = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index < sub.index,
    ).order_by(Subtitle.index.desc()).limit(3).all()
    ctx_after = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index > sub.index,
    ).order_by(Subtitle.index).limit(3).all()

    ctx_block = "\n".join([
        *[f"  [{s.index}] {s.original_text or ''} → {s.text or ''}" for s in reversed(ctx_before)],
        f"→ [{sub.index}] {sub.original_text or ''} → {sub.text or ''}",
        *[f"  [{s.index}] {s.original_text or ''} → {s.text or ''}" for s in ctx_after],
    ])

    prompt = f"""Dịch lại 1 dòng phụ đề Trung→Việt cho phim đang dịch.

NGUYÊN BẢN (Trung): {sub.original_text}
BẢN HIỆN TẠI (Việt): {sub.text}
YÊU CẦU NGƯỜI DÙNG: {req.hint or "Dịch tốt hơn, giữ cảm xúc"}

THÔNG TIN PHIM:
{json.dumps(bible_brief, ensure_ascii=False, indent=2)}

MẠCH HỘI THOẠI:
{ctx_block}

Yêu cầu output: TRẢ VỀ JSON THUẦN với {req.variants} variants:
{{
  "variants": [
    {{"text_vi": "<bản dịch 1>"}},
    {{"text_vi": "<bản dịch 2>"}}
  ]
}}

Chỉ JSON, không markdown, không giải thích."""

    llm_req = LLMRequest(
        prompt=prompt, model=req.model, api_key=req.api_key,
        temperature=0.7, max_output=2000, json_mode=True,
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await call_llm(llm_req, client=client)
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    from core.llm_client import parse_json_response
    data = parse_json_response(resp.text, default={"variants": []})

    return {
        "ok": True,
        "subtitle_id": sub.id,
        "current_text": sub.text,
        "variants": [v.get("text_vi", "") for v in data.get("variants", [])],
        "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out,
    }


# ─── Genre packs ──────────────────────────────────────────────────────────────

@router.get("/translate/genre-packs", response_model=list[GenrePackInfo])
def list_genre_packs():
    """List các genre pack có sẵn cho FE chọn."""
    return get_available_genre_packs()