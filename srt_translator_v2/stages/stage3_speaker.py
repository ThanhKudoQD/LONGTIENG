"""
Stage 3 — Speaker (v3 refactored, arc-based).

Chiến lược chạy:
- Arcs chạy SONG SONG (giới hạn config.concurrency.speaker_arcs)
- Chunks trong mỗi arc chạy TUẦN TỰ (cache prefix Bible + carry over speaker chunk trước)

Cải tiến v3.1:
- Carry over speaker N dòng cuối chunk trước → AI có "trí nhớ" nối tiếp
- Inject quan hệ giữa nhân vật (rel) vào prompt
- 4 mẹo phân tích (tên trong câu, gọi-đáp, vừa nói không nói tiếp, xưng hô)
- Sliding window 20 dòng context trước/sau (read-only)
- Cache marker tách Bible+quan hệ+rules (cố định) khỏi chunk context (biến)
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


def format_relationships_in_chunk(bible: Bible, chars_in_chunk: set[str]) -> str:
    """Format quan hệ giữa các nhân vật trong chunk (bilateral, dedup)."""
    if not chars_in_chunk:
        return "(Không có thông tin quan hệ)"

    lines = []
    seen_pairs = set()
    for ch in bible.cast.characters:
        if ch.zh not in chars_in_chunk:
            continue
        for other_zh, rel in ch.rel.items():
            if other_zh not in chars_in_chunk:
                continue
            pair = tuple(sorted([ch.zh, other_zh]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            # Tên Việt cho cả 2 (nếu có)
            other_ch = bible.cast.get_by_zh(other_zh)
            ch_vi = ch.vi or ch.zh
            other_vi = (other_ch.vi if other_ch else None) or other_zh
            lines.append(f"- {ch_vi} ({ch.zh}) ↔ {other_vi} ({other_zh}): {rel}")

    return "\n".join(lines) if lines else "(Không có quan hệ rõ trong chunk)"


def format_carry_over(
    entries: list[SrtEntry],
    prev_results: dict[int, dict],
    chunk_start: int,
    carry_lines: int,
    bible: Bible,
) -> str:
    """Format N dòng CUỐI chunk trước (đã gán speaker) làm 'trí nhớ' cho chunk hiện tại.

    prev_results: speaker map của chunk trước (line_idx → {speaker_zh, confidence, ...})
    Trả về string format: 'line_idx | speaker_vi | text' để AI thấy ngữ cảnh nối tiếp.
    """
    if not prev_results or carry_lines <= 0:
        return "(không có chunk trước — đây là chunk đầu tiên của arc)"

    # Lấy N dòng cuối cùng có speaker trước chunk_start
    sorted_lines = sorted(
        [ln for ln in prev_results.keys() if ln < chunk_start],
        reverse=True,
    )
    target_lines = sorted(sorted_lines[:carry_lines])
    if not target_lines:
        return "(không có chunk trước)"

    out = []
    for ln in target_lines:
        info = prev_results.get(ln, {})
        speaker_zh = info.get("speaker_zh") or "?"
        # Tìm tên Việt nếu có
        ch = bible.cast.get_by_zh(speaker_zh) if speaker_zh != "?" else None
        speaker_display = (ch.vi if ch and ch.vi else speaker_zh)
        # Lấy text gốc
        text = ""
        for e in entries:
            if e.index == ln:
                text = e.text
                break
        out.append(f"{ln} | {speaker_display} ({speaker_zh}) | {text}")

    return "\n".join(out)


def format_scenes_info(chunk: Chunk) -> str:
    """Format scenes trong chunk."""
    if not chunk.scenes:
        return f"(Chunk {chunk.r[0]}-{chunk.r[1]} không chia scenes, là 1 mạch liền)"

    lines = []
    for i, sc in enumerate(chunk.scenes):
        chars_str = ", ".join(sc.ch)
        tag_str = f" [{sc.tag}]" if sc.tag else ""
        lines.append(f"Scene {i+1} ({sc.r[0]}-{sc.r[1]}): [{chars_str}], {sc.e}{tag_str}")
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
    prev_results: Optional[dict[int, dict]] = None,
) -> dict[int, dict]:
    """Gán speaker cho 1 chunk với context window + carry over từ chunk trước."""
    if semaphore is None:
        return await _process_chunk_inner(chunk, entries, bible, config, tracker, client, prev_results)
    else:
        async with semaphore:
            return await _process_chunk_inner(chunk, entries, bible, config, tracker, client, prev_results)


async def _process_chunk_inner(
    chunk: Chunk,
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    prev_results: Optional[dict[int, dict]] = None,
) -> dict[int, dict]:
    chars_in_chunk = get_chunk_characters(chunk, bible)
    arc_chars = format_arc_characters(bible, chars_in_chunk)
    relationships = format_relationships_in_chunk(bible, chars_in_chunk)
    scenes_info = format_scenes_info(chunk)
    chunk_srt = format_chunk_srt(entries, chunk)

    # Arc info
    arc = find_arc_for_chunk(chunk, bible)
    arc_title = arc.t if arc else f"Arc {chunk.arc_index}"
    arc_summary = (arc.summary if arc and arc.summary else "(không có tóm tắt)")

    # Context window (read-only)
    window = config.speaker.context_window
    total_lines = max(e.index for e in entries) if entries else 0
    ctx_before_start = max(1, chunk.r[0] - window)
    ctx_before_end = chunk.r[0] - 1
    ctx_after_start = chunk.r[1] + 1
    ctx_after_end = min(total_lines, chunk.r[1] + window)

    context_before = format_context_lines(entries, ctx_before_start, ctx_before_end)
    context_after = format_context_lines(entries, ctx_after_start, ctx_after_end)

    # Carry over từ chunk trước (đã gán speaker) — tăng accuracy đầu chunk
    carry_over = format_carry_over(
        entries=entries,
        prev_results=prev_results or {},
        chunk_start=chunk.r[0],
        carry_lines=config.speaker.carry_over_lines,
        bible=bible,
    )

    prompt_template = load_prompt("speaker", config)
    prompt = (prompt_template
              .replace("{ARC_CHARACTERS}", arc_chars)
              .replace("{RELATIONSHIPS}", relationships)
              .replace("{ARC_TITLE}", arc_title)
              .replace("{ARC_SUMMARY}", arc_summary)
              .replace("{CHUNK_TITLE}", chunk.t or f"Chunk {chunk.r[0]}-{chunk.r[1]}")
              .replace("{CHUNK_START}", str(chunk.r[0]))
              .replace("{CHUNK_END}", str(chunk.r[1]))
              .replace("{SCENES_INFO}", scenes_info)
              .replace("{CARRY_OVER}", carry_over)
              .replace("{CONTEXT_BEFORE}", context_before)
              .replace("{CONTEXT_AFTER}", context_after)
              .replace("{CHUNK_SRT}", chunk_srt))

    # Tách cached prefix (Bible + rules + 4 mẹo + quan hệ) khỏi variable (chunk context)
    cached_prefix, variable = split_for_cache(prompt)

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=config.models.medium,
        api_key=config.api_key,
        temperature=0.2,
        max_output=12000,
        json_mode=True,
        thinking=config.models.medium_thinking,
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

async def _process_one_arc(
    arc_idx: int,
    arc_chunks: list[Chunk],
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    on_chunk_done: Optional[callable] = None,
) -> dict[int, dict]:
    """Gán speaker cho TẤT CẢ chunks của 1 arc — TUẦN TỰ trong arc.

    Lý do tuần tự:
    - Hit cache prefix (Bible + quan hệ + mẹo) giữa chunks cùng arc
    - Carry over speaker chunk N → chunk N+1 (AI có 'trí nhớ')
    """
    arc_results: dict[int, dict] = {}
    prev_chunk_results: dict[int, dict] = {}

    for chunk in arc_chunks:
        chunk_result = await process_one_chunk(
            chunk, entries, bible, config, tracker, client,
            semaphore=None,
            prev_results=prev_chunk_results,
        )
        arc_results.update(chunk_result)

        # Cập nhật prev_results = chunk vừa gán xong (cho chunk tiếp theo)
        prev_chunk_results = chunk_result

        if on_chunk_done:
            try:
                res = on_chunk_done(chunk_result)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning(f"[Stage 3] checkpoint callback failed: {e}")

    logger.info(f"[Stage 3] Arc {arc_idx}: {len(arc_chunks)} chunks done, "
                f"{len(arc_results)} lines assigned")
    return arc_results


async def run_stage3_speaker(
    entries: list[SrtEntry],
    bible: Bible,
    chunk_map: ChunkMap,
    config: PipelineConfig,
    tracker: CostTracker,
    on_chunk_done: Optional[callable] = None,
) -> dict[int, dict]:
    """Stage 3 — gán speaker theo arc.

    Chiến lược:
    - Arcs chạy SONG SONG (giới hạn bởi config.concurrency.speaker_arcs)
    - Chunks trong mỗi arc chạy TUẦN TỰ (cache prefix + carry over speaker)
    """
    logger.info("=" * 60)
    logger.info(
        f"STAGE 3 — SPEAKER (window={config.speaker.context_window}, "
        f"carry_over={config.speaker.carry_over_lines}, "
        f"arcs_parallel={config.concurrency.speaker_arcs})"
    )
    logger.info("=" * 60)

    if not chunk_map.chunks:
        logger.warning("[Stage 3] No chunks, skipping")
        return {}

    # Group chunks theo arc_index, giữ thứ tự trong arc
    chunks_by_arc: dict[int, list[Chunk]] = {}
    for chunk in chunk_map.chunks:
        chunks_by_arc.setdefault(chunk.arc_index, []).append(chunk)

    # Sort chunks trong mỗi arc theo start_line (đảm bảo tuần tự đúng)
    for arc_idx in chunks_by_arc:
        chunks_by_arc[arc_idx].sort(key=lambda c: c.r[0])

    arc_indices = sorted(chunks_by_arc.keys())
    logger.info(f"[Stage 3] Processing {len(arc_indices)} arcs, "
                f"{sum(len(v) for v in chunks_by_arc.values())} chunks total")

    all_results: dict[int, dict] = {}

    async with httpx.AsyncClient() as client:
        # Semaphore giới hạn số ARC chạy song song
        arc_semaphore = asyncio.Semaphore(config.concurrency.speaker_arcs)

        async def _run_arc_with_sem(arc_idx, arc_chunks):
            async with arc_semaphore:
                return await _process_one_arc(
                    arc_idx, arc_chunks, entries, bible, config, tracker, client,
                    on_chunk_done=on_chunk_done,
                )

        tasks = [
            _run_arc_with_sem(arc_idx, chunks_by_arc[arc_idx])
            for arc_idx in arc_indices
        ]

        for coro in asyncio.as_completed(tasks):
            arc_result = await coro
            all_results.update(arc_result)

    # Stats
    high = sum(1 for r in all_results.values() if r["confidence"] == "h")
    mid = sum(1 for r in all_results.values() if r["confidence"] == "m")
    low = sum(1 for r in all_results.values() if r["confidence"] == "l")
    logger.info(f"[Stage 3] DONE. {len(all_results)} lines assigned. "
                f"high={high}, mid={mid}, low={low}, "
                f"cost so far: ${tracker.total_cost_usd:.4f}")
    return all_results
