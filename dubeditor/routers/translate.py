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
    Chunk as DBChunk,
    PolishIssue as DBPolishIssue,
    LLMCall as DBLLMCall,
    PipelineEvent as DBPipelineEvent,
)
from dubeditor.schemas import (
    TranslateStartRequest, TranslateStageRequest, RetranslateRequest,
    RetranslateBatchRequest, RetranslateBatchResponse, RetranslateBatchLineOut,
    SelectVariantRequest,
    BibleOut, SceneOut, StoryArcOut, PolishIssueOut, ChunkOut,
    TranslateStatusOut,
    CleanedSubtitleOut,
    ScanResultOut, SuspiciousLineOut,
    Stage0RunResultOut,
)
from dubeditor.translate_service import (
    TranslateRunner, build_pipeline_config,
    load_active_bible_from_db,
)
from dubeditor.llm_log_service import (
    save_llm_call, save_pipeline_event,
    load_llm_calls, load_pipeline_events,
    clear_logs,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── SSE infrastructure ───────────────────────────────────────────────────────

_progress_subscribers: dict[int, list[asyncio.Queue]] = {}
_active_runners: dict[int, TranslateRunner] = {}


async def _publish_progress(pid: int, stage: str, progress: float,
                             message: str, detail: Optional[dict] = None):
    """Broadcast 1 progress event tới tất cả SSE subscribers của project.

    v3.9: persist event vào DB TRƯỚC khi broadcast → F5 / reopen Editor vẫn còn log.
    """
    # Persist trước — best effort, không block broadcast nếu DB lỗi
    try:
        db = SessionLocal()
        try:
            save_pipeline_event(db, pid, stage, progress, message, detail)
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[_publish_progress] persist failed: {e}")

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
    """Broadcast 1 LLM call event (prompt + response) tới SSE subscribers.

    v3.9: persist call vào DB TRƯỚC khi broadcast.
    """
    try:
        db = SessionLocal()
        try:
            save_llm_call(db, pid, payload)
        finally:
            db.close()
    except Exception as e:
        logger.debug(f"[_publish_llm_call] persist failed: {e}")

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
        chunk_id=s.chunk_id,  # v3
        is_hook=bool(s.is_hook), is_emotion_peak=bool(s.is_emotion_peak),
        status=s.status or "pending", error_message=s.error_message,
        line_count=s.end_line - s.start_line + 1,
    )


def _db_chunk_to_out(c: DBChunk, scene_count: int = 0,
                    arc_title: str = "", arc_tone: str = "") -> ChunkOut:
    return ChunkOut(
        id=c.id,
        project_id=c.project_id,
        arc_index=c.arc_index,
        chunk_index=c.chunk_index,
        title=c.title or "",
        start_line=c.start_line,
        end_line=c.end_line,
        status=c.status or "pending",
        line_count=c.end_line - c.start_line + 1,
        scene_count=scene_count,
        arc_title=arc_title,
        arc_tone=arc_tone,
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

    chunk_count = db.query(DBChunk).filter(DBChunk.project_id == pid).count()
    scene_count = db.query(DBScene).filter(DBScene.project_id == pid).count()

    subs = db.query(Subtitle).filter(Subtitle.project_id == pid).all()

    def is_translated(s: Subtitle) -> bool:
        # v3: chỉ tính là đã dịch khi có text_v1 (bản dịch Việt thật sự từ Stage 4)
        # KHÔNG dùng `text` vì cột này có thể chứa original TQ lúc import.
        if s.text_v1 and s.text_v1.strip():
            return True
        return False

    # v3.2: Stage 0 stats
    cleaned_count = sum(1 for s in subs if getattr(s, "is_cleaned", False))
    # removed_count = số dòng đã bị Stage 0 xóa khỏi DB (log riêng)
    from dubeditor.models import RemovedSubtitle
    removed_count = db.query(RemovedSubtitle).filter(
        RemovedSubtitle.project_id == pid
    ).count()

    # Tất cả subtitle hiện tại đều cần dịch (Stage 0 đã xóa noise rồi)
    translated = sum(1 for s in subs if is_translated(s))
    variants = sum(1 for s in subs if s.text_v2 and s.text_v2.strip())
    review = sum(1 for s in subs if s.needs_review)
    speaker_assigned = sum(1 for s in subs if s.speaker_zh)

    cps_vals = [s.cps_value for s in subs if s.cps_value]
    avg_cps = sum(cps_vals) / len(cps_vals) if cps_vals else 0.0

    # Tổng cost + tokens
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

    # v3.9: Resume — xác định stage tiếp theo cần chạy
    # Logic: dựa vào artifacts có sẵn trong DB, không phải translate_status string
    # (vì status có thể là 'cancelled' hoặc 'error' khi dở dang)
    next_stage = None
    can_resume = False
    is_running_now = (p.translate_status == "running")

    if not is_running_now:
        # Đếm xem stage nào đã có data:
        has_bible_done = bool(active_bible)
        has_chunks_done = chunk_count > 0
        has_speaker_done = speaker_assigned > 0
        has_translate_done = translated > 0

        # Xác định stage tiếp theo (chronological order)
        # Stage 0 normalize không tính vào resume — luôn rerun đầu pipeline
        if not has_bible_done:
            next_stage = "bible"
        elif not has_chunks_done:
            next_stage = "chunks"
        elif not has_speaker_done:
            next_stage = "speaker"
        elif not has_translate_done:
            next_stage = "translate"
        else:
            # Tất cả đã xong → không có gì resume
            next_stage = None

        # can_resume = đang dở giữa pipeline (có ít nhất 1 stage xong, chưa xong hết)
        any_done = has_bible_done or has_chunks_done or has_speaker_done or has_translate_done
        all_done = (has_bible_done and has_chunks_done and
                    has_speaker_done and has_translate_done)
        can_resume = any_done and (not all_done)

    return TranslateStatusOut(
        project_id=pid,
        status=p.translate_status or "idle",
        current_stage=None,
        progress=p.translate_progress or 0.0,
        has_bible=bool(active_bible),
        chunk_count=chunk_count,
        scene_count=scene_count,
        speaker_assigned_count=speaker_assigned,
        translated_count=translated,
        variants_count=variants,
        review_count=review,
        avg_cps=round(avg_cps, 2),
        cost_usd=round(cost, 4),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        error_message=p.translate_error,
        cleaned_count=cleaned_count,
        removed_count=removed_count,
        next_stage=next_stage,
        can_resume=can_resume,
    )


# ─── Stage 0 — Cleaned subtitles ─────────────────────────────────────────────

@router.get("/projects/{pid}/translate/normalize/cleaned",
            response_model=list[CleanedSubtitleOut])
def get_cleaned_subtitles(pid: int, db: Session = Depends(get_db)):
    """Danh sách subtitles đã được Stage 0 xử lý.

    Trả về 2 nguồn:
    - Subtitle còn trong DB có is_cleaned=True → "clean" (đã sửa text)
    - RemovedSubtitle log → "remove" (đã bị xóa khỏi DB)
    """
    from dubeditor.models import RemovedSubtitle

    _get_project(db, pid)
    result = []

    # 1. Dòng đã clean (còn trong DB)
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.is_cleaned == True,
    ).order_by(Subtitle.index).all()

    for s in subs:
        result.append(CleanedSubtitleOut(
            id=s.id,
            index=s.index,
            start_time=s.start_time,
            end_time=s.end_time,
            original_raw=s.original_raw,
            current_text=s.original_text or "",
            is_noise=False,
            clean_reason=s.clean_reason,
            action="clean",
        ))

    # 2. Dòng đã remove (log RemovedSubtitle, không còn trong subtitles)
    removed = db.query(RemovedSubtitle).filter(
        RemovedSubtitle.project_id == pid,
    ).order_by(RemovedSubtitle.original_index).all()

    for r in removed:
        # Dùng negative id để FE phân biệt với clean (id = -removed_id)
        result.append(CleanedSubtitleOut(
            id=-r.id,
            index=r.original_index,
            start_time=r.start_time,
            end_time=r.end_time,
            original_raw=r.original_text,
            current_text="",
            is_noise=True,
            clean_reason=r.clean_reason,
            action="remove",
        ))

    # Sắp xếp theo index gốc
    result.sort(key=lambda x: x.index)
    return result


@router.get("/projects/{pid}/translate/normalize/scan",
            response_model=ScanResultOut)
def scan_suspicious_lines(pid: int, db: Session = Depends(get_db)):
    """Quét heuristic tìm dòng nghi ngờ — KHÔNG gọi AI, KHÔNG ghi DB.

    Trả về danh sách dòng nghi ngờ + lý do flag để user xem trước khi gửi AI.
    """
    _get_project(db, pid)

    # Import scanner trực tiếp (không qua TranslateRunner để khỏi đụng config)
    import sys
    from pathlib import Path
    repo_root = Path(__file__).resolve().parent.parent.parent
    if str(repo_root / "srt_translator_v2") not in sys.path:
        sys.path.insert(0, str(repo_root / "srt_translator_v2"))
    from core.suspicious_scanner import scan_suspicious
    from core.srt_parser import SrtEntry
    from stages.stage0_normalize import build_data_lines

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid
    ).order_by(Subtitle.index).all()
    if not subs:
        return ScanResultOut(
            total_lines=0,
            suspicious_count=0,
            cluster_count=0,
            suspicious_lines=[],
        )

    # Build entries từ DB
    entries = [
        SrtEntry(
            index=s.index,
            start_sec=s.start_time,
            end_sec=s.end_time,
            text=s.original_text or "",
        )
        for s in subs
    ]

    # Scan
    flags = scan_suspicious(entries)

    # Estimate số dòng sẽ gửi AI (suspicious + ±2 context, dedup)
    _, lines_to_send = build_data_lines(entries, flags, context_window=2)

    return ScanResultOut(
        total_lines=len(entries),
        suspicious_count=len(flags),
        cluster_count=lines_to_send,  # nay là số dòng sẽ gửi AI (sau dedup)
        suspicious_lines=[
            SuspiciousLineOut(
                index=f.line_index,
                text=f.text,
                reasons=f.reasons,
            )
            for f in flags
        ],
    )


@router.post("/projects/{pid}/translate/normalize/run",
             response_model=Stage0RunResultOut)
async def run_normalize_sync(pid: int, req: TranslateStartRequest,
                              db: Session = Depends(get_db)):
    """Chạy Stage 0 SYNC — đợi xong rồi trả kết quả.

    Khác với /run-stage (chạy background), endpoint này:
    - Chạy ngay trong request
    - Trả về kết quả Stage 0 (counts, cost)
    - FE chỉ cần await 1 lần, không phải poll
    """
    _get_project(db, pid)

    # Build config, ép stage0_enabled=True
    config = build_pipeline_config(req)
    config.stage0.enabled = True

    runner = TranslateRunner(db, pid, config)
    runner._install_llm_observer()
    try:
        report = await runner.run_normalize()
    except Exception as e:
        logger.error(f"[Stage 0 sync] failed: {e}", exc_info=True)
        runner._save_status("idle", 0.0, error=str(e))
        raise HTTPException(500, f"Lỗi Stage 0: {str(e)[:200]}")
    finally:
        runner._uninstall_llm_observer()

    # Status về idle sau khi xong (KHÔNG phải done — chỉ stage riêng)
    runner._save_status("idle", 0.0)

    return Stage0RunResultOut(
        total_lines=report.total_lines,
        suspicious_count=report.suspicious_count,
        cluster_count=report.context_lines_sent,  # số dòng đã gửi AI
        removed_count=report.removed,
        cleaned_count=report.cleaned,
        kept_count=report.kept,
        cost_usd=round(runner.tracker.total_cost_usd, 4),
        tokens_in=runner.tracker.total_tokens_in,
        tokens_out=runner.tracker.total_tokens_out,
    )


@router.post("/projects/{pid}/translate/normalize/revert/{subtitle_id}")
def revert_cleaned_subtitle(pid: int, subtitle_id: int, db: Session = Depends(get_db)):
    """Hoàn tác 1 dòng đã bị Stage 0 xử lý.

    Nếu subtitle_id > 0 → dòng đã clean (còn trong DB) → khôi phục original_raw
    Nếu subtitle_id < 0 → dòng đã remove (id = -removed_subtitle.id) →
                          insert lại + reindex tất cả
    """
    from dubeditor.models import RemovedSubtitle

    _get_project(db, pid)

    # Trường hợp 1: revert clean (id dương)
    if subtitle_id > 0:
        sub = db.query(Subtitle).filter(
            Subtitle.id == subtitle_id,
            Subtitle.project_id == pid,
        ).first()
        if not sub:
            raise HTTPException(404, "Subtitle not found")
        if not sub.is_cleaned or not sub.original_raw:
            raise HTTPException(400, "Subtitle chưa được Stage 0 xử lý")

        sub.original_text = sub.original_raw
        sub.is_cleaned = False
        sub.clean_reason = None
        sub.original_raw = None
        db.commit()
        return {"ok": True, "subtitle_id": subtitle_id, "action": "restored_clean"}

    # Trường hợp 2: revert remove (id âm = -removed.id)
    removed_id = -subtitle_id
    removed = db.query(RemovedSubtitle).filter(
        RemovedSubtitle.id == removed_id,
        RemovedSubtitle.project_id == pid,
    ).first()
    if not removed:
        raise HTTPException(404, "RemovedSubtitle not found")

    # Reset chunks/scenes (vì index sẽ shift sau khi insert)
    from dubeditor.models import Scene as DBScene, Chunk as DBChunk
    db.query(DBScene).filter(DBScene.project_id == pid).delete()
    db.query(DBChunk).filter(DBChunk.project_id == pid).delete()

    # Insert dòng mới vào vị trí original_index (hoặc cuối nếu vượt range)
    target_idx = removed.original_index
    # Shift các dòng có index >= target_idx lên 1
    db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index >= target_idx,
    ).update({Subtitle.index: Subtitle.index + 1}, synchronize_session=False)

    # Insert dòng đã xóa
    new_sub = Subtitle(
        project_id=pid,
        index=target_idx,
        start_time=removed.start_time,
        end_time=removed.end_time,
        original_text=removed.original_text,
        text="",
        is_cleaned=False,
        original_raw=None,
        clean_reason=None,
    )
    db.add(new_sub)

    # Xóa log
    db.delete(removed)

    # Reindex liên tục để đảm bảo không có gap.
    # v3.9 perf: bulk_update_mappings thay vì load 6000 ORM + commit từng UPDATE.
    db.commit()
    remaining_rows = (
        db.query(Subtitle.id, Subtitle.index)
        .filter(Subtitle.project_id == pid)
        .order_by(Subtitle.index)
        .all()
    )
    mappings = []
    for new_idx, (sub_id, old_idx) in enumerate(remaining_rows, start=1):
        if old_idx != new_idx:
            mappings.append({"id": sub_id, "index": new_idx})
    if mappings:
        db.bulk_update_mappings(Subtitle, mappings)

    # Cập nhật subtitle_count — gộp commit chung
    from dubeditor.models import Project
    project = db.query(Project).filter(Project.id == pid).first()
    if project:
        project.subtitle_count = len(remaining_rows)
    db.commit()

    return {"ok": True, "subtitle_id": subtitle_id, "action": "restored_removed"}


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
            # Resume mode — run_stage() trong TranslateRunner đã tự load state từ DB
            # qua load_active_bible_from_db + đọc chunks/scenes từ DB khi cần.
            # Map "scenes" → "chunks" (alias cho backwards compat).
            stage_alias = {"scenes": "chunks"}.get(only_stage, only_stage)
            await runner.run_stage(stage_alias)

            # Sau khi 1 stage xong → status = "idle" (KHÔNG phải "done" cho cả pipeline)
            # "done" chỉ áp dụng khi run_full() chạy đủ Stage 0-4.
            runner._save_status("idle", 0.0)
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
    """Xóa Bible + Chunks + Scenes + Issues. KHÔNG xóa Subtitles/Characters.
    
    Reset Subtitles về trạng thái pre-pipeline (clear v3 variants).
    """
    if pid in _active_runners:
        raise HTTPException(409, "Đang chạy, cancel trước.")

    _get_project(db, pid)

    db.query(DBPolishIssue).filter(DBPolishIssue.project_id == pid).delete()
    db.query(DBScene).filter(DBScene.project_id == pid).delete()
    db.query(DBChunk).filter(DBChunk.project_id == pid).delete()  # v3
    db.query(DBStoryArc).filter(DBStoryArc.project_id == pid).delete()
    db.query(DBBible).filter(DBBible.project_id == pid).delete()

    # Reset subtitles (clear v2 + v3 fields)
    db.query(Subtitle).filter(Subtitle.project_id == pid).update({
        "scene_id": None,
        "chunk_id": None,             # v3
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
        # v3: clear variants
        "text_v1": None,
        "text_v2": None,
        "variant_selected": 1,
    })

    p = db.query(Project).filter(Project.id == pid).first()
    if p:
        p.translate_status = "idle"
        p.translate_progress = 0.0
        p.translate_error = None

    # v3.9: Reset = full clean → xóa log cũ luôn (Cancel KHÔNG xóa)
    clear_logs(db, pid)

    db.commit()
    return {"ok": True, "message": "Đã reset translate state"}


# ─── v3.9: Persistent logs (events + LLM calls) ──────────────────────────────

@router.get("/projects/{pid}/translate/events")
def list_events(pid: int, limit: int = 500, db: Session = Depends(get_db)):
    """List pipeline events đã persist. Trả từ cũ → mới (asc) để FE append dễ.

    Dùng khi FE mount TranslatePage sau F5 → restore log cũ trước khi SSE chạy.
    """
    rows = load_pipeline_events(db, pid, limit=limit)
    out = []
    for r in rows:
        try:
            detail = json.loads(r.detail_json) if r.detail_json else None
        except Exception:
            detail = None
        out.append({
            "id": r.id,
            "created_at": r.created_at,
            "stage": r.stage,
            "progress": r.progress or 0.0,
            "message": r.message,
            "detail": detail,
        })
    return out


@router.get("/projects/{pid}/translate/llm-calls")
def list_llm_calls_endpoint(pid: int, limit: int = 200, db: Session = Depends(get_db)):
    """List LLM calls đã persist (cũ → mới)."""
    rows = load_llm_calls(db, pid, limit=limit)
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "created_at": r.created_at,
            "stage_tag": r.stage_tag,
            "provider": r.provider,
            "model": r.model,
            "attempt": r.attempt or 1,
            "tokens_in": r.tokens_in or 0,
            "tokens_out": r.tokens_out or 0,
            "cached_tokens": r.cached_tokens or 0,
            "timing_ms": r.timing_ms or 0,
            "temperature": r.temperature or 0.0,
            "json_mode": bool(r.json_mode),
            "thinking": r.thinking,
            "finish_reason": r.finish_reason,
            "error": r.error,
            "prompt_full": r.prompt_full,
            "response_full": r.response_full,
            # alias cho FE LLMCallMessage shape (SSE dùng prompt_preview/response_preview)
            "prompt_preview": (r.prompt_full or "")[:2000] if r.prompt_full else None,
            "response_preview": (r.response_full or "")[:2000] if r.response_full else None,
            "prompt_length": len(r.prompt_full or ""),
            "response_length": len(r.response_full or ""),
            "ok": not bool(r.error),
            "call_idx": r.id,  # dùng id làm idx khi load từ DB
        })
    return out


@router.delete("/projects/{pid}/translate/logs")
def clear_logs_endpoint(pid: int, db: Session = Depends(get_db)):
    """Xóa toàn bộ pipeline events + LLM calls của project (user bấm Clear logs)."""
    clear_logs(db, pid)
    return {"ok": True, "message": "Đã xóa logs"}


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
    """Dịch lại 1 subtitle, TRẢ 2 BẢN v1 (sát nghĩa) + v2 (thoát ý)."""
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

    # Build prompt
    from core.llm_client import LLMRequest, call_llm, parse_json_response
    import httpx

    # Tìm speaker info
    speaker_vi = "?"
    rel_info = "(không có thông tin)"
    if sub.speaker_zh:
        ch = bible.cast.get_by_zh(sub.speaker_zh)
        if ch:
            speaker_vi = ch.vi
            rel_pairs = []
            for other_zh, rel in (ch.rel or {}).items():
                other_ch = bible.cast.get_by_zh(other_zh)
                other_vi = other_ch.vi if other_ch else other_zh
                rel_pairs.append(f"- với {other_vi}: {rel}")
            if rel_pairs:
                rel_info = "\n".join(rel_pairs)

    # Glossary terms có trong text
    relevant_terms = bible.glossary.find_in_text(sub.original_text or "")
    gloss_block = "\n".join(
        f"- {t.zh} → \"{t.vi}\"" for t in relevant_terms
    ) or "(Không có)"

    # Top cast brief
    cast_brief = "\n".join(
        f"- {c.vi} ({c.zh}): {c.g}, {c.role}, {c.char}"
        for c in bible.cast.characters[:10]
    )

    # Context N dòng trước/sau (v3.5: configurable, default 2, cap 5)
    ctx_n = max(1, min(5, getattr(req, "context_window", 2) or 2))
    ctx_before = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index < sub.index,
    ).order_by(Subtitle.index.desc()).limit(ctx_n).all()
    ctx_after = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index > sub.index,
    ).order_by(Subtitle.index).limit(ctx_n).all()

    ctx_block = "\n".join([
        *[f"  [{s.index}] {s.speaker_zh or '?'} | {s.original_text or ''} → {s.text or ''}"
          for s in reversed(ctx_before)],
        f"  → [{sub.index}] {sub.speaker_zh or '?'} | {sub.original_text or ''} (cần dịch)",
        *[f"  [{s.index}] {s.speaker_zh or '?'} | {s.original_text or ''} → {s.text or ''}"
          for s in ctx_after],
    ])

    duration = max(0.01, (sub.end_time or 0) - (sub.start_time or 0))

    # v3.6: Inject Genre Pack đồng bộ Stage 4
    from stages.stage4_translate import load_genre_pack, format_genre_pack_for_prompt
    from config import default_config as _dft_cfg
    _dummy_cfg = _dft_cfg()
    genre_pack = load_genre_pack(bible.world.genre_id, _dummy_cfg)
    genre_pack_str = format_genre_pack_for_prompt(genre_pack)

    prompt = f"""Dịch lại 1 dòng phụ đề TQ→Việt cho lồng tiếng C-drama.

━━━ THÔNG TIN PHIM ━━━
Thể loại: {', '.join(bible.world.genre)}
Tone: {bible.world.tone}
Era: {bible.world.era}

━━━ NHÂN VẬT CHÍNH ━━━
{cast_brief}

━━━ SPEAKER DÒNG NÀY ━━━
{speaker_vi} (TQ: {sub.speaker_zh or '?'})

QUAN HỆ:
{rel_info}

━━━ GLOSSARY ━━━
{gloss_block}

━━━ GENRE PACK ━━━
{genre_pack_str}

━━━ MẠCH HỘI THOẠI (chỉ tham khảo, KHÔNG dịch) ━━━
{ctx_block}

━━━ DÒNG CẦN DỊCH ━━━
Original TQ: {sub.original_text or ''}
Hiện tại VI: {sub.text or '(chưa có)'}
Duration: {duration:.1f}s
Emotion: {sub.emotion or 'neutral'}, intensity: {sub.intensity or 5}

━━━ YÊU CẦU NGƯỜI DÙNG ━━━
{req.hint or "Dịch lại tốt hơn, giữ cảm xúc"}

━━━ NGUYÊN TẮC DỊCH ━━━

1. ĐÚNG NGHĨA + HIỂU CỤM SUB:
   - Phụ đề TQ thường bị cắt theo nhịp hơi thở, 1 câu dài có thể bị cắt 2-4 sub
   - Cấu trúc TQ và VN NGƯỢC NHAU (TQ: bổ ngữ TRƯỚC danh từ; VN: bổ ngữ SAU)
   - Đọc context trước/sau để hiểu trọn ý câu gốc, KHÔNG ép thành câu trọn riêng
     nếu nó là mảnh của câu dài
   - Nếu dòng này thuộc cụm, ĐỀ XUẤT user dùng "Dịch lại cả cụm" để chuẩn hơn

2. TỰ NHIÊN — câu Việt mượt, không "mùi dịch"

3. ĐÚNG TONE + NHÂN VẬT — xưng hô theo quan hệ + emotion + Genre Pack
   CẤM TUYỆT ĐỐI:
   ✗ "con-mẹ/bố" nếu KHÔNG có huyết thống trong quan hệ
   ✗ "anh-em" cho 2 nữ (trừ chị em ruột → "chị-em")
   ✗ "anh-em" cho 2 nam (dùng "tôi-cậu" / cổ trang "huynh-đệ")
   ✗ Xưng hô cổ trang trong phim hiện đại (không "tại hạ", "thiếp")
   ✗ "ngài" cho người thân (vợ chồng, anh chị em)

4. ĐÚNG VĂN HÓA — thành ngữ TQ → tương đương VN, văn phong khớp era

5. LỒNG TIẾNG: câu tròn, đủ chủ ngữ (cho TTS), KHÔNG cụt cộc 1-2 từ

━━━ NHIỆM VỤ ━━━
Trả 2 BẢN DỊCH KHÁC NHAU:
- text_v1: SÁT NGHĨA — dịch sát từng phần ý, giữ cấu trúc TQ, phù hợp subtitle
- text_v2: THOÁT Ý — dịch theo cách người Việt nói tự nhiên, phù hợp lồng tiếng

OUTPUT JSON THUẦN:
{{
  "text_v1": "...",
  "text_v2": "...",
  "emotion": "neutral|happy|sad|angry|cold|tense|intimate|fearful|sarcastic|shocked|determined|regretful|humorous|threatening",
  "intensity": 1-10
}}"""

    llm_req = LLMRequest(
        prompt=prompt, model=req.model, api_key=req.api_key,
        temperature=0.5, max_output=2000, json_mode=True,
        # v3.3: forward thinking toggle từ FE (None = dùng default của model)
        thinking=req.thinking,
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await call_llm(llm_req, client=client)
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    data = parse_json_response(resp.text, default={})

    text_v1 = (data.get("text_v1") or "").strip()
    text_v2 = (data.get("text_v2") or "").strip()
    emotion = data.get("emotion")
    intensity = data.get("intensity")

    return {
        "ok": True,
        "subtitle_id": sub.id,
        "current_text_v1": sub.text_v1,
        "current_text_v2": sub.text_v2,
        "new_text_v1": text_v1,
        "new_text_v2": text_v2 if text_v2 != text_v1 else None,
        "emotion": emotion,
        "intensity": intensity,
        "tokens_in": resp.tokens_in,
        "tokens_out": resp.tokens_out,
    }


# ─── v3.6: Retranslate BATCH (1-5 dòng) ──────────────────────────────────────

@router.post("/projects/{pid}/translate/retranslate-batch",
             response_model=RetranslateBatchResponse)
async def retranslate_batch(pid: int, req: RetranslateBatchRequest,
                             db: Session = Depends(get_db)):
    """Dịch lại 1-5 dòng cùng lúc.

    Dùng khi user muốn sửa cả cụm sub liền mạch (tránh 1 dòng đơn ra rác nghĩa).
    Prompt đồng bộ Stage 4: cụm sub liền mạch + Genre Pack + CẤM xưng hô.
    """
    _get_project(db, pid)

    # Validate ids
    if not req.subtitle_ids:
        raise HTTPException(400, "subtitle_ids rỗng")
    if len(req.subtitle_ids) > 5:
        raise HTTPException(400, "Tối đa 5 dòng/lần (cap để tránh prompt quá dài)")

    subs = db.query(Subtitle).filter(
        Subtitle.id.in_(req.subtitle_ids),
        Subtitle.project_id == pid,
    ).order_by(Subtitle.index).all()
    if not subs:
        raise HTTPException(404, "Không tìm thấy subtitle nào")

    bible = load_active_bible_from_db(db, pid)
    if not bible:
        raise HTTPException(400, "Project chưa có Bible. Chạy Stage 1 trước.")

    from core.llm_client import LLMRequest, call_llm, parse_json_response
    from stages.stage4_translate import load_genre_pack, format_genre_pack_for_prompt
    import httpx

    # Genre Pack (đồng bộ Stage 4)
    genre_pack = load_genre_pack(bible.world.genre_id, _build_dummy_config_for_genre_pack())
    genre_pack_str = format_genre_pack_for_prompt(genre_pack)

    # Bible compact
    cast_brief = "\n".join(
        f"- {c.vi} ({c.zh}): {c.g}, {c.role}, {c.char}"
        for c in bible.cast.characters[:15]
    )

    # Relationships (giữa các speaker trong dòng cần dịch)
    speakers_zh = set(s.speaker_zh for s in subs if s.speaker_zh)
    rel_lines = []
    seen_pairs = set()
    for ch in bible.cast.characters:
        if ch.zh not in speakers_zh:
            continue
        for other_zh, rel in (ch.rel or {}).items():
            pair = tuple(sorted([ch.zh, other_zh]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            other_ch = bible.cast.get_by_zh(other_zh)
            other_vi = other_ch.vi if other_ch else other_zh
            rel_lines.append(f"- {ch.vi} ↔ {other_vi}: {rel}")
    rel_block = "\n".join(rel_lines) if rel_lines else "(Không có quan hệ rõ)"

    # Glossary — gộp từ tất cả dòng cần dịch
    all_text = " ".join(s.original_text or "" for s in subs)
    relevant_terms = bible.glossary.find_in_text(all_text)
    gloss_block = "\n".join(
        f"- {t.zh} → \"{t.vi}\"" for t in relevant_terms
    ) or "(Không có)"

    # Context window (cap 5, default 2)
    ctx_n = max(1, min(5, req.context_window or 2))
    min_idx = min(s.index for s in subs)
    max_idx = max(s.index for s in subs)

    ctx_before_subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index < min_idx,
    ).order_by(Subtitle.index.desc()).limit(ctx_n).all()
    ctx_after_subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index > max_idx,
    ).order_by(Subtitle.index).limit(ctx_n).all()

    def _ctx_line(s):
        vi = (s.text or '').replace('\n', ' ')
        zh = (s.original_text or '').replace('\n', ' ')
        return f"  [{s.index}] {s.speaker_zh or '?'} | {zh} → {vi}"

    ctx_before_str = "\n".join(_ctx_line(s) for s in reversed(ctx_before_subs)) or "(không có)"
    ctx_after_str = "\n".join(_ctx_line(s) for s in ctx_after_subs) or "(không có)"

    # Lines cần dịch — format: [index] speaker_zh | text_zh | emotion | intensity
    target_lines_str = "\n".join(
        f"[{s.index}] {s.speaker_zh or '?'} | {s.original_text or ''} "
        f"| {s.emotion or 'neutral'} | {s.intensity or 5}"
        for s in subs
    )

    # Prompt — đồng bộ Stage 4 (cụm sub liền mạch + Genre Pack + CẤM xưng hô)
    prompt = f"""Dịch lại {len(subs)} dòng phụ đề TQ→Việt cho lồng tiếng C-drama.

━━━ THÔNG TIN PHIM ━━━
Thể loại: {', '.join(bible.world.genre)}
Tone: {bible.world.tone}
Era: {bible.world.era}

━━━ NHÂN VẬT ━━━
{cast_brief}

━━━ QUAN HỆ ━━━
{rel_block}

━━━ GLOSSARY ━━━
{gloss_block}

━━━ GENRE PACK ━━━
{genre_pack_str}

━━━ CONTEXT TRƯỚC (chỉ tham khảo, KHÔNG dịch) ━━━
{ctx_before_str}

━━━ DÒNG CẦN DỊCH LẠI ({len(subs)} dòng) ━━━
Format: [line_index] speaker_zh | text_zh | emotion | intensity

{target_lines_str}

━━━ CONTEXT SAU (chỉ tham khảo, KHÔNG dịch) ━━━
{ctx_after_str}

━━━ NGUYÊN TẮC DỊCH ━━━

1. ĐÚNG NGHĨA + HIỂU CỤM SUB:
   - Phụ đề TQ cắt theo nhịp hơi thở, 1 câu dài thường bị cắt 2-4 sub liên tiếp
   - Cấu trúc TQ và VN NGƯỢC NHAU (TQ: bổ ngữ TRƯỚC danh từ; VN: bổ ngữ SAU)
   - Đọc CẢ CỤM, hiểu trọn ý, phân bổ chữ Việt giữa các sub cho mượt
   - KHÔNG ép mỗi sub thành câu trọn riêng nếu nó là mảnh của 1 câu dài
   Vd: "我要让你成为全世界 / 最幸福的女人"
   ✅ "Anh muốn biến em thành / người phụ nữ hạnh phúc nhất trên thế gian này"
   ❌ "Anh muốn em trở thành cả thế giới / hạnh phúc nhất"

2. TỰ NHIÊN — câu Việt mượt, không "mùi dịch", đảo cấu trúc khi cần

3. ĐÚNG TONE + NHÂN VẬT — xưng hô theo quan hệ + emotion + Genre Pack
   CẤM TUYỆT ĐỐI:
   ✗ "con-mẹ/bố" nếu KHÔNG có huyết thống trong quan hệ
   ✗ "anh-em" cho 2 nữ (trừ chị em ruột → "chị-em")
   ✗ "anh-em" cho 2 nam (dùng "tôi-cậu" / cổ trang "huynh-đệ")
   ✗ Xưng hô cổ trang trong phim hiện đại (không "tại hạ", "thiếp")
   ✗ "ngài" cho người thân (vợ chồng, anh chị em)

4. ĐÚNG VĂN HÓA — thành ngữ TQ → tương đương VN, văn phong khớp era

5. GIỮ SỐ DÒNG — output PHẢI có ĐÚNG {len(subs)} entry, mỗi line_index input
   có đúng 1 entry. KHÔNG bỏ, KHÔNG gộp, KHÔNG tách. Được phân bổ chữ giữa
   các sub liền kề cho mượt — text_v1 mỗi dòng KHÔNG được rỗng.

━━━ YÊU CẦU NGƯỜI DÙNG ━━━
{req.hint or "(không có yêu cầu đặc biệt — dịch tốt hơn bản hiện tại)"}

━━━ NHIỆM VỤ ━━━
Mỗi dòng trả 2 BẢN DỊCH KHÁC NHAU:
- text_v1: SÁT NGHĨA — sát cấu trúc TQ, phù hợp subtitle
- text_v2: THOÁT Ý — người Việt nói tự nhiên, phù hợp lồng tiếng (null nếu trùng v1)

OUTPUT JSON THUẦN:
{{
  "translations": [
    {{
      "line_index": <index>,
      "text_v1": "...",
      "text_v2": "..." | null,
      "emotion": "neutral|happy|sad|angry|cold|tense|intimate|fearful|sarcastic|shocked|determined|regretful|humorous|threatening",
      "intensity": 1-10
    }}
  ]
}}

CHỈ TRẢ JSON, KHÔNG markdown fence."""

    # Cap output theo số dòng (tránh model trả thiếu)
    max_output = min(8000, 1000 + 800 * len(subs))

    llm_req = LLMRequest(
        prompt=prompt, model=req.model, api_key=req.api_key,
        temperature=0.5, max_output=max_output, json_mode=True,
        thinking=req.thinking,
    )

    try:
        async with httpx.AsyncClient() as client:
            resp = await call_llm(llm_req, client=client, stage_tag="retranslate_batch")
    except Exception as e:
        raise HTTPException(500, f"LLM call failed: {e}")

    data = parse_json_response(resp.text, default={"translations": []})
    translations = data.get("translations", []) or []

    # Map line_index → result
    result_by_idx = {}
    for t in translations:
        try:
            line_idx = int(t.get("line_index", -1))
            if line_idx < 1:
                continue
            result_by_idx[line_idx] = t
        except (TypeError, ValueError):
            continue

    # Build response — đảm bảo đủ dòng (nếu AI bỏ sót → trả text_v1 = current)
    out_lines: list[RetranslateBatchLineOut] = []
    for s in subs:
        t = result_by_idx.get(s.index, {})
        text_v1_raw = (t.get("text_v1") or "").strip()
        text_v2_raw = (t.get("text_v2") or "").strip() or None
        # Đảm bảo v2 != v1
        if text_v2_raw and text_v2_raw == text_v1_raw:
            text_v2_raw = None

        out_lines.append(RetranslateBatchLineOut(
            line_index=s.index,
            subtitle_id=s.id,
            text_v1=text_v1_raw or (s.text_v1 or s.text or ""),
            text_v2=text_v2_raw,
            emotion=t.get("emotion") or s.emotion,
            intensity=_safe_int(t.get("intensity"), s.intensity or 5),
            current_text_v1=s.text_v1,
            current_text_v2=s.text_v2,
        ))

    return RetranslateBatchResponse(
        ok=True,
        lines=out_lines,
        tokens_in=resp.tokens_in or 0,
        tokens_out=resp.tokens_out or 0,
    )


def _safe_int(v, default: int) -> int:
    try:
        return max(1, min(10, int(float(v))))
    except (TypeError, ValueError):
        return default


def _build_dummy_config_for_genre_pack():
    """Build tối thiểu PipelineConfig chỉ để load_genre_pack đọc được prompts_dir."""
    from config import default_config
    return default_config()


# ─── Chunks (v3 — 3 tầng arc/chunk/scene) ────────────────────────────────────

@router.get("/projects/{pid}/chunks", response_model=list[ChunkOut])
def list_chunks(pid: int, db: Session = Depends(get_db)):
    """List chunks của project, kèm arc info."""
    _get_project(db, pid)
    chunks = db.query(DBChunk).filter(
        DBChunk.project_id == pid
    ).order_by(DBChunk.chunk_index).all()
    arcs = db.query(DBStoryArc).filter(
        DBStoryArc.project_id == pid
    ).all()
    arc_by_idx = {a.arc_index: a for a in arcs}

    result = []
    for c in chunks:
        arc = arc_by_idx.get(c.arc_index)
        scene_count = db.query(DBScene).filter(DBScene.chunk_id == c.id).count()
        result.append(_db_chunk_to_out(
            c,
            scene_count=scene_count,
            arc_title=arc.title if arc else "",
            arc_tone=arc.emotional_tone if arc else "",
        ))
    return result


@router.get("/projects/{pid}/chunks/{chunk_id}")
def get_chunk_detail(pid: int, chunk_id: int, db: Session = Depends(get_db)):
    """Chi tiết 1 chunk + scenes + subtitles."""
    _get_project(db, pid)
    c = db.query(DBChunk).filter(
        DBChunk.id == chunk_id,
        DBChunk.project_id == pid,
    ).first()
    if not c:
        raise HTTPException(404, "Chunk not found")

    scenes = db.query(DBScene).filter(
        DBScene.chunk_id == chunk_id
    ).order_by(DBScene.start_line).all()

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.chunk_id == chunk_id,
    ).order_by(Subtitle.index).all()

    arc = db.query(DBStoryArc).filter(
        DBStoryArc.project_id == pid,
        DBStoryArc.arc_index == c.arc_index,
    ).first()

    return {
        "id": c.id,
        "project_id": c.project_id,
        "arc_index": c.arc_index,
        "chunk_index": c.chunk_index,
        "title": c.title,
        "start_line": c.start_line,
        "end_line": c.end_line,
        "status": c.status,
        "arc_title": arc.title if arc else "",
        "arc_tone": arc.emotional_tone if arc else "",
        "scenes": [_db_scene_to_out(s).dict() for s in scenes],
        "subtitles_count": len(subs),
    }


# ─── Variant Selection (v3) ───────────────────────────────────────────────────

@router.post("/projects/{pid}/subtitles/{sub_id}/select-variant")
def select_variant(pid: int, sub_id: int, req: dict, db: Session = Depends(get_db)):
    """User chọn bản v1 hoặc v2 dùng làm text active."""
    sub = db.query(Subtitle).filter(
        Subtitle.id == sub_id,
        Subtitle.project_id == pid,
    ).first()
    if not sub:
        raise HTTPException(404, "Subtitle not found")

    variant = int(req.get("variant", 1))
    if variant not in (1, 2):
        raise HTTPException(400, "variant phải 1 hoặc 2")

    sub.variant_selected = variant
    # Update active text
    if variant == 2 and sub.text_v2:
        sub.text = sub.text_v2
    else:
        sub.text = sub.text_v1 or ""

    # Recompute CPS
    duration = max(0.01, sub.end_time - sub.start_time)
    from core.srt_parser import calculate_cps
    sub.cps_value = calculate_cps(sub.text, duration) if sub.text else None

    # Reset tts_done vì text đã đổi
    sub.tts_done = False
    sub.audio_path = None

    db.commit()
    return {
        "ok": True,
        "subtitle_id": sub.id,
        "variant_selected": sub.variant_selected,
        "text": sub.text,
        "cps_value": sub.cps_value,
    }


@router.post("/projects/{pid}/subtitles/bulk-select-variant")
def bulk_select_variant(pid: int, req: dict, db: Session = Depends(get_db)):
    """Bulk: chọn cùng 1 variant cho nhiều dòng (hoặc tất cả).

    Body: {"variant": 1|2, "subtitle_ids": [...] | null (= all)}
    """
    variant = int(req.get("variant", 1))
    if variant not in (1, 2):
        raise HTTPException(400, "variant phải 1 hoặc 2")

    ids = req.get("subtitle_ids")
    q = db.query(Subtitle).filter(Subtitle.project_id == pid)
    if ids:
        q = q.filter(Subtitle.id.in_(ids))

    from core.srt_parser import calculate_cps
    updated = 0
    for sub in q.all():
        # Chỉ apply variant 2 nếu có text_v2
        if variant == 2 and not sub.text_v2:
            continue
        sub.variant_selected = variant
        sub.text = sub.text_v2 if variant == 2 else (sub.text_v1 or "")
        duration = max(0.01, sub.end_time - sub.start_time)
        sub.cps_value = calculate_cps(sub.text, duration) if sub.text else None
        sub.tts_done = False
        sub.audio_path = None
        updated += 1

    db.commit()
    return {"ok": True, "updated": updated, "variant": variant}