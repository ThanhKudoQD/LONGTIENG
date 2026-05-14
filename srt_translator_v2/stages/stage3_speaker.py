"""
Stage 3 — Speaker (v3).

Logic mới: gán speaker theo CHUNK (đã có từ Bước 2).
- 1 call/chunk
- Phim 6000 dòng ~20-25 chunks = 20-25 calls
- Concurrency 5 song song
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
from models import Bible, Chunk, ChunkMap, Scene

logger = logging.getLogger(__name__)


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
    # Nếu chunk không có scenes → lấy toàn bộ cast (fallback)
    if not chars:
        for c in bible.cast.characters:
            chars.add(c.zh)
    return chars


def format_arc_characters(bible: Bible, chars_in_chunk: set[str]) -> str:
    """Format danh sách nhân vật trong arc + chunk."""
    lines = []
    for ch in bible.cast.characters:
        if ch.zh in chars_in_chunk:
            lines.append(f"- {ch.zh} ({ch.vi}): {ch.g}, {ch.role}, {ch.char}")
    if not lines:
        # Fallback: top characters
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
    """Format SRT của chunk."""
    lines = []
    for e in entries:
        if chunk.r[0] <= e.index <= chunk.r[1]:
            lines.append(f"{e.index} | {e.text}")
    return "\n".join(lines)


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
    semaphore: asyncio.Semaphore,
) -> dict[int, dict]:
    """Gán speaker cho 1 chunk. Return map line_idx → {speaker_zh, confidence, scene_index, chunk_index, arc_index}."""
    async with semaphore:
        chars_in_chunk = get_chunk_characters(chunk, bible)
        arc_chars = format_arc_characters(bible, chars_in_chunk)
        scenes_info = format_scenes_info(chunk)
        chunk_srt = format_chunk_srt(entries, chunk)

        prompt_template = load_prompt("speaker", config)
        prompt = (prompt_template
                  .replace("{ARC_CHARACTERS}", arc_chars)
                  .replace("{SCENES_INFO}", scenes_info)
                  .replace("{CHUNK_SRT}", chunk_srt))

        req = LLMRequest(
            prompt=prompt,
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

                # Normalize confidence
                confidence = confidence.lower()
                if confidence not in ("h", "m", "l"):
                    # Tolerate "high", "mid", "low"
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
    """Stage 3 — gán speaker cho toàn phim, theo chunk.
    
    Có callback on_chunk_done(chunk, result) để checkpoint.
    """
    logger.info("=" * 60)
    logger.info("STAGE 3 — SPEAKER ASSIGNMENT")
    logger.info("=" * 60)

    if not chunk_map.chunks:
        logger.warning("[Stage 3] No chunks, skipping")
        return {}

    semaphore = asyncio.Semaphore(config.concurrency.speaker)
    all_results: dict[int, dict] = {}

    async with httpx.AsyncClient() as client:
        tasks = [
            process_one_chunk(chunk, entries, bible, config, tracker, client, semaphore)
            for chunk in chunk_map.chunks
        ]

        completed = 0
        total = len(tasks)

        # Run với as_completed để checkpoint per chunk
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            chunk_result = await coro
            all_results.update(chunk_result)
            completed += 1
            if completed % 5 == 0 or completed == total:
                logger.info(f"[Stage 3] {completed}/{total} chunks done")

            # Checkpoint callback
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
                f"high={high}, mid={mid}, low={low}")
    return all_results
