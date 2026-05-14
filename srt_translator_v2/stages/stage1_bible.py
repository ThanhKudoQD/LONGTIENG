"""
Stage 1 — Bible v3.

3 sub-stages chạy song song / tuần tự:
- 1A. Cast: trích xuất nhân vật (heavy model)
- 1B. World: thể loại, plot, arcs (medium model)
- 1C. Glossary: thuật ngữ + xưng hô theo thể loại (medium model)

1A chạy trước (cần xong để 1C tham khảo).
1B + 1C có thể chạy song song sau 1A.
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
from models import (
    Bible, Cast, World, Glossary,
    Character, StoryArc, GlossaryTerm,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# FORMAT SRT cho prompt
# ─────────────────────────────────────────────────────────────────

def format_srt_for_prompt(entries: list[SrtEntry], with_timing: bool = False) -> str:
    """Convert SRT entries thành chuỗi compact để đưa vào prompt."""
    lines = []
    for e in entries:
        if with_timing:
            lines.append(f"{e.index} | {e.start_sec:.1f} | {e.text}")
        else:
            lines.append(f"{e.index} | {e.text}")
    return "\n".join(lines)


def load_prompt(name: str, config: PipelineConfig) -> str:
    """Load 1 prompt template."""
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# 1A. CAST
# ─────────────────────────────────────────────────────────────────

async def stage1a_cast(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> Cast:
    """Trích xuất danh sách nhân vật."""
    logger.info("[Stage 1A] Extracting cast...")

    prompt_template = load_prompt("bible_cast", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    prompt = prompt_template.replace("{SRT_FULL}", srt_text)

    req = LLMRequest(
        prompt=prompt,
        model=config.models.heavy,
        api_key=config.api_key,
        temperature=0.2,
        max_output=16000,
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    resp = await call_llm(req, client=client, stage_tag="1a_cast")
    tracker.add("1a_cast", resp)

    data = parse_json_response(resp.text, default={"characters": []})

    characters = []
    for ch_data in data.get("characters", []) or []:
        try:
            ch = Character(
                zh=ch_data.get("zh", "") or "",
                vi=ch_data.get("vi", "") or "",
                alias=ch_data.get("alias", []) or [],
                g=ch_data.get("g", "?") or "?",
                role=ch_data.get("role", "phu") or "phu",
                age=ch_data.get("age"),
                char=ch_data.get("char", "") or "",
                rel=ch_data.get("rel", {}) or {},
                catchphrase=ch_data.get("catchphrase"),
            )
            characters.append(ch)
        except Exception as e:
            logger.warning(f"[Stage 1A] Skip invalid character: {e}")

    logger.info(f"[Stage 1A] Got {len(characters)} characters")
    return Cast(characters=characters)


# ─────────────────────────────────────────────────────────────────
# 1B. WORLD
# ─────────────────────────────────────────────────────────────────

async def stage1b_world(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> World:
    """Trích xuất bối cảnh + story arcs."""
    logger.info("[Stage 1B] Extracting world + arcs...")

    prompt_template = load_prompt("bible_world", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    prompt = (prompt_template
              .replace("{SRT_FULL}", srt_text)
              .replace("{TOTAL_LINES}", str(len(entries))))

    req = LLMRequest(
        prompt=prompt,
        model=config.models.medium,
        api_key=config.api_key,
        temperature=0.3,
        max_output=8000,
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    resp = await call_llm(req, client=client, stage_tag="1b_world")
    tracker.add("1b_world", resp)

    data = parse_json_response(resp.text, default={})

    arcs = []
    for i, arc_data in enumerate(data.get("arcs", []) or []):
        try:
            r = arc_data.get("r", [1, len(entries)])
            if not isinstance(r, (list, tuple)) or len(r) != 2:
                r = [arc_data.get("start_line", 1), arc_data.get("end_line", len(entries))]
            arcs.append(StoryArc(
                index=arc_data.get("index", i),
                r=(int(r[0]), int(r[1])),
                t=arc_data.get("t", "") or arc_data.get("title", ""),
                tone=arc_data.get("tone", "neutral") or "neutral",
            ))
        except Exception as e:
            logger.warning(f"[Stage 1B] Skip invalid arc: {e}")

    # Fallback: nếu không có arcs → tạo 1 arc duy nhất
    if not arcs:
        logger.warning("[Stage 1B] No arcs returned, creating fallback single arc")
        arcs.append(StoryArc(
            index=0,
            r=(1, len(entries)),
            t="Toàn phim",
            tone="neutral",
        ))

    # Sanity check arcs liền nhau
    arcs = _normalize_arcs(arcs, total_lines=len(entries))

    world = World(
        genre=data.get("genre", []) or [],
        era=data.get("era", "hiện đại") or "hiện đại",
        tone=data.get("tone", "") or "",
        plot=data.get("plot", "") or "",
        arcs=arcs,
    )
    logger.info(f"[Stage 1B] Genre: {world.genre}, {len(arcs)} arcs")
    return world


def _normalize_arcs(arcs: list[StoryArc], total_lines: int) -> list[StoryArc]:
    """Sửa arcs nếu chia sai (lấn / hở / sai range)."""
    if not arcs:
        return [StoryArc(index=0, r=(1, total_lines), t="Toàn phim", tone="neutral")]

    # Sort theo start_line
    arcs = sorted(arcs, key=lambda a: a.r[0])

    fixed = []
    for i, arc in enumerate(arcs):
        start, end = arc.r
        # Arc đầu phải bắt đầu từ 1
        if i == 0:
            start = 1
        # Arc i+1 phải = fixed[-1].end + 1
        elif fixed and start != fixed[-1].r[1] + 1:
            start = fixed[-1].r[1] + 1

        # Arc cuối phải end = total_lines
        if i == len(arcs) - 1:
            end = total_lines

        # End phải >= start
        if end < start:
            end = start

        fixed.append(StoryArc(index=i, r=(start, end), t=arc.t, tone=arc.tone))

    return fixed


# ─────────────────────────────────────────────────────────────────
# 1C. GLOSSARY
# ─────────────────────────────────────────────────────────────────

async def stage1c_glossary(
    entries: list[SrtEntry],
    cast: Cast,
    world: World,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> Glossary:
    """Trích xuất glossary (gộp thuật ngữ riêng + xưng hô thể loại)."""
    logger.info("[Stage 1C] Extracting glossary...")

    prompt_template = load_prompt("bible_glossary", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)

    # Bible reference tóm tắt cho prompt
    bible_ref = {
        "characters_zh": [c.zh for c in cast.characters if c.zh],
        "genre": world.genre,
        "era": world.era,
    }
    bible_ref_str = json.dumps(bible_ref, ensure_ascii=False, indent=2)

    prompt = (prompt_template
              .replace("{SRT_FULL}", srt_text)
              .replace("{BIBLE_REFERENCE}", bible_ref_str))

    req = LLMRequest(
        prompt=prompt,
        model=config.models.medium,
        api_key=config.api_key,
        temperature=0.2,
        max_output=8000,
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    resp = await call_llm(req, client=client, stage_tag="1c_glossary")
    tracker.add("1c_glossary", resp)

    data = parse_json_response(resp.text, default={"terms": []})

    terms = []
    for t_data in data.get("terms", []) or []:
        try:
            terms.append(GlossaryTerm(
                zh=t_data.get("zh", "") or "",
                vi=t_data.get("vi", "") or "",
                cat=(t_data.get("cat") or t_data.get("category") or "khac") or "khac",
                n=int(t_data.get("n", 0)),
                note=t_data.get("note"),
            ))
        except Exception as e:
            logger.warning(f"[Stage 1C] Skip invalid term: {e}")

    logger.info(f"[Stage 1C] Got {len(terms)} glossary terms")
    return Glossary(terms=terms)


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 1
# ─────────────────────────────────────────────────────────────────

async def run_stage1_bible(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
) -> Bible:
    """Stage 1 — Bible đầy đủ.

    Order:
    1A Cast trước (đồng bộ)
    1B World + 1C Glossary song song (cần Cast cho 1C)
    """
    logger.info("=" * 60)
    logger.info("STAGE 1 — BIBLE")
    logger.info("=" * 60)

    async with httpx.AsyncClient() as client:
        # 1A trước
        cast = await stage1a_cast(entries, config, tracker, client)

        # 1B + 1C song song
        world_task = stage1b_world(entries, config, tracker, client)
        glossary_task = stage1c_glossary(entries, cast, World(), config, tracker, client)

        world, glossary = await asyncio.gather(world_task, glossary_task)

    bible = Bible(
        cast=cast,
        world=world,
        glossary=glossary,
        model_used=config.models.heavy,
    )

    logger.info(f"[Stage 1] DONE. "
                f"{len(cast.characters)} cast, "
                f"{len(world.arcs)} arcs, "
                f"{len(glossary.terms)} terms")
    return bible
