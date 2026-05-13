"""
Stage 1 — Bible.

Đọc SRT toàn phim, sinh:
- 1A. Cast: danh sách nhân vật
- 1B. World + Story Arc: bối cảnh, cốt truyện
- 1C. Glossary: thuật ngữ riêng
- 1D. Genre Pack matcher: chọn pack phù hợp + merge

Chạy 1A trước (cần cho 1B + 1C), rồi 1B+1C song song.
"""
from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry, format_time
from models import (
    Bible, Cast, World, Glossary, GenrePack,
    Character, Pronouns, StoryArc, GlossaryTerm,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# SRT FORMATTING cho prompt
# ─────────────────────────────────────────────────────────────────

def format_srt_for_prompt(entries: list[SrtEntry], with_timing: bool = True) -> str:
    """Convert SRT entries thành chuỗi compact để đưa vào prompt."""
    lines = []
    for e in entries:
        if with_timing:
            lines.append(f"{e.index} | {e.start_sec:.1f}-{e.end_sec:.1f} | {e.text}")
        else:
            lines.append(f"{e.index} | {e.text}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────
# PROMPT LOADING
# ─────────────────────────────────────────────────────────────────

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
    """Sinh danh sách nhân vật từ SRT."""
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

    resp = await call_llm(req, client=client)
    tracker.add("1a_cast", resp)

    data = parse_json_response(resp.text, default={"characters": []})

    characters = []
    for ch_data in data.get("characters", []):
        try:
            # Map nested fields safely
            self_address_data = ch_data.get("self_address", {})
            if isinstance(self_address_data, str):
                # Edge case: LLM returns string instead of object
                self_address_data = {"default": self_address_data}

            ch = Character(
                zh=ch_data.get("zh", ""),
                vi=ch_data.get("vi", ""),
                aliases_zh=ch_data.get("aliases_zh", []) or [],
                aliases_vi=ch_data.get("aliases_vi", []) or [],
                role=ch_data.get("role", "phu"),
                gender=ch_data.get("gender", "?"),
                age_group=ch_data.get("age_group"),
                social_status=ch_data.get("social_status"),
                personality=ch_data.get("personality", "") or "",
                speaking_style=ch_data.get("speaking_style", "") or "",
                self_address=Pronouns(**{k: v for k, v in self_address_data.items()
                                          if k in Pronouns.model_fields}),
                addresses=ch_data.get("addresses", {}) or {},
                relationships=ch_data.get("relationships", {}) or {},
                notes=ch_data.get("notes", "") or "",
            )
            if ch.zh:  # bỏ entry rỗng
                characters.append(ch)
        except Exception as e:
            logger.warning(f"[1A] Skipped malformed character: {e}; data={ch_data}")

    logger.info(f"[Stage 1A] Found {len(characters)} characters")
    return Cast(characters=characters)


# ─────────────────────────────────────────────────────────────────
# 1B. WORLD + STORY ARC
# ─────────────────────────────────────────────────────────────────

async def stage1b_world(
    entries: list[SrtEntry],
    cast: Cast,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> World:
    """Sinh world + story arc."""
    logger.info("[Stage 1B] Building world & story arcs...")
    prompt_template = load_prompt("bible_world", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    cast_json = cast.model_dump_json(indent=2, exclude_none=True)
    prompt = (prompt_template
              .replace("{CAST_JSON}", cast_json)
              .replace("{SRT_FULL}", srt_text))

    req = LLMRequest(
        prompt=prompt,
        model=config.models.heavy,
        api_key=config.api_key,
        temperature=0.3,
        max_output=8000,
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    resp = await call_llm(req, client=client)
    tracker.add("1b_world", resp)

    data = parse_json_response(resp.text, default={})

    arcs = []
    for arc_data in data.get("story_arcs", []) or []:
        try:
            arcs.append(StoryArc(
                index=arc_data.get("index", len(arcs)),
                title=arc_data.get("title", ""),
                summary=arc_data.get("summary", ""),
                start_line=arc_data.get("start_line", 1),
                end_line=arc_data.get("end_line", len(entries)),
                emotional_tone=arc_data.get("emotional_tone", ""),
                key_events=arc_data.get("key_events", []) or [],
            ))
        except Exception as e:
            logger.warning(f"[1B] Skipped malformed arc: {e}")

    world = World(
        genre_main=data.get("genre_main", "khong_xac_dinh"),
        genre_sub=data.get("genre_sub", []) or [],
        era=data.get("era"),
        setting=data.get("setting"),
        plot_summary=data.get("plot_summary", "") or "",
        main_conflict=data.get("main_conflict", "") or "",
        tone_overall=data.get("tone_overall", "") or "",
        story_arcs=arcs,
    )

    logger.info(f"[Stage 1B] Genre: {world.genre_main} / {world.genre_sub}, "
                f"{len(arcs)} story arcs")
    return world


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
    """Sinh glossary thuật ngữ riêng phim."""
    logger.info("[Stage 1C] Building glossary...")
    prompt_template = load_prompt("bible_glossary", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)

    cast_compact = json.dumps([
        {"zh": c.zh, "vi": c.vi, "role": c.role}
        for c in cast.characters
    ], ensure_ascii=False, indent=2)

    world_compact = json.dumps({
        "genre_main": world.genre_main,
        "genre_sub": world.genre_sub,
        "era": world.era,
        "setting": world.setting,
        "plot_summary": world.plot_summary,
    }, ensure_ascii=False, indent=2)

    prompt = (prompt_template
              .replace("{CAST_JSON}", cast_compact)
              .replace("{WORLD_JSON}", world_compact)
              .replace("{SRT_FULL}", srt_text))

    req = LLMRequest(
        prompt=prompt,
        model=config.models.heavy,
        api_key=config.api_key,
        temperature=0.2,
        max_output=8000,
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    resp = await call_llm(req, client=client)
    tracker.add("1c_glossary", resp)

    data = parse_json_response(resp.text, default={"terms": []})

    terms = []
    for t_data in data.get("terms", []) or []:
        try:
            terms.append(GlossaryTerm(
                zh=t_data.get("zh", ""),
                vi=t_data.get("vi", ""),
                category=t_data.get("category", "other"),
                notes=t_data.get("notes", "") or "",
            ))
        except Exception as e:
            logger.warning(f"[1C] Skipped term: {e}")

    logger.info(f"[Stage 1C] Found {len(terms)} glossary terms")
    return Glossary(terms=terms)


# ─────────────────────────────────────────────────────────────────
# 1D. GENRE PACK MATCHER
# ─────────────────────────────────────────────────────────────────

def load_genre_pack(pack_id: str, config: PipelineConfig) -> Optional[GenrePack]:
    """Load 1 genre pack từ disk."""
    path = config.genre_packs_dir / f"{pack_id}.json"
    if not path.exists():
        logger.warning(f"[Genre Pack] Not found: {pack_id}")
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        terms = [GlossaryTerm(**t) for t in data.get("common_terms", [])]
        cliches = [GlossaryTerm(**t) for t in data.get("common_cliches", [])]

        return GenrePack(
            id=data["id"],
            name_vi=data["name_vi"],
            name_zh=data["name_zh"],
            description=data["description"],
            tone_signature=data.get("tone_signature", ""),
            typical_pronouns=data.get("typical_pronouns", {}),
            common_terms=terms,
            common_cliches=cliches,
            translation_examples=data.get("translation_examples", []),
            style_notes=data.get("style_notes", ""),
        )
    except Exception as e:
        logger.error(f"[Genre Pack] Failed to load {pack_id}: {e}")
        return None


def list_available_packs(config: PipelineConfig) -> list[str]:
    """Liệt kê các pack có sẵn."""
    return [p.stem for p in config.genre_packs_dir.glob("*.json")]


def auto_match_genre_pack(world: World, available_packs: list[str]) -> Optional[str]:
    """Match genre pack đơn giản theo genre tags."""
    sub = set(world.genre_sub or [])
    main = world.genre_main

    # Priority match
    if "tong_tai" in sub and main == "do_thi":
        return "modern_ceo_romance"
    if "trong_sinh" in sub and "bao_thu" in sub:
        return "reborn_revenge"
    if "chien_than" in sub:
        return "war_god_return"
    if "hac_dao" in sub:
        return "mafia_lord"
    if "cung_dau" in sub or main == "co_trang":
        return "ancient_palace"

    # Fallback - đô thị mặc định
    if main == "do_thi":
        return "modern_ceo_romance"

    return None


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 1 ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────

async def run_stage1_bible(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
) -> Bible:
    """Chạy Stage 1 đầy đủ.

    Tối ưu: 1B + 1C chạy SONG SONG sau khi 1A xong.
    1C dùng world placeholder (chỉ cần Cast để filter terms) — chấp nhận
    chất lượng glossary giảm nhẹ để đổi lấy ~40% tốc độ.
    """
    logger.info("=" * 60)
    logger.info("STAGE 1 — BIBLE")
    logger.info("=" * 60)

    async with httpx.AsyncClient() as client:
        # 1A — Cast trước (cần cho 1B + 1C)
        cast = await stage1a_cast(entries, config, tracker, client)

        # 1B (World) + 1C (Glossary) chạy SONG SONG.
        # 1C dùng World rỗng (placeholder) — không lý tưởng nhưng nhanh.
        placeholder_world = World()
        world_task = stage1b_world(entries, cast, config, tracker, client)
        glossary_task = stage1c_glossary(entries, cast, placeholder_world,
                                          config, tracker, client)
        world, glossary = await asyncio.gather(world_task, glossary_task)

    # 1D — Match Genre Pack
    if config.genre_pack:
        pack_id = config.genre_pack
        logger.info(f"[Stage 1D] Using user-specified pack: {pack_id}")
    else:
        available = list_available_packs(config)
        pack_id = auto_match_genre_pack(world, available)
        if pack_id:
            logger.info(f"[Stage 1D] Auto-matched genre pack: {pack_id}")
        else:
            logger.info("[Stage 1D] No genre pack matched")

    # Merge Genre Pack terms vào Glossary
    if pack_id:
        pack = load_genre_pack(pack_id, config)
        if pack:
            existing_zh = {t.zh for t in glossary.terms}
            merged_count = 0
            for term in pack.common_terms + pack.common_cliches:
                if term.zh not in existing_zh:
                    glossary.terms.append(term)
                    merged_count += 1
            logger.info(f"[Stage 1D] Merged {merged_count} terms from Genre Pack")

    bible = Bible(
        cast=cast,
        world=world,
        glossary=glossary,
        genre_pack_id=pack_id,
    )

    logger.info(f"[Stage 1] DONE. Cast: {len(cast.characters)}, "
                f"Arcs: {len(world.story_arcs)}, Terms: {len(glossary.terms)}")
    return bible