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

    _model_1a = config.models.get_model_for("stage1a")
    _key_1a = config.get_api_key_for(_model_1a)
    _thinking_1a = config.models.get_thinking_for("stage1a")

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=_model_1a,
        api_key=_key_1a,
        temperature=0.2,
        # v3 FIX: 20000 quá ít khi thinking=True (thinking tokens ăn budget).
        # Set max (cap_max_output sẽ tự giới hạn theo model: Gemini 2.5 = 65536).
        max_output=65536,
        json_mode=True,
        thinking=_thinking_1a,
        max_retries=config.concurrency.retry_max,
    )

    # v3 DEBUG: log toàn bộ config request (mask key, KHÔNG log prompt text dài)
    logger.info(
        f"[Stage 1A] REQUEST CONFIG: "
        f"model={_model_1a!r}, "
        f"api_key={'***' + _key_1a[-6:] if _key_1a and len(_key_1a) > 6 else ('EMPTY' if not _key_1a else _key_1a)}, "
        f"key_len={len(_key_1a or '')}, "
        f"provider_field={getattr(config, 'provider', '?')!r}, "
        f"temperature=0.2, "
        f"max_output=20000, "
        f"json_mode=True, "
        f"thinking={_thinking_1a!r}, "
        f"max_retries={config.concurrency.retry_max}, "
        f"prompt_len={len(variable if cached_prefix else prompt)}, "
        f"cached_prefix_len={len(cached_prefix) if cached_prefix else 0}, "
        f"entries_count={len(entries)}"
    )

    resp = await call_llm(req, client=client, stage_tag="1a_cast_glossary")
    tracker.add("1a_cast_glossary", resp)

    # v3 DEBUG: log response stats (KHÔNG log text dài, chỉ stats + preview ngắn)
    _resp_preview = (resp.text or "")[:300].replace("\n", " ")
    logger.info(
        f"[Stage 1A] RESPONSE: "
        f"tokens_in={resp.tokens_in}, "
        f"tokens_out={resp.tokens_out}, "
        f"cached_tokens={getattr(resp, 'cached_tokens', 0)}, "
        f"timing_ms={resp.timing_ms}, "
        f"finish_reason={getattr(resp, 'finish_reason', '?')!r}, "
        f"text_len={len(resp.text or '')}, "
        f"preview={_resp_preview!r}"
    )

    data = parse_json_response(resp.text, default={"characters": [], "terms": []})

    # v3 DEBUG: log parsed result
    logger.info(
        f"[Stage 1A] PARSED: "
        f"characters_count={len(data.get('characters', []) or [])}, "
        f"terms_count={len(data.get('terms', []) or [])}, "
        f"top_keys={list(data.keys()) if isinstance(data, dict) else 'NOT_DICT'}"
    )

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
            )
            characters.append(ch)
        except Exception as e:
            logger.warning(f"[Stage 1A] Skip invalid character: {e}")

    # Parse Glossary (KHÔNG còn field n — bỏ vì AI bịa số)
    raw_terms = []
    for t_data in data.get("terms", []) or []:
        try:
            raw_terms.append(GlossaryTerm(
                zh=t_data.get("zh", "") or "",
                vi=t_data.get("vi", "") or "",
                cat=(t_data.get("cat") or t_data.get("category") or "khac") or "khac",
                note=t_data.get("note"),
            ))
        except Exception as e:
            logger.warning(f"[Stage 1A] Skip invalid term: {e}")

    # ━━━ FILTER: bỏ term xuất hiện < 2 lần (trừ cliche) ━━━
    # AI hay phá rule "term phải lặp ≥ 2 lần" — code đếm thật để loại term thừa.
    # Cliche giữ lại dù xuất hiện 1 lần vì là cụm điển hình quan trọng.
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    terms = []
    dropped = 0
    for term in raw_terms:
        if not term.zh:
            continue
        actual_count = srt_text.count(term.zh)
        if actual_count >= 2 or term.cat == "cliche":
            terms.append(term)
        else:
            dropped += 1
            logger.debug(f"[Stage 1A] Drop term '{term.zh}' (count={actual_count}, cat={term.cat})")

    if dropped:
        logger.info(f"[Stage 1A] Dropped {dropped} terms appearing <2 times (kept {len(terms)})")

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

    _model_1b = config.models.get_model_for("stage1b")
    _key_1b = config.get_api_key_for(_model_1b)
    _thinking_1b = config.models.get_thinking_for("stage1b")

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=_model_1b,
        api_key=_key_1b,
        temperature=0.3,
        # v3 FIX: 10000 quá ít khi thinking=True. Set max — cap_max_output tự giới hạn.
        max_output=65536,
        json_mode=True,
        thinking=_thinking_1b,
        max_retries=config.concurrency.retry_max,
    )

    # v3 DEBUG: log toàn bộ config request (mask key, KHÔNG log prompt text dài)
    logger.info(
        f"[Stage 1B] REQUEST CONFIG: "
        f"model={_model_1b!r}, "
        f"api_key={'***' + _key_1b[-6:] if _key_1b and len(_key_1b) > 6 else ('EMPTY' if not _key_1b else _key_1b)}, "
        f"key_len={len(_key_1b or '')}, "
        f"provider_field={getattr(config, 'provider', '?')!r}, "
        f"temperature=0.3, "
        f"max_output=10000, "
        f"json_mode=True, "
        f"thinking={_thinking_1b!r}, "
        f"max_retries={config.concurrency.retry_max}, "
        f"prompt_len={len(variable if cached_prefix else prompt)}, "
        f"cached_prefix_len={len(cached_prefix) if cached_prefix else 0}, "
        f"cast_brief_chars={len(cast.characters)}"
    )

    resp = await call_llm(req, client=client, stage_tag="1b_world")
    tracker.add("1b_world", resp)

    # v3 DEBUG: log response stats
    _resp_preview = (resp.text or "")[:300].replace("\n", " ")
    logger.info(
        f"[Stage 1B] RESPONSE: "
        f"tokens_in={resp.tokens_in}, "
        f"tokens_out={resp.tokens_out}, "
        f"cached_tokens={getattr(resp, 'cached_tokens', 0)}, "
        f"timing_ms={resp.timing_ms}, "
        f"finish_reason={getattr(resp, 'finish_reason', '?')!r}, "
        f"text_len={len(resp.text or '')}, "
        f"preview={_resp_preview!r}"
    )

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
    arcs = _normalize_arcs(arcs, total_lines=len(entries), max_arcs=config.chunk.max_arcs)

    # Parse genre_id + validate (chỉ chấp nhận giá trị hợp lệ để load genre_pack)
    VALID_GENRE_IDS = {
        "modern_ceo_romance",
        "ancient_palace",
        "reborn_revenge",
        "mafia_lord",
        "war_god_return",
        "other",
    }
    raw_genre_id = (data.get("genre_id") or "other").strip()
    if raw_genre_id not in VALID_GENRE_IDS:
        logger.warning(f"[Stage 1B] Invalid genre_id '{raw_genre_id}', fallback to 'other'")
        raw_genre_id = "other"

    world = World(
        genre=data.get("genre", []) or [],
        genre_id=raw_genre_id,
        era=data.get("era", "hiện đại") or "hiện đại",
        tone=data.get("tone", "") or "",
        plot=data.get("plot", "") or "",
        arcs=arcs,
    )
    logger.info(f"[Stage 1B] Genre: {world.genre} (id={world.genre_id}), {len(arcs)} arcs with summaries")
    return world


def _normalize_arcs(arcs: list[StoryArc], total_lines: int, max_arcs: int = 8) -> list[StoryArc]:
    """Sửa arcs nếu chia sai (lấn / hở / sai range).

    Nếu AI trả về > max_arcs → gộp các arc nhỏ liền nhau lại để giảm xuống max_arcs.
    """
    if not arcs:
        return [StoryArc(index=0, r=(1, total_lines), t="Toàn phim", summary="", tone="neutral")]

    arcs = sorted(arcs, key=lambda a: a.r[0])

    # ━━━ HARD CAP max_arcs: gộp arcs nhỏ liền nhau ━━━
    if len(arcs) > max_arcs:
        logger.warning(
            f"[Stage 1B] AI returned {len(arcs)} arcs, exceeds max_arcs={max_arcs}. "
            f"Merging smallest adjacent arcs."
        )
        # Lặp gộp cho đến khi <= max_arcs
        while len(arcs) > max_arcs:
            # Tìm cặp liền nhau có tổng dòng nhỏ nhất → gộp
            min_pair_size = float('inf')
            min_pair_idx = 0
            for i in range(len(arcs) - 1):
                size = (arcs[i].r[1] - arcs[i].r[0]) + (arcs[i+1].r[1] - arcs[i+1].r[0])
                if size < min_pair_size:
                    min_pair_size = size
                    min_pair_idx = i
            # Gộp arcs[min_pair_idx] + arcs[min_pair_idx+1]
            a1 = arcs[min_pair_idx]
            a2 = arcs[min_pair_idx + 1]
            merged = StoryArc(
                index=a1.index,
                r=(a1.r[0], a2.r[1]),
                t=f"{a1.t} & {a2.t}" if a1.t and a2.t else (a1.t or a2.t or "Merged arc"),
                summary=f"{a1.summary} {a2.summary}".strip(),
                tone=a1.tone or a2.tone or "neutral",
            )
            arcs = arcs[:min_pair_idx] + [merged] + arcs[min_pair_idx + 2:]

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
# MAIN STAGE 1 (legacy combined) + Split 1A / 1B runners
# ─────────────────────────────────────────────────────────────────

async def run_stage1a_only(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
) -> tuple[Cast, Glossary]:
    """Stage 1A độc lập — chỉ trích Cast + Glossary.

    Dùng khi user muốn chạy riêng 1A để xem nhân vật trước,
    sửa nếu cần, rồi mới chạy 1B.
    """
    logger.info("=" * 60)
    logger.info("STAGE 1A — CAST + GLOSSARY (standalone)")
    logger.info("=" * 60)
    async with httpx.AsyncClient() as client:
        cast, glossary = await stage1a_cast_and_glossary(entries, config, tracker, client)
    logger.info(f"[Stage 1A] DONE. {len(cast.characters)} cast, {len(glossary.terms)} terms")
    return cast, glossary


async def run_stage1b_only(
    entries: list[SrtEntry],
    cast: Cast,
    config: PipelineConfig,
    tracker: CostTracker,
) -> World:
    """Stage 1B độc lập — chỉ trích World + Arcs.

    Dùng khi 1A đã chạy xong (Bible đã có cast). Stage này cần `cast`
    làm input để biết nhân vật khi tóm tắt arcs.
    """
    logger.info("=" * 60)
    logger.info("STAGE 1B — WORLD + ARCS (standalone)")
    logger.info("=" * 60)
    async with httpx.AsyncClient() as client:
        world = await stage1b_world(entries, cast, config, tracker, client)
    logger.info(f"[Stage 1B] DONE. {len(world.arcs)} arcs, genre_id={world.genre_id}")
    return world


async def run_stage1_bible(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    on_cast_done: Optional[callable] = None,
) -> Bible:
    """Stage 1 — Bible v3 (LEGACY combined runner, vẫn giữ cho run_full).

    Order TUẦN TỰ (cache-friendly):
    1A Cast + Glossary (heavy, full SRT)
    1B World + Arc summaries (medium, SRT cached từ 1A → giảm 50-90% input cost)

    v3.11: thêm `on_cast_done` callback — gọi NGAY sau khi 1A xong với (cast, glossary)
    để caller có thể save Bible PARTIAL (chỉ cast + glossary, chưa có world).
    Nếu 1B bị cancel → caller vẫn giữ được data 1A.
    """
    logger.info("=" * 60)
    logger.info("STAGE 1 — BIBLE (2 sub-calls, sequential for cache)")
    logger.info("=" * 60)

    async with httpx.AsyncClient() as client:
        # 1A trước — Cast + Glossary gộp
        cast, glossary = await stage1a_cast_and_glossary(entries, config, tracker, client)

        # v3.11: callback để caller save partial NGAY sau 1A
        if on_cast_done is not None:
            try:
                await on_cast_done(cast, glossary)
            except Exception as e:
                logger.warning(f"[Stage 1] on_cast_done callback failed: {e}")

        # 1B sau — World + Arc summaries (cache hit SRT từ 1A)
        world = await stage1b_world(entries, cast, config, tracker, client)

    bible = Bible(
        cast=cast,
        world=world,
        glossary=glossary,
        model_used=config.models.get_model_for("stage1"),
    )

    logger.info(f"[Stage 1] DONE. "
                f"{len(cast.characters)} cast, "
                f"{len(world.arcs)} arcs, "
                f"{len(glossary.terms)} terms")
    return bible
