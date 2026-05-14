"""
Stage 2 — Chunks + Scenes (v3).

Logic mới:
- 1 call/arc → AI chia chunks + scenes trong arc đó
- 5 arcs phim 6000 dòng = 5 calls (song song)
- Output compact: scenes là array thay vì object
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry, format_time
from models import Bible, Chunk, Scene, ChunkMap, StoryArc, normalize_emotion

logger = logging.getLogger(__name__)


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def format_arc_srt(entries: list[SrtEntry], arc: StoryArc) -> str:
    """Format SRT của 1 arc với timestamp."""
    lines = []
    for e in entries:
        if arc.r[0] <= e.index <= arc.r[1]:
            lines.append(f"{e.index} | {format_time(e.start_sec)} | {e.text}")
    return "\n".join(lines)


def build_bible_reference(bible: Bible) -> str:
    """Tóm tắt Bible dạng compact để inject vào prompt."""
    ref = {
        "genre": bible.world.genre,
        "era": bible.world.era,
        "characters": [
            {"zh": c.zh, "vi": c.vi, "g": c.g, "role": c.role}
            for c in bible.cast.characters[:30]  # top 30 nhân vật
        ],
        "tone": bible.world.tone,
    }
    return json.dumps(ref, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────
# PARSE SCENES ARRAY
# ─────────────────────────────────────────────────────────────────

def parse_scene_array(arr) -> Optional[Scene]:
    """Parse 1 scene từ array [start, end, [chars], emotion, location, "HOOK"?].
    
    Tolerant: chấp nhận dict cũ luôn.
    """
    try:
        if isinstance(arr, dict):
            # Tolerate dict format
            r = arr.get("r") or [arr.get("start_line", 1), arr.get("end_line", 1)]
            return Scene(
                r=(int(r[0]), int(r[1])),
                ch=arr.get("ch") or arr.get("characters_present", []),
                e=normalize_emotion(arr.get("e") or arr.get("emotion_primary", "neutral")),
                loc=arr.get("loc") or arr.get("location", ""),
                tag=arr.get("tag") or None,
            )

        if not isinstance(arr, (list, tuple)) or len(arr) < 5:
            return None

        start = int(arr[0])
        end = int(arr[1])
        chars = list(arr[2]) if isinstance(arr[2], (list, tuple)) else []
        emotion = normalize_emotion(str(arr[3]))
        location = str(arr[4]) if arr[4] else ""
        tag = arr[5] if len(arr) > 5 and arr[5] in ("HOOK", "PEAK") else None

        return Scene(
            r=(start, end),
            ch=chars,
            e=emotion,
            loc=location,
            tag=tag,
        )
    except Exception as e:
        logger.warning(f"[Stage 2] Skip invalid scene: {e}")
        return None


def parse_chunk_dict(data: dict, arc_index: int) -> Optional[Chunk]:
    """Parse 1 chunk từ dict."""
    try:
        r = data.get("r") or [data.get("start_line", 1), data.get("end_line", 1)]
        if not isinstance(r, (list, tuple)) or len(r) != 2:
            return None

        scenes_raw = data.get("scenes", []) or []
        scenes = []
        for s in scenes_raw:
            sc = parse_scene_array(s)
            if sc:
                scenes.append(sc)

        return Chunk(
            r=(int(r[0]), int(r[1])),
            t=data.get("t", "") or data.get("title", ""),
            arc_index=arc_index,
            scenes=scenes,
        )
    except Exception as e:
        logger.warning(f"[Stage 2] Skip invalid chunk: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# PROCESS 1 ARC
# ─────────────────────────────────────────────────────────────────

async def process_one_arc(
    arc: StoryArc,
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> list[Chunk]:
    """Chia 1 arc thành chunks + scenes."""
    async with semaphore:
        logger.info(f"[Stage 2] Processing arc {arc.index}: \"{arc.t}\" "
                    f"(dòng {arc.r[0]}-{arc.r[1]})")

        prompt_template = load_prompt("chunks_and_scenes", config)
        arc_srt = format_arc_srt(entries, arc)
        bible_ref = build_bible_reference(bible)

        prompt = (prompt_template
                  .replace("{BIBLE_REFERENCE}", bible_ref)
                  .replace("{ARC_INDEX}", str(arc.index))
                  .replace("{ARC_TITLE}", arc.t)
                  .replace("{ARC_TONE}", arc.tone)
                  .replace("{ARC_START}", str(arc.r[0]))
                  .replace("{ARC_END}", str(arc.r[1]))
                  .replace("{ARC_SRT}", arc_srt)
                  .replace("{CHUNK_TARGET}", str(config.chunk.target_lines))
                  .replace("{MAX_CHUNKS}", str(config.chunk.max_chunks_per_arc)))

        req = LLMRequest(
            prompt=prompt,
            model=config.models.medium,
            api_key=config.api_key,
            temperature=0.3,
            max_output=8000,
            json_mode=True,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client,
                                  stage_tag=f"2_chunks_arc{arc.index}")
            tracker.add("2_chunks", resp)
            data = parse_json_response(resp.text, default={"chunks": []})
        except Exception as e:
            logger.warning(f"[Stage 2] Arc {arc.index} failed: {e}. "
                           f"Fallback to 1 chunk for whole arc.")
            return [_fallback_chunk_for_arc(arc)]

        chunks = []
        for c in data.get("chunks", []) or []:
            chunk = parse_chunk_dict(c, arc.index)
            if chunk:
                chunks.append(chunk)

        if not chunks:
            logger.warning(f"[Stage 2] Arc {arc.index}: no chunks parsed, fallback")
            return [_fallback_chunk_for_arc(arc)]

        # Normalize chunks within arc
        chunks = _normalize_chunks(chunks, arc)

        logger.info(f"[Stage 2] Arc {arc.index}: {len(chunks)} chunks, "
                    f"{sum(len(c.scenes) for c in chunks)} scenes total")
        return chunks


def _fallback_chunk_for_arc(arc: StoryArc) -> Chunk:
    """Fallback: 1 chunk cho cả arc nếu AI fail."""
    return Chunk(
        r=arc.r,
        t=arc.t or f"Arc {arc.index}",
        arc_index=arc.index,
        scenes=[],
    )


def _normalize_chunks(chunks: list[Chunk], arc: StoryArc) -> list[Chunk]:
    """Sửa chunks liền nhau, không lấn/hở."""
    if not chunks:
        return [_fallback_chunk_for_arc(arc)]

    chunks = sorted(chunks, key=lambda c: c.r[0])

    fixed = []
    for i, ch in enumerate(chunks):
        start, end = ch.r
        if i == 0:
            start = arc.r[0]
        elif fixed and start != fixed[-1].r[1] + 1:
            start = fixed[-1].r[1] + 1

        if i == len(chunks) - 1:
            end = arc.r[1]

        if end < start:
            end = start

        # Filter scenes trong chunk
        valid_scenes = []
        for sc in ch.scenes:
            if sc.start_line >= start and sc.end_line <= end:
                valid_scenes.append(sc)

        # Normalize scenes within chunk
        valid_scenes = _normalize_scenes(valid_scenes, start, end)

        fixed.append(Chunk(
            r=(start, end),
            t=ch.t,
            arc_index=arc.index,
            scenes=valid_scenes,
        ))

    return fixed


def _normalize_scenes(scenes: list[Scene], chunk_start: int, chunk_end: int) -> list[Scene]:
    """Sửa scenes liền nhau trong chunk."""
    if not scenes:
        return []  # Chunk ngắn, không cần scenes

    scenes = sorted(scenes, key=lambda s: s.r[0])

    fixed = []
    for i, sc in enumerate(scenes):
        start, end = sc.r
        if i == 0:
            start = chunk_start
        elif fixed and start != fixed[-1].r[1] + 1:
            start = fixed[-1].r[1] + 1

        if i == len(scenes) - 1:
            end = chunk_end

        if end < start:
            end = start

        fixed.append(Scene(
            r=(start, end),
            ch=sc.ch,
            e=sc.e,
            loc=sc.loc,
            tag=sc.tag,
        ))

    return fixed


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 2
# ─────────────────────────────────────────────────────────────────

async def run_stage2_chunks(
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
) -> ChunkMap:
    """Stage 2 — chia chunks + scenes cho toàn phim."""
    logger.info("=" * 60)
    logger.info("STAGE 2 — CHUNKS + SCENES")
    logger.info("=" * 60)

    if not bible.world.arcs:
        # Không có arcs → tạo 1 arc giả cho cả phim
        logger.warning("[Stage 2] No arcs in Bible, creating single arc")
        arcs = [StoryArc(index=0, r=(1, len(entries)), t="Toàn phim", tone="neutral")]
    else:
        arcs = bible.world.arcs

    semaphore = asyncio.Semaphore(config.concurrency.chunks)

    async with httpx.AsyncClient() as client:
        tasks = [
            process_one_arc(arc, entries, bible, config, tracker, client, semaphore)
            for arc in arcs
        ]
        results = await asyncio.gather(*tasks)

    all_chunks = []
    for chunks_of_arc in results:
        all_chunks.extend(chunks_of_arc)

    chunk_map = ChunkMap(chunks=all_chunks)
    logger.info(f"[Stage 2] DONE. {len(all_chunks)} chunks total")
    return chunk_map


# Backwards compat
run_stage2_scenes = run_stage2_chunks
