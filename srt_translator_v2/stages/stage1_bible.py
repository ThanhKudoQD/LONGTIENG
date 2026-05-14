"""
Stage 1 — Bible v3 (refactored).

2 sub-stages CHẠY TUẦN TỰ để tận dụng prompt cache:
- 1A. Cast + Glossary (1 call heavy) — gộp lại vì cùng cần Hán Việt + ngữ cảnh
- 1B. World + arc summaries (1 call medium) — chạy SAU 1A, cache hit SRT prefix

Lý do gộp/tách:
- Cast & Glossary cùng cần model Pro (heavy) cho Hán Việt chuẩn → gộp tiết kiệm 1 call
- World+Arc cần reasoning về plot/structure → medium model đủ, output ngắn
- Tuần tự (không song song) → call 2 dùng prompt cache của call 1 → giảm 50-90% input cost
"""
from __future__ import annotations
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
# Helpers — split cached prefix vs variable
# ─────────────────────────────────────────────────────────────────

CACHE_MARKER = "━━━ PHẦN BIẾN — CONTEXT ━━━"


def split_for_cache(prompt: str) -> tuple[str, str]:
    """Tách prompt thành (cached_prefix, variable_suffix) tại marker.

    Nếu không có marker → toàn bộ là variable (không cache).
    """
    if CACHE_MARKER in prompt:
        idx = prompt.index(CACHE_MARKER)
        return prompt[:idx], prompt[idx:]
    return "", prompt


# ─────────────────────────────────────────────────────────────────
# 1A. CAST + GLOSSARY (gộp, 1 call heavy)
# ─────────────────────────────────────────────────────────────────

async def stage1a_cast_and_glossary(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> tuple[Cast, Glossary]:
    """Trích xuất nhân vật + thuật ngữ trong 1 call.

    Lý do gộp:
    - Cùng cần đọc toàn bộ SRT (input lớn nhất)
    - Cùng cần Hán Việt chuẩn (model heavy)
    - Cùng cần ngữ cảnh nhân vật để gán xưng hô (TỰ XƯNG ↔ Cast)
    - Output 2 phần độc lập, AI không bị nhầm
    """
    logger.info("[Stage 1A] Extracting Cast + Glossary (1 call)...")

    prompt_template = load_prompt("bible_cast_glossary", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    prompt = prompt_template.replace("{SRT_FULL}", srt_text)

    cached_prefix, variable = split_for_cache(prompt)

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=config.models.heavy,
        api_key=config.api_key,
        temperature=0.2,
        max_output=20000,           # đủ cho cả Cast + Glossary
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    resp = await call_llm(req, client=client, stage_tag="1a_cast_glossary")
    tracker.add("1a_cast_glossary", resp)

    data = parse_json_response(resp.text, default={"characters": [], "terms": []})

    # Parse Cast
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

    # Parse Glossary
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
            logger.warning(f"[Stage 1A] Skip invalid term: {e}")

    logger.info(f"[Stage 1A] Got {len(characters)} characters, {len(terms)} terms")
    return Cast(characters=characters), Glossary(terms=terms)


# ─────────────────────────────────────────────────────────────────
# 1B. WORLD + ARC SUMMARIES (1 call medium, sau 1A để cache hit)
# ─────────────────────────────────────────────────────────────────

async def stage1b_world(
    entries: list[SrtEntry],
    cast: Cast,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> World:
    """Trích xuất bối cảnh + story arcs CÓ TÓM TẮT.

    Chạy SAU 1A → SRT đã được Gemini/OpenAI cache → input cost giảm 50-90%.
    """
    logger.info("[Stage 1B] Extracting World + Arc summaries...")

    prompt_template = load_prompt("bible_world", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)

    # Cast brief để AI biết ai là ai khi tóm tắt arc
    cast_brief = "\n".join(
        f"- {c.zh} → {c.vi} ({c.role}, {c.char})"
        for c in cast.characters[:15]
    )

    prompt = (prompt_template
              .replace("{SRT_FULL}", srt_text)
              .replace("{CAST_BRIEF}", cast_brief)
              .replace("{TOTAL_LINES}", str(len(entries))))

    cached_prefix, variable = split_for_cache(prompt)

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=config.models.medium,
        api_key=config.api_key,
        temperature=0.3,
        max_output=10000,           # tăng vì có arc summaries
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
                summary=arc_data.get("summary", "") or arc_data.get("s", ""),
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
            summary="",
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
    logger.info(f"[Stage 1B] Genre: {world.genre}, {len(arcs)} arcs with summaries")
    return world


def _normalize_arcs(arcs: list[StoryArc], total_lines: int) -> list[StoryArc]:
    """Sửa arcs nếu chia sai (lấn / hở / sai range)."""
    if not arcs:
        return [StoryArc(index=0, r=(1, total_lines), t="Toàn phim", summary="", tone="neutral")]

    arcs = sorted(arcs, key=lambda a: a.r[0])

    fixed = []
    for i, arc in enumerate(arcs):
        start, end = arc.r
        if i == 0:
            start = 1
        elif fixed and start != fixed[-1].r[1] + 1:
            start = fixed[-1].r[1] + 1

        if i == len(arcs) - 1:
            end = total_lines

        if end < start:
            end = start

        fixed.append(StoryArc(
            index=i, r=(start, end),
            t=arc.t, summary=arc.summary, tone=arc.tone,
        ))

    return fixed


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 1
# ─────────────────────────────────────────────────────────────────

async def run_stage1_bible(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
) -> Bible:
    """Stage 1 — Bible v3.

    Order TUẦN TỰ (cache-friendly):
    1A Cast + Glossary (heavy, full SRT)
    1B World + Arc summaries (medium, SRT cached từ 1A → giảm 50-90% input cost)
    """
    logger.info("=" * 60)
    logger.info("STAGE 1 — BIBLE (2 sub-calls, sequential for cache)")
    logger.info("=" * 60)

    async with httpx.AsyncClient() as client:
        # 1A trước — Cast + Glossary gộp
        cast, glossary = await stage1a_cast_and_glossary(entries, config, tracker, client)

        # 1B sau — World + Arc summaries (cache hit SRT từ 1A)
        world = await stage1b_world(entries, cast, config, tracker, client)

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
