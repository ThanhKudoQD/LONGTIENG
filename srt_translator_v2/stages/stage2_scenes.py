"""
Stage 2 — Chunks + Scenes (v3 refactored).

Cải tiến:
- Cache marker tách BIBLE (cố định) khỏi ARC (biến) → mỗi arc gọi LLM
  thì BIBLE được cache, giảm 50-90% input cost
- Inject arc.summary vào prompt làm context dẫn dắt AI chia chunks
  theo đúng mạch truyện
- Toggle config.chunk.parallel:
    · True  → chạy song song (nhanh, không cache hit giữa arcs)
    · False → tuần tự (chậm hơn ~30%, cache hit Bible giảm 50-90% cost)

Output compact: scenes là array thay vì object.
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


# ─────────────────────────────────────────────────────────────────
# Cache marker (đồng bộ với prompt template)
# ─────────────────────────────────────────────────────────────────

CACHE_MARKER = "━━━ PHẦN BIẾN — CONTEXT ARC ━━━"


def split_for_cache(prompt: str) -> tuple[str, str]:
    """Tách prompt thành (cached_prefix, variable) tại marker.

    cached_prefix = phần BIBLE + rules (giống nhau xuyên mọi arc)
    variable = phần ARC riêng (summary, range, SRT)
    """
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

def format_arc_srt(entries: list[SrtEntry], arc: StoryArc) -> str:
    """Format SRT của 1 arc với timestamp."""
    lines = []
    for e in entries:
        if arc.r[0] <= e.index <= arc.r[1]:
            lines.append(f"{e.index} | {format_time(e.start_sec)} | {e.text}")
    return "\n".join(lines)


def build_bible_reference(bible: Bible) -> str:
    """Tóm tắt Bible dạng compact để inject vào prompt.

    PHẦN NÀY ĐƯỢC CACHE — phải GIỐNG NHAU xuyên mọi arc, không inject
    field riêng arc vào đây.
    """
    ref = {
        "genre": bible.world.genre,
        "era": bible.world.era,
        "tone": bible.world.tone,
        "plot": bible.world.plot,
        "characters": [
            {"zh": c.zh, "vi": c.vi, "g": c.g, "role": c.role}
            for c in bible.cast.characters[:30]
        ],
    }
    return json.dumps(ref, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────────────────────────────
# PARSE
# ─────────────────────────────────────────────────────────────────

def parse_scene_array(arr) -> Optional[Scene]:
    """Parse 1 scene từ array [start, end, [chars], emotion, location, "HOOK"?]."""
    try:
        if isinstance(arr, dict):
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
    semaphore: Optional[asyncio.Semaphore],
) -> list[Chunk]:
    """Chia 1 arc thành chunks + scenes.

    Mỗi call dùng cached_prefix = phần Bible + rules → cache hit từ arc thứ 2.
    """
    if semaphore is None:
        # Tuần tự — không cần lock
        return await _process_arc_inner(arc, entries, bible, config, tracker, client)
    else:
        async with semaphore:
            return await _process_arc_inner(arc, entries, bible, config, tracker, client)


async def _process_arc_inner(
    arc: StoryArc,
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> list[Chunk]:
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
              .replace("{ARC_SUMMARY}", arc.summary or "(không có tóm tắt)")
              .replace("{ARC_START}", str(arc.r[0]))
              .replace("{ARC_END}", str(arc.r[1]))
              .replace("{ARC_SRT}", arc_srt)
              .replace("{CHUNK_TARGET}", str(config.chunk.target_lines))
              .replace("{MAX_CHUNKS}", str(config.chunk.max_chunks_per_arc)))

    # Tách cached prefix
    cached_prefix, variable = split_for_cache(prompt)

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=config.models.medium,
        api_key=config.api_key,
        temperature=0.3,
        max_output=8000,
        json_mode=True,
        thinking=config.models.medium_thinking,
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

    chunks = _normalize_chunks(chunks, arc)

    logger.info(f"[Stage 2] Arc {arc.index}: {len(chunks)} chunks, "
                f"{sum(len(c.scenes) for c in chunks)} scenes total")
    return chunks


def _fallback_chunk_for_arc(arc: StoryArc) -> Chunk:
    return Chunk(
        r=arc.r,
        t=arc.t or f"Arc {arc.index}",
        arc_index=arc.index,
        scenes=[],
    )


def _normalize_chunks(chunks: list[Chunk], arc: StoryArc) -> list[Chunk]:
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

        valid_scenes = []
        for sc in ch.scenes:
            if sc.start_line >= start and sc.end_line <= end:
                valid_scenes.append(sc)

        valid_scenes = _normalize_scenes(valid_scenes, start, end)

        fixed.append(Chunk(
            r=(start, end),
            t=ch.t,
            arc_index=arc.index,
            scenes=valid_scenes,
        ))

    return fixed


def _normalize_scenes(scenes: list[Scene], chunk_start: int, chunk_end: int) -> list[Scene]:
    if not scenes:
        return []

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
    """Stage 2 — chia chunks + scenes cho toàn phim.

    Mode:
    - config.chunk.parallel = False (mặc định) → tuần tự, cache hit Bible
    - config.chunk.parallel = True             → song song, không cache giữa arcs
    """
    logger.info("=" * 60)
    mode = "PARALLEL" if config.chunk.parallel else "SEQUENTIAL (cache-friendly)"
    logger.info(f"STAGE 2 — CHUNKS + SCENES ({mode})")
    logger.info("=" * 60)

    if not bible.world.arcs:
        logger.warning("[Stage 2] No arcs in Bible, creating single arc")
        arcs = [StoryArc(index=0, r=(1, len(entries)), t="Toàn phim",
                         summary="", tone="neutral")]
    else:
        arcs = bible.world.arcs

    all_chunks: list[Chunk] = []

    async with httpx.AsyncClient() as client:
        if config.chunk.parallel:
            # SONG SONG — nhanh nhưng không cache hit Bible giữa các arc
            semaphore = asyncio.Semaphore(config.concurrency.chunks)
            tasks = [
                process_one_arc(arc, entries, bible, config, tracker, client, semaphore)
                for arc in arcs
            ]
            results = await asyncio.gather(*tasks)
            for chunks_of_arc in results:
                all_chunks.extend(chunks_of_arc)
        else:
            # TUẦN TỰ — chậm hơn nhưng cache hit từ arc thứ 2 → giảm 50-90% input cost
            for arc in arcs:
                chunks_of_arc = await process_one_arc(
                    arc, entries, bible, config, tracker, client,
                    semaphore=None,
                )
                all_chunks.extend(chunks_of_arc)

    chunk_map = ChunkMap(chunks=all_chunks)
    logger.info(f"[Stage 2] DONE. {len(all_chunks)} chunks total, "
                f"cost so far: ${tracker.total_cost_usd:.4f}")
    return chunk_map


# Backwards compat
run_stage2_scenes = run_stage2_chunks
