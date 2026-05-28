"""
LLM runner — wrapper async cho 4 task của Simple pipeline.

Reuse `srt_translator_v2/core/llm_client.py` (đã được test kỹ ở pipeline v3).
"""
from __future__ import annotations
import asyncio
import sys
import logging
import time
from pathlib import Path
from typing import Optional, Literal

# Add srt_translator_v2 to sys.path (lib gốc)
_TRANSLATOR_DIR = Path(__file__).parent.parent.parent / "srt_translator_v2"
if str(_TRANSLATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATOR_DIR))

from core.llm_client import (
    LLMRequest, LLMResponse,
    call_llm, estimate_cost, cap_max_output,
)

logger = logging.getLogger(__name__)


# ─── Task → max_output mapping ───────────────────────────────────────────────

TaskKey = Literal['bible', 'translate', 'repair', 'qa']

# Bible cần output dài (JSON to). Translate batch ~3-5k tok. Repair ngắn hơn.
# LƯU Ý: với reasoning models (gpt-5*, o1*...), max_output bao gồm CẢ reasoning
# tokens (ẩn) + output thật. gpt-5-nano có thể tốn 8-12k token reasoning trước
# khi trả JSON → cần max_output cao để JSON không bị cắt giữa chừng.
TASK_MAX_OUTPUT = {
    'bible':     65536,   # JSON Bible có thể dài nếu nhiều nhân vật
    'translate': 65536,   # reasoning models (gpt-5-nano) tốn nhiều token ẩn
    'repair':    16384,
    'qa':        8192,
}

TASK_TEMPERATURE = {
    'bible':     0.2,     # JSON structured, ít creative
    'translate': 0.4,     # cần chút linh hoạt cho dịch tự nhiên
    'repair':    0.3,
    'qa':        0.3,
}


# ─── Public API ──────────────────────────────────────────────────────────────

async def run_llm_task(
    task: TaskKey,
    prompt: str,
    *,
    model: str,
    api_key: str,
    thinking: bool = False,
    cached_prefix: Optional[str] = None,
    timeout: float = 300.0,
    max_retries: int = 3,
) -> LLMResponse:
    """Gọi LLM cho 1 task. Trả LLMResponse với text, tokens, cost.

    Raises Exception nếu fail sau retry.

    Args:
        task: 'bible' | 'translate' | 'repair' | 'qa'
        prompt: prompt đầy đủ (variable part — phần KHÔNG cache)
        model: model id (vd 'gemini-2.5-pro')
        api_key: API key cho provider tương ứng
        thinking: bật/tắt thinking (chỉ áp dụng cho Gemini 2.5+, o-series)
        cached_prefix: block lớn để cache (bible content cho translate task)
        timeout: giây
        max_retries: số lần retry khi LLM lỗi (timeout, 5xx)
    """
    if not api_key:
        raise ValueError(f"Missing API key for task '{task}' with model '{model}'")
    if not prompt or not prompt.strip():
        raise ValueError(f"Empty prompt for task '{task}'")

    max_output = cap_max_output(TASK_MAX_OUTPUT.get(task, 8192), model)
    temperature = TASK_TEMPERATURE.get(task, 0.3)

    req = LLMRequest(
        prompt=prompt,
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_output=max_output,
        json_mode=True,           # tất cả 4 task đều output JSON
        timeout=timeout,
        cached_prefix=cached_prefix,
        thinking=thinking,
        max_retries=max_retries,
    )

    started = time.monotonic()
    try:
        resp = await call_llm(req)
    except Exception as e:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        logger.exception(
            f"[simple.llm_runner] Task={task} model={model} failed after {elapsed_ms}ms: {e}"
        )
        raise

    # Đảm bảo resp có cost
    if resp.tokens_in or resp.tokens_out:
        # estimate_cost trả về USD
        cost = estimate_cost(resp)
        # Gắn vào raw để caller dễ lấy
        if resp.raw is None:
            resp.raw = {}
        resp.raw['_cost_usd'] = cost

    logger.info(
        f"[simple.llm_runner] Task={task} model={model} "
        f"tokens_in={resp.tokens_in} tokens_out={resp.tokens_out} "
        f"cached={resp.cached_tokens} ms={resp.timing_ms}"
    )
    return resp


def get_cost(resp: LLMResponse) -> float:
    """Lấy cost USD từ response. Trả 0 nếu chưa estimate."""
    if resp.raw and isinstance(resp.raw, dict):
        return float(resp.raw.get('_cost_usd', 0.0))
    return estimate_cost(resp)


# ─── Parallel runner cho Turbo mode ──────────────────────────────────────────

async def run_llm_tasks_parallel(
    tasks: list[dict],
    *,
    concurrency: int = 5,
) -> list[LLMResponse | Exception]:
    """Chạy nhiều LLM call song song với concurrency limit.

    Args:
        tasks: list các dict với keys giống run_llm_task args
        concurrency: max parallel calls

    Returns:
        List response (cùng order với tasks). Phần tử có thể là Exception nếu fail.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(t: dict):
        async with sem:
            try:
                return await run_llm_task(**t)
            except Exception as e:
                return e

    return await asyncio.gather(*[_one(t) for t in tasks])
