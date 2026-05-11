"""
TTS Queue — quản lý hàng chờ tạo TTS, 1 worker async sequential.
- High priority: insert đầu queue (move lên trước nếu đã có)
- Normal priority: append cuối queue (skip nếu đã có)
- 1 worker chạy liên tục, lấy từ đầu queue
- Cancel: clear pending, không ngắt sub đang chạy
- Queue state lưu RAM, broadcast WS mỗi khi đổi
"""
import asyncio
import logging
from collections import deque
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)


class ProjectQueue:
    """Queue cho 1 project."""
    def __init__(self, project_id: int):
        self.project_id = project_id
        self.pending: deque[int] = deque()
        self.running: Optional[int] = None
        self._lock = asyncio.Lock()

    def state(self) -> dict:
        return {
            "project_id": self.project_id,
            "running": self.running,
            "pending": list(self.pending),
        }

    async def enqueue(self, sub_ids: list[int], priority: str = "normal"):
        async with self._lock:
            if priority == "high":
                # Insert đầu — duyệt ngược để giữ thứ tự ban đầu
                for sid in reversed(sub_ids):
                    if sid in self.pending:
                        self.pending.remove(sid)
                    if sid != self.running:  # đang chạy thì bỏ qua
                        self.pending.appendleft(sid)
            else:
                # Append cuối — skip nếu đã có
                for sid in sub_ids:
                    if sid not in self.pending and sid != self.running:
                        self.pending.append(sid)

    async def pop_next(self) -> Optional[int]:
        async with self._lock:
            if not self.pending:
                return None
            return self.pending.popleft()

    async def cancel_all(self):
        async with self._lock:
            self.pending.clear()


class TTSQueueManager:
    """
    Quản lý queue cho tất cả projects.
    Worker chung — mỗi tick lấy 1 project có pending → xử lý.
    """
    def __init__(self):
        self.queues: dict[int, ProjectQueue] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._broadcast_fn: Optional[Callable[[int, dict], Awaitable[None]]] = None
        self._generate_fn: Optional[Callable[[int], Awaitable[None]]] = None
        self._stop = False

    def setup(self, generate_fn, broadcast_fn):
        """
        generate_fn(subtitle_id) — async, generate 1 sub
        broadcast_fn(project_id, data) — async, broadcast WS event
        """
        self._generate_fn = generate_fn
        self._broadcast_fn = broadcast_fn

    def get_queue(self, project_id: int) -> ProjectQueue:
        if project_id not in self.queues:
            self.queues[project_id] = ProjectQueue(project_id)
        return self.queues[project_id]

    async def enqueue(self, project_id: int, sub_ids: list[int], priority: str = "normal"):
        q = self.get_queue(project_id)
        await q.enqueue(sub_ids, priority)
        await self._broadcast_state(project_id)

    async def cancel_all(self, project_id: int):
        q = self.get_queue(project_id)
        await q.cancel_all()
        await self._broadcast_state(project_id)

    def get_state(self, project_id: int) -> dict:
        q = self.get_queue(project_id)
        return q.state()

    async def _broadcast_state(self, project_id: int):
        if self._broadcast_fn:
            try:
                await self._broadcast_fn(project_id, {
                    "type": "tts_queue_state",
                    **self.get_queue(project_id).state(),
                })
            except Exception as e:
                logger.warning(f"[TTSQueue] broadcast failed: {e}")

    def start_worker(self):
        """Chạy worker trong event loop hiện tại."""
        if self._worker_task and not self._worker_task.done():
            return
        self._stop = False
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("[TTSQueue] Worker started")

    def stop_worker(self):
        self._stop = True
        if self._worker_task:
            self._worker_task.cancel()

    async def _worker_loop(self):
        """
        Worker chính — round-robin các project có pending.
        Mỗi iter: pick 1 project có sub trong queue → pop → generate → broadcast.
        """
        while not self._stop:
            target_pid = None
            target_q = None
            for pid, q in list(self.queues.items()):
                if q.pending and q.running is None:
                    target_pid = pid
                    target_q = q
                    break

            if target_pid is None:
                await asyncio.sleep(0.2)
                continue

            sub_id = await target_q.pop_next()
            if sub_id is None:
                continue

            target_q.running = sub_id
            await self._broadcast_state(target_pid)

            try:
                if self._generate_fn:
                    await self._generate_fn(sub_id)
            except Exception as e:
                logger.error(f"[TTSQueue] gen failed sub={sub_id}: {e}", exc_info=True)
                if self._broadcast_fn:
                    try:
                        await self._broadcast_fn(target_pid, {
                            "type": "tts_queue_error",
                            "subtitle_id": sub_id,
                            "error": str(e)[:200],
                        })
                    except: pass
            finally:
                target_q.running = None
                await self._broadcast_state(target_pid)


# Singleton
queue_manager = TTSQueueManager()
