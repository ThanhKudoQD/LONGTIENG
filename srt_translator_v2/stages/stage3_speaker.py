"""
Stage 3 — Speaker (v3 refactored).

Cải tiến:
- Sliding window 20 dòng context trước + 20 dòng sau (read-only) → giảm lỗi
  gán sai speaker ở đầu/cuối chunk
- Inject arc.summary + chunk title vào prompt → AI hiểu mạch truyện
- Cache marker tách Bible+rules (cố định) khỏi chunk context (biến)
- Toggle config.speaker.parallel:
    · True (mặc định) → song song, mỗi chunk độc lập (cache không hit cross-chunk
      vì context_before/after khác nhau)
    · False → tuần tự, cache Bible+rules giữa chunks (giảm cost ~30%)

Mỗi call gán speaker cho 1 chunk.
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry
from models import Bible, Chunk, ChunkMap, Scene, StoryArc

logger = logging.getLogger(__name__)


CACHE_MARKER = "━━━ PHẦN BIẾN — CONTEXT CHUNK ━━━"


def split_for_cache(prompt: str) -> tuple[str, str]:
    """Tách prompt thành (cached_prefix, variable) tại marker."""
    if CACHE_MARKER in prompt:
        idx = prompt.index(CACHE_MARKER)
        return prompt[:idx], prompt[idx:]
    return "", prompt


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def get_chunk_characters(chunk: Chunk, bible: Bible) -> set[str]:
    """Lấy tất cả nhân vật xuất hiện trong chunk (từ scenes)."""
    chars = set()
    if chunk.scenes:
        for sc in chunk.scenes:
            for c in sc.ch:
                chars.add(c)
    if not chars:
        for c in bible.cast.characters:
            chars.add(c.zh)
    return chars


def format_arc_characters(bible: Bible, chars_in_chunk: set[str]) -> str:
    """Format danh sách nhân vật trong chunk + bible info."""
    lines = []
    for ch in bible.cast.characters:
        if ch.zh in chars_in_chunk:
            lines.append(f"- {ch.zh} ({ch.vi}): {ch.g}, {ch.role}, {ch.char}")
    if not lines:
        for ch in bible.cast.characters[:10]:
            lines.append(f"- {ch.zh} ({ch.vi}): {ch.g}, {ch.role}, {ch.char}")
    return "\n".join(lines)


def format_scenes_info(chunk: Chunk) -> str:
    """Format scenes trong chunk."""
    if not chunk.scenes:
        return f"(Chunk {chunk.r[0]}-{chunk.r[1]} không chia scenes, là 1 mạch liền)"

    lines = []
    for i, sc in enumerate(chunk.scenes):
        chars_str = ", ".join(sc.ch)
        loc_str = f"@ {sc.loc}" if sc.loc else ""
        tag_str = f" [{sc.tag}]" if sc.tag else ""
        lines.append(f"Scene {i+1} ({sc.r[0]}-{sc.r[1]}): [{chars_str}] {loc_str}, {sc.e}{tag_str}")
    return "\n".join(lines)


def format_chunk_srt(entries: list[SrtEntry], chunk: Chunk) -> str:
    """Format SRT của chunk (phần cần gán)."""
    lines = []
    for e in entries:
        if chunk.r[0] <= e.index <= chunk.r[1]:
            lines.append(f"{e.index} | {e.text}")
    return "\n".join(lines)


def format_context_lines(
    entries: list[SrtEntry],
    start: int,
    end: int,
) -> str:
    """Format context lines (read-only). Trả về '(không có)' nếu rỗng."""
    if start > end:
        return "(không có — đầu/cuối phim)"
    lines = []
    for e in entries:
        if start <= e.index <= end:
            lines.append(f"{e.index} | {e.text}")
    return "\n".join(lines) if lines else "(không có)"


def find_arc_for_chunk(chunk: Chunk, bible: Bible) -> Optional[StoryArc]:
    """Tìm arc tương ứng với chunk."""
    for arc in bible.world.arcs:
        if arc.index == chunk.arc_index:
            return arc
    return None


# ─────────────────────────────────────────────────────────────────
# PROCESS 1 CHUNK
# ─────────────────────────────────────────────────────────────────

async def process_one_chunk(
    chunk: Chunk,
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: Optional[asyncio.Semaphore],
) -> dict[int, dict]:
    """Gán speaker cho 1 chunk với context window."""
    if semaphore is None:
        return await _process_chunk_inner(chunk, entries, bible, config, tracker, client)
    else:
        async with semaphore:
            return await _process_chunk_inner(chunk, entries, bible, config, tracker, client)


async def _process_chunk_inner(
    chunk: Chunk,
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> dict[int, dict]:
    chars_in_chunk = get_chunk_characters(chunk, bible)
    arc_chars = format_arc_characters(bible, chars_in_chunk)
    scenes_info = format_scenes_info(chunk)
    chunk_srt = format_chunk_srt(entries, chunk)

    # Arc info
    arc = find_arc_for_chunk(chunk, bible)
    arc_title = arc.t if arc else f"Arc {chunk.arc_index}"
    arc_summary = (arc.summary if arc and arc.summary else "(không có tóm tắt)")

    # Context window
    window = config.speaker.context_window
    total_lines = max(e.index for e in entries) if entries else 0
    ctx_before_start = max(1, chunk.r[0] - window)
    ctx_before_end = chunk.r[0] - 1
    ctx_after_start = chunk.r[1] + 1
    ctx_after_end = min(total_lines, chunk.r[1] + window)

    context_before = format_context_lines(entries, ctx_before_start, ctx_before_end)
    context_after = format_context_lines(entries, ctx_after_start, ctx_after_end)

    prompt_template = load_prompt("speaker", config)
    prompt = (prompt_template
              .replace("{ARC_CHARACTERS}", arc_chars)
              .replace("{ARC_TITLE}", arc_title)
              .replace("{ARC_SUMMARY}", arc_summary)
              .replace("{CHUNK_TITLE}", chunk.t or f"Chunk {chunk.r[0]}-{chunk.r[1]}")
              .replace("{CHUNK_START}", str(chunk.r[0]))
              .replace("{CHUNK_END}", str(chunk.r[1]))
              .replace("{SCENES_INFO}", scenes_info)
              .replace("{CONTEXT_BEFORE}", context_before)
              .replace("{CONTEXT_AFTER}", context_after)
              .replace("{CHUNK_SRT}", chunk_srt))

    # Tách cached prefix (Bible + rules) khỏi variable (chunk context)
    cached_prefix, variable = split_for_cache(prompt)

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=config.models.medium,
        api_key=config.api_key,
        temperature=0.2,
        max_output=12000,
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    try:
        resp = await call_llm(req, client=client,
                              stage_tag=f"3_speaker_c{chunk.r[0]}")
        tracker.add("3_speaker", resp)
        data = parse_json_response(resp.text, default={"speakers": []})
    except Exception as e:
        logger.warning(f"[Stage 3] Chunk {chunk.r[0]}-{chunk.r[1]} failed: {e}")
        return {}

    # Build scene index map (line → scene_index trong chunk)
    scene_idx_by_line = {}
    for s_idx, sc in enumerate(chunk.scenes):
        for line in range(sc.r[0], sc.r[1] + 1):
            scene_idx_by_line[line] = s_idx

    result = {}
    for entry in data.get("speakers", []) or []:
        try:
            if isinstance(entry, dict):
                line_idx = int(entry.get("line_index") or entry.get("idx", -1))
                speaker_zh = str(entry.get("speaker_zh") or entry.get("speaker", ""))
                confidence = str(entry.get("confidence", "l"))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 3:
                line_idx = int(entry[0])
                speaker_zh = str(entry[1])
                confidence = str(entry[2])
            else:
                continue

            if line_idx < 1:
                continue

            # CHỈ NHẬN line_idx trong chunk (bỏ context AI trả nhầm)
            if not (chunk.r[0] <= line_idx <= chunk.r[1]):
                continue

            # Normalize confidence
            confidence = confidence.lower()
            if confidence not in ("h", "m", "l"):
                if confidence.startswith("h"):
                    confidence = "h"
                elif confidence.startswith("m"):
                    confidence = "m"
                else:
                    confidence = "l"

            result[line_idx] = {
                "speaker_zh": speaker_zh if speaker_zh != "?" else None,
                "confidence": confidence,
                "scene_index": scene_idx_by_line.get(line_idx),
                "chunk_range": chunk.r,
                "arc_index": chunk.arc_index,
            }
        except Exception as e:
            logger.debug(f"[Stage 3] Skip invalid speaker entry: {e}")
            continue

    return result


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 3
# ─────────────────────────────────────────────────────────────────

async def run_stage3_speaker(
    entries: list[SrtEntry],
    bible: Bible,
    chunk_map: ChunkMap,
    config: PipelineConfig,
    tracker: CostTracker,
    on_chunk_done: Optional[callable] = None,
) -> dict[int, dict]:
    """Stage 3 — gán speaker cho toàn phim, theo chunk + context window.

    Mode:
    - config.speaker.parallel = True (mặc định) → song song concurrency speaker
    - config.speaker.parallel = False           → tuần tự, cache hit Bible
    """
    logger.info("=" * 60)
    mode = "PARALLEL" if config.speaker.parallel else "SEQUENTIAL (cache-friendly)"
    logger.info(f"STAGE 3 — SPEAKER (window={config.speaker.context_window}, {mode})")
    logger.info("=" * 60)

    if not chunk_map.chunks:
        logger.warning("[Stage 3] No chunks, skipping")
        return {}

    all_results: dict[int, dict] = {}

    async with httpx.AsyncClient() as client:
        if config.speaker.parallel:
            # SONG SONG
            semaphore = asyncio.Semaphore(config.concurrency.speaker)
            tasks = [
                process_one_chunk(chunk, entries, bible, config, tracker, client, semaphore)
                for chunk in chunk_map.chunks
            ]

            completed = 0
            total = len(tasks)

            for i, coro in enumerate(asyncio.as_completed(tasks)):
                chunk_result = await coro
                all_results.update(chunk_result)
                completed += 1
                if completed % 5 == 0 or completed == total:
                    logger.info(f"[Stage 3] {completed}/{total} chunks done")

                if on_chunk_done:
                    try:
                        res = on_chunk_done(chunk_result)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as e:
                        logger.warning(f"[Stage 3] checkpoint callback failed: {e}")
        else:
            # TUẦN TỰ
            total = len(chunk_map.chunks)
            for i, chunk in enumerate(chunk_map.chunks):
                chunk_result = await process_one_chunk(
                    chunk, entries, bible, config, tracker, client,
                    semaphore=None,
                )
                all_results.update(chunk_result)
                if (i + 1) % 5 == 0 or (i + 1) == total:
                    logger.info(f"[Stage 3] {i+1}/{total} chunks done")

                if on_chunk_done:
                    try:
                        res = on_chunk_done(chunk_result)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as e:
                        logger.warning(f"[Stage 3] checkpoint callback failed: {e}")

    # Stats
    high = sum(1 for r in all_results.values() if r["confidence"] == "h")
    mid = sum(1 for r in all_results.values() if r["confidence"] == "m")
    low = sum(1 for r in all_results.values() if r["confidence"] == "l")
    logger.info(f"[Stage 3] DONE. {len(all_results)} lines assigned. "
                f"high={high}, mid={mid}, low={low}, "
                f"cost so far: ${tracker.total_cost_usd:.4f}")
    return all_results
