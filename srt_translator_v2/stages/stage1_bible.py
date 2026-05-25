"""
Stage 1 — Bible v3.14 (refactored).

3 sub-stages:
- 1A.1 Cast       — parallel với 1A.2, prompt `bible_cast`, output key-shortened
- 1A.2 Glossary   — parallel với 1A.1, prompt `bible_glossary`, output array compact
- 1B   World+Arcs — chạy SAU 1A (cần cast), cache hit SRT prefix từ 1A

v3.14 changes:
- TÁCH 1A thành 2 calls riêng (cast / glossary) → tránh MAX_TOKENS với phim
  dài hoặc nhiều nhân vật, chạy parallel tiết kiệm thời gian
- Output format compact: cast dùng key viết tắt (z/v/a/g/r/y/c/l),
  glossary dùng array [z,v,c,n_or_null] — giảm ~30-40% output token
- Backward-compat parser: vẫn đọc được format object cũ ("characters", "terms")

Lý do thiết kế:
- Cast & Glossary cùng cần model heavy (Hán Việt chuẩn) → cùng cấu hình `stage1a`
- Parallel an toàn vì 2 task ĐỘC LẬP (không phụ thuộc data của nhau)
- World+Arcs vẫn TUẦN TỰ sau 1A (cần cast làm input)
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
# 1A. CAST + GLOSSARY (TÁCH thành 2 calls parallel, cache SRT prefix)
# ─────────────────────────────────────────────────────────────────
#
# v3.14: TÁCH `bible_cast_glossary.txt` thành 2 prompt riêng:
# - `bible_cast.txt`     → chỉ characters (output có thể lớn — 50-100 NV)
# - `bible_glossary.txt` → chỉ terms (output nhỏ — 30-80 terms)
#
# Lý do tách:
# 1. Tránh MAX_TOKENS: gộp khiến phim dài/nhiều NV vượt cap output model
# 2. Output format compact: characters dùng key viết tắt (z/v/a/g/r/y/c/l),
#    glossary dùng array compact [z,v,c,n_or_null]
# 3. Parallel: chạy đồng thời tiết kiệm thời gian (~50%)
# 4. Implicit cache hit: cả 2 prompt cùng kết thúc bằng SRT_FULL ở variable
#    block → Gemini implicit cache khớp prefix instructions → tiết kiệm input
# 5. Retry granular: hỏng cast không phải redo glossary và ngược lại


async def _call_cast(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> Cast:
    """Call AI lấy Cast (characters)."""
    logger.info("[Stage 1A.1] Extracting Cast...")

    prompt_template = load_prompt("bible_cast", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    prompt = prompt_template.replace("{SRT_FULL}", srt_text)
    cached_prefix, variable = split_for_cache(prompt)

    _model = config.models.get_model_for("stage1a_cast")
    _key = config.get_api_key_for(_model)
    _thinking = config.models.get_thinking_for("stage1a_cast")

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=_model,
        api_key=_key,
        # v3.14 FIX: temperature 0.2 → 0.4 cho cast để giảm "repetition loop"
        # (model determinstic quá khi gặp character nhiều cách gọi → lặp alias vô hạn → MAX_TOKENS)
        temperature=0.4,
        max_output=65536,
        json_mode=True,
        thinking=_thinking,
        max_retries=config.concurrency.retry_max,
    )
    logger.info(
        f"[Stage 1A.1] REQUEST: model={_model!r}, "
        f"prompt_len={len(variable if cached_prefix else prompt)}, "
        f"cached_prefix_len={len(cached_prefix) if cached_prefix else 0}"
    )

    resp = await call_llm(req, client=client, stage_tag="1a1_cast")
    tracker.add("1a1_cast", resp)

    logger.info(
        f"[Stage 1A.1] RESPONSE: tokens_in={resp.tokens_in}, "
        f"tokens_out={resp.tokens_out}, cached_tokens={getattr(resp, 'cached_tokens', 0)}, "
        f"finish_reason={getattr(resp, 'finish_reason', '?')!r}"
    )

    data = parse_json_response(resp.text, default={"c": []})

    # v3.14: Đọc cả format mới ("c") và format cũ ("characters") để backward-compat
    characters_raw = data.get("c") or data.get("characters") or []
    characters = []
    dropped_aliases = 0
    dropped_rels = 0
    for ch_data in characters_raw:
        try:
            zh = (ch_data.get("z") or ch_data.get("zh") or "")
            # v3.14 FIX: Dedupe alias chống bug AI loop sinh ra
            # ["商总", "商先生", "商湛", "商湛", "商湛", ...] (lặp 250 lần)
            # → MAX_TOKENS. Dedupe + bỏ tên gốc + cap 5.
            raw_alias = ch_data.get("a") or ch_data.get("alias") or []
            if not isinstance(raw_alias, list):
                raw_alias = []
            # dict.fromkeys giữ thứ tự, loại trùng
            alias = []
            seen_alias = set()
            for a in raw_alias:
                if not isinstance(a, str):
                    continue
                a = a.strip()
                if not a or a == zh or a in seen_alias:
                    continue
                seen_alias.add(a)
                alias.append(a)
                if len(alias) >= 5:
                    break
            dropped_aliases += len(raw_alias) - len(alias)

            # v3.14 FIX: Dedupe rel (cùng zh-name nhiều entry)
            raw_rel = ch_data.get("l") or ch_data.get("rel") or {}
            if not isinstance(raw_rel, dict):
                raw_rel = {}
            rel = {}
            for k, v in raw_rel.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    continue
                k = k.strip()
                v = v.strip()
                if not k or not v or k == zh:
                    continue
                if k not in rel and len(rel) < 6:
                    rel[k] = v
                else:
                    dropped_rels += 1

            # v3.14 FIX: Cap character description 120 ký tự
            char_desc = (ch_data.get("c") or ch_data.get("char") or "")
            if len(char_desc) > 120:
                char_desc = char_desc[:120].rstrip() + "..."

            ch = Character(
                zh=zh,
                vi=(ch_data.get("v") or ch_data.get("vi") or ""),
                alias=alias,
                g=(ch_data.get("g") or "?"),
                role=(ch_data.get("r") or ch_data.get("role") or "phu"),
                age=(ch_data.get("y") or ch_data.get("age")),
                char=char_desc,
                rel=rel,
            )
            characters.append(ch)
        except Exception as e:
            logger.warning(f"[Stage 1A.1] Skip invalid character: {e}")

    if dropped_aliases or dropped_rels:
        logger.warning(
            f"[Stage 1A.1] Dedupe: dropped {dropped_aliases} duplicate aliases, "
            f"{dropped_rels} duplicate rels (AI repetition loop)"
        )

    logger.info(f"[Stage 1A.1] Got {len(characters)} characters")
    return Cast(characters=characters)


async def _call_glossary(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    srt_text: str,
) -> Glossary:
    """Call AI lấy Glossary (terms).

    `srt_text` truyền vào để tránh tính lại format_srt_for_prompt (dùng để filter cuối).
    """
    logger.info("[Stage 1A.2] Extracting Glossary...")

    prompt_template = load_prompt("bible_glossary", config)
    prompt = prompt_template.replace("{SRT_FULL}", srt_text)
    cached_prefix, variable = split_for_cache(prompt)

    _model = config.models.get_model_for("stage1a_glossary")
    _key = config.get_api_key_for(_model)
    _thinking = config.models.get_thinking_for("stage1a_glossary")

    req = LLMRequest(
        prompt=variable if cached_prefix else prompt,
        cached_prefix=cached_prefix if cached_prefix else None,
        model=_model,
        api_key=_key,
        temperature=0.2,
        max_output=32768,  # Glossary output nhỏ hơn cast nhiều
        json_mode=True,
        thinking=_thinking,
        max_retries=config.concurrency.retry_max,
    )
    logger.info(
        f"[Stage 1A.2] REQUEST: model={_model!r}, "
        f"prompt_len={len(variable if cached_prefix else prompt)}, "
        f"cached_prefix_len={len(cached_prefix) if cached_prefix else 0}"
    )

    resp = await call_llm(req, client=client, stage_tag="1a2_glossary")
    tracker.add("1a2_glossary", resp)

    logger.info(
        f"[Stage 1A.2] RESPONSE: tokens_in={resp.tokens_in}, "
        f"tokens_out={resp.tokens_out}, cached_tokens={getattr(resp, 'cached_tokens', 0)}, "
        f"finish_reason={getattr(resp, 'finish_reason', '?')!r}"
    )

    data = parse_json_response(resp.text, default={"t": []})

    # v3.14: Đọc cả format mới ("t" array) và format cũ ("terms" object) — backward-compat
    raw_terms_input = data.get("t") or data.get("terms") or []
    raw_terms: list[GlossaryTerm] = []
    for entry in raw_terms_input:
        try:
            if isinstance(entry, list):
                # Format mới: [z, v, c, n_or_null]
                if len(entry) < 3:
                    continue
                z = entry[0] or ""
                v = entry[1] or ""
                c = entry[2] or "khac"
                n = entry[3] if len(entry) >= 4 else None
                if isinstance(n, str) and not n.strip():
                    n = None
            elif isinstance(entry, dict):
                # Format cũ: object zh/vi/cat/note
                z = entry.get("z") or entry.get("zh") or ""
                v = entry.get("v") or entry.get("vi") or ""
                c = (entry.get("c") or entry.get("cat") or entry.get("category") or "khac")
                n = entry.get("n") or entry.get("note")
            else:
                continue

            raw_terms.append(GlossaryTerm(zh=z, vi=v, cat=c, note=n))
        except Exception as e:
            logger.warning(f"[Stage 1A.2] Skip invalid term: {e}")

    # ━━━ FILTER: bỏ term xuất hiện < 2 lần (trừ cliche) ━━━
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
            logger.debug(f"[Stage 1A.2] Drop term '{term.zh}' (count={actual_count}, cat={term.cat})")

    if dropped:
        logger.info(f"[Stage 1A.2] Dropped {dropped} terms appearing <2 times (kept {len(terms)})")

    logger.info(f"[Stage 1A.2] Got {len(terms)} terms")
    return Glossary(terms=terms)


async def stage1a_cast_and_glossary(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
) -> tuple[Cast, Glossary]:
    """Trích xuất nhân vật + thuật ngữ.

    v3.14: TÁCH thành 2 calls PARALLEL.
    - 1A.1 cast: prompt `bible_cast`, output format key-shortened
    - 1A.2 glossary: prompt `bible_glossary`, output format array compact

    Cả 2 calls cùng kết thúc bằng SRT_FULL → Gemini implicit cache prefix
    chung của instructions; bù lại tăng input vì gửi SRT 2 lần, nhưng tránh
    được MAX_TOKENS khi gộp.
    """
    logger.info("[Stage 1A] Extracting Cast + Glossary (2 parallel calls)...")

    # Format SRT 1 lần dùng chung cho cả 2 calls (cùng input)
    srt_text = format_srt_for_prompt(entries, with_timing=False)

    # Chạy parallel
    import asyncio
    cast, glossary = await asyncio.gather(
        _call_cast(entries, config, tracker, client),
        _call_glossary(entries, config, tracker, client, srt_text),
    )

    logger.info(
        f"[Stage 1A] DONE. {len(cast.characters)} characters, {len(glossary.terms)} terms"
    )
    return cast, glossary


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


# v3.14: Runners độc lập cho 1A.1 (cast) và 1A.2 (glossary) — user có thể
# chạy riêng từng cái trong UI để dễ debug + retry granular.
async def run_stage1a_cast_only(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
) -> Cast:
    """Stage 1A.1 — chỉ trích Cast (characters)."""
    logger.info("=" * 60)
    logger.info("STAGE 1A.1 — CAST ONLY")
    logger.info("=" * 60)
    async with httpx.AsyncClient() as client:
        cast = await _call_cast(entries, config, tracker, client)
    logger.info(f"[Stage 1A.1] DONE. {len(cast.characters)} characters")
    return cast


async def run_stage1a_glossary_only(
    entries: list[SrtEntry],
    config: PipelineConfig,
    tracker: CostTracker,
) -> Glossary:
    """Stage 1A.2 — chỉ trích Glossary (terms)."""
    logger.info("=" * 60)
    logger.info("STAGE 1A.2 — GLOSSARY ONLY")
    logger.info("=" * 60)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    async with httpx.AsyncClient() as client:
        glossary = await _call_glossary(entries, config, tracker, client, srt_text)
    logger.info(f"[Stage 1A.2] DONE. {len(glossary.terms)} terms")
    return glossary


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
