"""
Background job runner cho Simple pipeline.

Mỗi task LLM dài (Bible part, Translate batch, Repair group, Run-all)
được run trong asyncio Task ngầm — endpoint HTTP trả 202 Accepted ngay.

Trạng thái + tiến độ được broadcast qua WebSocket `/ws/{project_id}` với
message format:

  {
    "kind": "simple",                   # phân biệt với pipeline cũ
    "task_id": "bible.part.3",          # định danh duy nhất
    "section": "bible" | "batches" | "review" | "issues",
    "phase": "started" | "progress" | "done" | "error",
    "ref": {"part_index": 3, ...},      # tham chiếu phần đang chạy
    "data": {...}                       # state mới (FE merge vào)
    "message": "Đang gọi LLM..."        # chữ hiển thị
    "error": "Timeout sau 300s"         # khi phase=error
  }

FE listen WS để update UI real-time mà không poll.
"""
from __future__ import annotations
import asyncio
import logging
import traceback
from typing import Awaitable, Callable, Optional, Any
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from dubeditor.database import SessionLocal
from dubeditor.routers.ws import broadcast as ws_broadcast

logger = logging.getLogger(__name__)


# ─── In-memory registry of running tasks ────────────────────────────────────
# Key: f"{project_id}:{task_id}", Value: asyncio.Task hoặc concurrent.futures.Future
# Cho phép cancel khi user click "Dừng".

_active_tasks: dict = {}

# Event loop chính của app (set lúc startup). Dùng để schedule task từ
# worker thread (FastAPI chạy sync endpoint trong threadpool → không có loop).
_main_loop = None


def set_main_loop(loop) -> None:
    """Gọi 1 lần lúc app startup để lưu event loop chính.

    Trong app.py, thêm vào startup event:
        @app.on_event("startup")
        async def _save_loop():
            import asyncio
            from dubeditor.simple.jobs import set_main_loop
            set_main_loop(asyncio.get_running_loop())
    """
    global _main_loop
    _main_loop = loop
    logger.info("[simple.jobs] main event loop registered")


def _get_main_loop():
    """Lấy loop chính. Fallback: thử get_running_loop (nếu đang trong async context)."""
    global _main_loop
    if _main_loop is not None and not _main_loop.is_closed():
        return _main_loop
    # Fallback — thử lấy loop đang chạy (chỉ work nếu gọi từ async context)
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def task_key(project_id: int, task_id: str) -> str:
    return f"{project_id}:{task_id}"


def is_task_running(project_id: int, task_id: str) -> bool:
    key = task_key(project_id, task_id)
    task = _active_tasks.get(key)
    if task is None:
        return False
    # asyncio.Task có .done(); concurrent Future cũng có .done()
    return not task.done()


def cancel_task(project_id: int, task_id: str) -> bool:
    key = task_key(project_id, task_id)
    task = _active_tasks.get(key)
    if task and not task.done():
        task.cancel()
        return True
    return False


# ─── Broadcast helpers ──────────────────────────────────────────────────────

async def broadcast_simple(
    project_id: int,
    section: str,
    task_id: str,
    phase: str,
    *,
    ref: Optional[dict] = None,
    data: Any = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Gửi 1 simple event qua WS cho project."""
    payload = {
        "kind": "simple",
        "section": section,
        "task_id": task_id,
        "phase": phase,
        "ref": ref or {},
    }
    if data is not None:
        payload["data"] = data
    if message:
        payload["message"] = message
    if error:
        payload["error"] = error
    payload["ts"] = datetime.now(timezone.utc).isoformat()

    try:
        await ws_broadcast(project_id, payload)
        logger.info(f"[simple.broadcast] sent {section}.{task_id} phase={phase} "
                    f"data={'yes' if data is not None else 'no'}")
    except Exception as e:
        logger.warning(f"[simple.broadcast] failed: {e}")


# ─── Spawner ────────────────────────────────────────────────────────────────

def spawn_task(
    project_id: int,
    section: str,
    task_id: str,
    coro_factory: Callable[[Session], Awaitable[Any]],
    *,
    ref: Optional[dict] = None,
    state_loader: Optional[Callable[[Session], Any]] = None,
    start_message: str = "Đang chạy...",
) -> str:
    """Spawn 1 background task chạy LLM job.

    Args:
        project_id, section, task_id: dùng cho WS routing
        coro_factory: hàm async nhận session DB, thực hiện job
        ref: dict metadata (vd {part_index: 3})
        state_loader: hàm sync nhận session, trả về state dict
                      sẽ được broadcast cùng với phase=done
        start_message: chữ hiển thị khi bắt đầu

    Returns:
        task_id (để FE/UI tracking)
    """
    key = task_key(project_id, task_id)

    # Nếu task cùng key đang chạy → reject
    if is_task_running(project_id, task_id):
        logger.info(f"[simple.spawn] {key} already running, skip")
        return task_id

    async def _runner():
        # Tạo session mới riêng cho task (không dùng session từ request)
        db = SessionLocal()
        try:
            await broadcast_simple(
                project_id, section, task_id, "started",
                ref=ref, message=start_message,
            )

            # Run job
            await coro_factory(db)

            # Broadcast done với state mới (nếu có)
            data = None
            if state_loader:
                try:
                    data = state_loader(db)
                except Exception as e:
                    logger.warning(f"[simple.spawn] state_loader error: {e}")

            await broadcast_simple(
                project_id, section, task_id, "done",
                ref=ref, data=data, message="Hoàn tất",
            )
        except asyncio.CancelledError:
            await broadcast_simple(
                project_id, section, task_id, "error",
                ref=ref, error="Đã dừng",
            )
            raise
        except Exception as e:
            logger.exception(f"[simple.spawn] task {key} failed: {e}")
            await broadcast_simple(
                project_id, section, task_id, "error",
                ref=ref,
                error=str(e)[:500],
                message=f"Lỗi: {str(e)[:120]}",
            )
        finally:
            db.close()
            _active_tasks.pop(key, None)

    loop = _get_main_loop()
    if loop is None:
        # Không có loop → không thể chạy background. Báo lỗi rõ ràng.
        logger.error(
            "[simple.spawn] No main event loop registered. "
            "Đảm bảo app.py gọi set_main_loop() lúc startup."
        )
        raise RuntimeError(
            "Background task không chạy được: chưa có event loop. "
            "Cần đăng ký set_main_loop() lúc app startup."
        )

    # FastAPI chạy sync endpoint trong worker thread (không có loop).
    # run_coroutine_threadsafe schedule coroutine lên loop CHÍNH một cách
    # thread-safe, trả về concurrent.futures.Future.
    future = asyncio.run_coroutine_threadsafe(_runner(), loop)
    _active_tasks[key] = future

    logger.info(f"[simple.spawn] launched {key}")
    return task_id


def list_active_tasks(project_id: int) -> list[str]:
    """Trả list task_id đang chạy cho project."""
    prefix = f"{project_id}:"
    return [
        k[len(prefix):]
        for k, t in _active_tasks.items()
        if k.startswith(prefix) and not t.done()
    ]
