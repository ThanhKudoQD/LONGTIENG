"""
Auto Flow orchestrator — chạy tuần tự Bible → Dịch → Review trong 1 lần.

Smart skip:
  - Bible: bỏ qua nếu master bible đã có (status done)
  - Dịch: bỏ qua batch đã translated, chỉ chạy batch idle/error
  - Review: rebuild + chạy các group chưa done

Retry: mỗi batch/part lỗi → thử lại 1 lần.

Tiến độ broadcast qua WS section='flow'. Log lưu in-memory + trả qua state.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.simple import (
    service_bible, service_translate, service_review, service_config,
    service_characters,
)
from dubeditor.simple.models import (
    SimpleBiblePart, SimpleBibleMerge, SimpleBatch, SimpleReviewGroup,
)

logger = logging.getLogger(__name__)

# In-memory log cho mỗi project (flow gần nhất)
_flow_logs: dict[int, list] = {}
_flow_status: dict[int, dict] = {}


def _log(project_id: int, level: str, msg: str) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "msg": msg,
    }
    _flow_logs.setdefault(project_id, []).append(entry)
    # Giữ tối đa 200 dòng log
    if len(_flow_logs[project_id]) > 200:
        _flow_logs[project_id] = _flow_logs[project_id][-200:]
    logger.info(f"[flow {project_id}] {level}: {msg}")


def get_flow_state(project_id: int) -> dict:
    return {
        "status": _flow_status.get(project_id, {"phase": "idle", "running": False}),
        "logs": _flow_logs.get(project_id, []),
    }


def reset_flow_log(project_id: int) -> None:
    _flow_logs[project_id] = []
    _flow_status[project_id] = {"phase": "idle", "running": False}


def _set_status(project_id: int, **kw) -> None:
    cur = _flow_status.get(project_id, {})
    cur.update(kw)
    _flow_status[project_id] = cur


# ─── Bible step ───────────────────────────────────────────────────────────────

def _bible_done(db: Session, project_id: int) -> bool:
    """Bible coi như xong nếu có master bible (merge done HOẶC single part done)."""
    master = service_bible.get_master_bible_dict(db, project_id)
    return bool(master and master.get('c'))


async def _run_bible_step(db: Session, project_id: int, config) -> bool:
    """Chạy Bible nếu chưa có. Trả True nếu sau bước này Bible sẵn sàng."""
    if _bible_done(db, project_id):
        _log(project_id, "info", "Bible đã có sẵn → bỏ qua.")
        return True

    parts = db.query(SimpleBiblePart).filter(
        SimpleBiblePart.project_id == project_id
    ).order_by(SimpleBiblePart.part_index).all()

    if not parts:
        _log(project_id, "error", "Chưa có Bible part nào. Vào tab Bible chọn mode trước.")
        return False

    # Single mode (1 part) hoặc multi
    for part in parts:
        if part.status == 'done':
            continue
        ok = await _run_with_retry(
            project_id, f"Bible part {part.part_index + 1}",
            lambda pid=part.id: service_bible.run_bible_part(db, pid, config)
        )
        if not ok:
            return False

    # Multi mode → cần merge
    if len(parts) > 1:
        merge = db.query(SimpleBibleMerge).filter(
            SimpleBibleMerge.project_id == project_id
        ).first()
        if not merge or merge.status != 'done':
            ok = await _run_with_retry(
                project_id, "Bible merge",
                lambda: service_bible.run_bible_merge(db, project_id, config)
            )
            if not ok:
                return False

    return _bible_done(db, project_id)


# ─── Translate step ───────────────────────────────────────────────────────────

async def _run_translate_step(db: Session, project_id: int, config) -> bool:
    """Rebuild batches nếu cần + dịch các batch chưa xong."""
    # Sync characters + rebuild batches (đảm bảo prompt có Bible mới nhất)
    service_characters.sync_characters_from_bible(db, project_id)

    batches = db.query(SimpleBatch).filter(
        SimpleBatch.project_id == project_id
    ).order_by(SimpleBatch.batch_index).all()

    if not batches:
        _log(project_id, "info", "Chưa có batch → rebuild...")
        service_translate.rebuild_batches(db, project_id, config)
        batches = db.query(SimpleBatch).filter(
            SimpleBatch.project_id == project_id
        ).order_by(SimpleBatch.batch_index).all()

    if not batches:
        _log(project_id, "error", "Không tạo được batch nào.")
        return False

    total = len(batches)
    done_count = sum(1 for b in batches if b.status == 'done')
    _log(project_id, "info", f"Dịch: {total} batch, {done_count} đã xong, dịch phần còn lại.")

    for b in batches:
        if b.status == 'done':
            continue
        _set_status(project_id, phase="translate", detail=f"batch {b.batch_index + 1}/{total}")
        ok = await _run_with_retry(
            project_id, f"Dịch batch {b.batch_index + 1}",
            lambda bid=b.id: service_translate.run_batch(db, bid, config)
        )
        # batch lỗi → bỏ qua, chạy tiếp (đã retry trong _run_with_retry)
        if not ok:
            _log(project_id, "warn", f"Batch {b.batch_index + 1} bỏ qua sau khi retry.")

    return True


# ─── Review step ───────────────────────────────────────────────────────────────

async def _run_review_step(db: Session, project_id: int, config) -> bool:
    """Rebuild review groups + chạy AI review tất cả."""
    _log(project_id, "info", "Review: chia batch review...")
    service_review.rebuild_review_groups(db, project_id, config)

    groups = db.query(SimpleReviewGroup).filter(
        SimpleReviewGroup.project_id == project_id
    ).order_by(SimpleReviewGroup.group_index).all()

    if not groups:
        _log(project_id, "info", "Không có gì để review (chưa có bản dịch).")
        return True

    total = len(groups)
    for g in groups:
        _set_status(project_id, phase="review", detail=f"nhóm {g.group_index + 1}/{total}")
        ok = await _run_with_retry(
            project_id, f"Review nhóm {g.group_index + 1}",
            lambda gid=g.id: service_review.run_review_group(db, gid)
        )
        if not ok:
            _log(project_id, "warn", f"Review nhóm {g.group_index + 1} bỏ qua sau khi retry.")

    return True


# ─── Retry helper ────────────────────────────────────────────────────────────

async def _run_with_retry(project_id: int, label: str, coro_fn, max_retry: int = 1) -> bool:
    """Chạy coro_fn (async). Lỗi → retry tối đa max_retry lần. Trả True nếu thành công."""
    import asyncio
    attempt = 0
    while attempt <= max_retry:
        try:
            result = coro_fn()
            if asyncio.iscoroutine(result):
                await result
            _log(project_id, "ok", f"{label} ✓")
            return True
        except Exception as e:
            attempt += 1
            if attempt <= max_retry:
                _log(project_id, "warn", f"{label} lỗi ({e}); thử lại lần {attempt}...")
            else:
                _log(project_id, "error", f"{label} thất bại sau {max_retry} retry: {e}")
                return False
    return False


# ─── Main orchestrator ──────────────────────────────────────────────────────

async def run_full_flow(
    db: Session,
    project_id: int,
    *,
    do_bible: bool = True,
    do_translate: bool = True,
    do_review: bool = True,
) -> dict:
    """Chạy tuần tự các bước được chọn. Smart skip phần đã xong."""
    reset_flow_log(project_id)
    _set_status(project_id, running=True, phase="start")
    _log(project_id, "info", "=== Bắt đầu Auto Flow ===")

    config = service_config.load_config(db, project_id)

    try:
        if do_bible:
            _set_status(project_id, phase="bible")
            _log(project_id, "info", "── Bước 1: Movie Bible ──")
            if not await _run_bible_step(db, project_id, config):
                _log(project_id, "error", "Bible thất bại → dừng flow.")
                _set_status(project_id, running=False, phase="error")
                return get_flow_state(project_id)

        if do_translate:
            _set_status(project_id, phase="translate")
            _log(project_id, "info", "── Bước 2: Dịch batch ──")
            if not await _run_translate_step(db, project_id, config):
                _log(project_id, "error", "Dịch thất bại → dừng flow.")
                _set_status(project_id, running=False, phase="error")
                return get_flow_state(project_id)

        if do_review:
            _set_status(project_id, phase="review")
            _log(project_id, "info", "── Bước 3: AI Review ──")
            await _run_review_step(db, project_id, config)

        _log(project_id, "ok", "=== Auto Flow HOÀN TẤT ===")
        _set_status(project_id, running=False, phase="done")
    except Exception as e:
        _log(project_id, "error", f"Flow crash: {e}")
        _set_status(project_id, running=False, phase="error")

    return get_flow_state(project_id)
