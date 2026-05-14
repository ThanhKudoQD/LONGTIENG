"""
Stage 4 — Translate (v3).

Trái tim pipeline. Dịch theo chunk với:
- 2 bản dịch (text_v1 sát nghĩa, text_v2 thoát ý)
- Sliding window overlap (30-50 dòng trước/sau)
- Checkpoint per chunk (callback save DB)
- Heavy model (Pro hoặc DeepSeek)
"""
from __future__ import annotations
import asyncio
import json
import logging
from typing import Optional, Callable

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry
from models import Bible, Chunk, ChunkMap, Scene, normalize_emotion

logger = logging.getLogger(__name__)


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# CONTEXT FORMATTING
# ─────────────────────────────────────────────────────────────────

def format_characters_in_chunk(chunk: Chunk, bible: Bible) -> str:
    """Format chi tiết nhân vật trong chunk."""
    chars_in_chunk = set()
    for sc in chunk.scenes:
        chars_in_chunk.update(sc.ch)
    # Nếu chunk không có scenes → fallback tất cả cast top
    if not chars_in_chunk:
        for c in bible.cast.characters[:15]:
            chars_in_chunk.add(c.zh)

    lines = []
    for ch in bible.cast.characters:
        if ch.zh not in chars_in_chunk:
            continue
        age_str = f", {ch.age}" if ch.age else ""
        catch_str = f" Câu cửa miệng: \"{ch.catchphrase}\"." if ch.catchphrase else ""
        lines.append(
            f"- {ch.vi} ({ch.zh}): {ch.g}, {ch.role}{age_str}\n"
            f"    {ch.char}.{catch_str}"
        )
    return "\n".join(lines) if lines else "(Không xác định)"


def format_relationships(chunk: Chunk, bible: Bible) -> str:
    """Build relationships giữa các nhân vật trong chunk."""
    chars_in_chunk = set()
    for sc in chunk.scenes:
        chars_in_chunk.update(sc.ch)

    if not chars_in_chunk:
        return "(Không có quan hệ rõ trong chunk)"

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
            other_ch = bible.cast.get_by_zh(other_zh)
            other_vi = other_ch.vi if other_ch else other_zh
            lines.append(f"- {ch.vi} ↔ {other_vi}: {rel}")
    return "\n".join(lines) if lines else "(Không có quan hệ rõ)"


def format_glossary_chunk(chunk: Chunk, entries_by_idx: dict[int, SrtEntry],
                          bible: Bible) -> str:
    """Lọc glossary terms có trong chunk text."""
    chunk_text = ""
    for i in range(chunk.r[0], chunk.r[1] + 1):
        e = entries_by_idx.get(i)
        if e:
            chunk_text += e.text + " "

    relevant = bible.glossary.find_in_text(chunk_text)
    if not relevant:
        return "(Không có thuật ngữ đặc biệt)"

    lines = []
    for term in relevant:
        note = f"  ({term.note})" if term.note else ""
        lines.append(f"- {term.zh} → \"{term.vi}\"{note}")
    return "\n".join(lines)


def format_scenes_in_chunk(chunk: Chunk) -> str:
    """Format scenes của chunk cho prompt."""
    if not chunk.scenes:
        return f"(Chunk này không chia scenes, là 1 mạch liền: dòng {chunk.r[0]}-{chunk.r[1]})"

    lines = []
    for i, sc in enumerate(chunk.scenes):
        chars_str = ", ".join(sc.ch)
        loc_str = f" @ {sc.loc}" if sc.loc else ""
        tag_str = f" [{sc.tag}]" if sc.tag else ""
        lines.append(
            f"Scene {i+1} (dòng {sc.r[0]}-{sc.r[1]}): "
            f"[{chars_str}]{loc_str}, emotion={sc.e}{tag_str}"
        )
    return "\n".join(lines)


def format_dialogue_input(
    chunk: Chunk,
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    bible: Bible,
) -> str:
    """Format thoại CẦN DỊCH với speaker + duration."""
    lines = []
    for i in range(chunk.r[0], chunk.r[1] + 1):
        e = entries_by_idx.get(i)
        if not e:
            continue
        speaker_info = speaker_map.get(i, {})
        speaker_zh = speaker_info.get("speaker_zh") or "?"
        duration = e.end_sec - e.start_sec
        lines.append(f"{e.index} | {speaker_zh} | {e.text} | {duration:.1f}s")
    return "\n".join(lines)


def format_context_window(
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    start_line: int,
    end_line: int,
    label: str = "context",
) -> str:
    """Format context trước/sau (sliding window). Chỉ text TQ + speaker, không dịch."""
    if start_line > end_line:
        return "(Không có)"

    lines = []
    for i in range(start_line, end_line + 1):
        e = entries_by_idx.get(i)
        if not e:
            continue
        speaker_info = speaker_map.get(i, {})
        speaker_zh = speaker_info.get("speaker_zh") or "?"
        lines.append(f"{e.index} | {speaker_zh} | {e.text}")
    return "\n".join(lines) if lines else "(Không có)"


# ─────────────────────────────────────────────────────────────────
# PROCESS 1 CHUNK
# ─────────────────────────────────────────────────────────────────

async def process_one_chunk(
    chunk: Chunk,
    bible: Bible,
    entries: list[SrtEntry],
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    prompt_template: str,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> dict[int, dict]:
    """Dịch 1 chunk, return map line_idx → translation info."""
    async with semaphore:
        # Build context blocks
        characters_in_chunk = format_characters_in_chunk(chunk, bible)
        relationships = format_relationships(chunk, bible)
        glossary_chunk = format_glossary_chunk(chunk, entries_by_idx, bible)
        scenes_in_chunk = format_scenes_in_chunk(chunk)
        dialogue_input = format_dialogue_input(chunk, entries_by_idx, speaker_map, bible)

        # Sliding window context
        overlap = config.chunk.overlap_lines
        context_before = format_context_window(
            entries_by_idx, speaker_map,
            max(1, chunk.r[0] - overlap),
            chunk.r[0] - 1,
            "before",
        )
        context_after = format_context_window(
            entries_by_idx, speaker_map,
            chunk.r[1] + 1,
            min(len(entries), chunk.r[1] + overlap),
            "after",
        )

        # Get arc info
        arc = bible.world.arcs[chunk.arc_index] if chunk.arc_index < len(bible.world.arcs) else None
        arc_title = arc.t if arc else ""
        arc_tone = arc.tone if arc else "neutral"

        # Build prompt
        prompt = (prompt_template
                  .replace("{CHUNK_TITLE}", chunk.t)
                  .replace("{ARC_TITLE}", arc_title)
                  .replace("{ARC_TONE}", arc_tone)
                  .replace("{CHARACTERS_IN_CHUNK}", characters_in_chunk)
                  .replace("{RELATIONSHIPS}", relationships)
                  .replace("{GLOSSARY_CHUNK}", glossary_chunk)
                  .replace("{SCENES_IN_CHUNK}", scenes_in_chunk)
                  .replace("{CONTEXT_BEFORE}", context_before)
                  .replace("{CONTEXT_AFTER}", context_after)
                  .replace("{DIALOGUE_INPUT}", dialogue_input)
                  .replace("{MIN_CHARS}", str(config.variant.min_chars))
                  .replace("{INTENSITY_MIN}", str(config.variant.important_intensity_min)))

        # Cached prefix: phần Bible + rules đầu prompt
        cached_prefix = None
        if config.cache.enabled:
            # Lấy phần header (từ đầu đến trước "PHẦN BIẾN")
            split_marker = "PHẦN BIẾN — CONTEXT CHUNK"
            if split_marker in prompt:
                idx = prompt.index(split_marker)
                cached_prefix = prompt[:idx]
                prompt_variable = prompt[idx:]
                # Chỉ cache nếu đủ dài
                if len(cached_prefix) >= config.cache.min_tokens_to_cache * 3:  # ~3 chars/tok
                    prompt = prompt_variable
                else:
                    cached_prefix = None

        req = LLMRequest(
            prompt=prompt,
            cached_prefix=cached_prefix,
            model=config.models.heavy,
            api_key=config.api_key,
            temperature=0.4,
            max_output=16000,
            json_mode=True,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client,
                                  stage_tag=f"4_translate_c{chunk.r[0]}")
            tracker.add("4_translate", resp)
            data = parse_json_response(resp.text, default={"translations": []})
        except Exception as e:
            logger.warning(f"[Stage 4] Chunk {chunk.r[0]}-{chunk.r[1]} failed: {e}")
            return {}

        result = {}
        for t in data.get("translations", []) or []:
            try:
                line_idx = int(t.get("line_index", -1))
                if line_idx < 1:
                    continue
                result[line_idx] = {
                    "speaker_vi": (t.get("speaker_vi") or "").strip(),
                    "text_v1": (t.get("text_v1") or "").strip() or None,
                    "text_v2": (t.get("text_v2") or "").strip() or None,
                    "emotion": normalize_emotion(t.get("emotion")),
                    "intensity": _clamp_intensity(t.get("intensity")),
                }
            except Exception as e:
                logger.debug(f"[Stage 4] Skip invalid translation: {e}")
                continue

        return result


def _clamp_intensity(val) -> int:
    """Clamp intensity về 1-10."""
    try:
        i = int(float(val))
        return max(1, min(10, i))
    except (TypeError, ValueError):
        return 5


# ─────────────────────────────────────────────────────────────────
# VARIANT FILTERING (sau khi nhận từ AI)
# ─────────────────────────────────────────────────────────────────

def should_keep_variant(
    text_v1: Optional[str],
    text_v2: Optional[str],
    emotion: str,
    intensity: int,
    is_hook: bool,
    is_peak: bool,
    config: PipelineConfig,
) -> bool:
    """Quyết định có giữ text_v2 không (theo config variant.mode)."""
    if not text_v2 or text_v2 == text_v1:
        return False

    mode = config.variant.mode
    if mode == "off":
        return False
    if mode == "always":
        return True

    # important_only
    if not text_v1 or len(text_v1) < config.variant.min_chars:
        return False

    # Important by emotion
    if emotion in config.variant.important_emotions:
        return True

    # Important by intensity
    if intensity >= config.variant.important_intensity_min:
        return True

    # Important by scene tag
    if is_hook or is_peak:
        return True

    return False


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 4
# ─────────────────────────────────────────────────────────────────

async def run_stage4_translate(
    entries: list[SrtEntry],
    bible: Bible,
    chunk_map: ChunkMap,
    speaker_map: dict[int, dict],
    config: PipelineConfig,
    tracker: CostTracker,
    on_chunk_done: Optional[Callable] = None,
) -> dict[int, dict]:
    """Stage 4 — dịch toàn phim theo chunks. Per-chunk checkpoint."""
    logger.info("=" * 60)
    logger.info("STAGE 4 — TRANSLATE")
    logger.info("=" * 60)

    if not chunk_map.chunks:
        logger.warning("[Stage 4] No chunks, skipping")
        return {}

    prompt_template = load_prompt("translate_chunk", config)
    entries_by_idx = {e.index: e for e in entries}

    semaphore = asyncio.Semaphore(config.concurrency.translate)
    all_results: dict[int, dict] = {}

    logger.info(f"[Stage 4] {len(chunk_map.chunks)} chunks, "
                f"concurrency={config.concurrency.translate}, "
                f"variant_mode={config.variant.mode}, "
                f"cache={'on' if config.cache.enabled else 'off'}")

    async with httpx.AsyncClient() as client:
        tasks = [
            process_one_chunk(
                chunk, bible, entries, entries_by_idx, speaker_map,
                prompt_template, config, tracker, client, semaphore,
            )
            for chunk in chunk_map.chunks
        ]

        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            chunk_result = await coro
            all_results.update(chunk_result)
            completed += 1
            if completed % 3 == 0 or completed == total:
                logger.info(f"[Stage 4] {completed}/{total} chunks translated")

            # Checkpoint callback
            if on_chunk_done:
                try:
                    res = on_chunk_done(chunk_result)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    logger.warning(f"[Stage 4] checkpoint failed: {e}")

    # Coverage stats
    covered = len(all_results)
    variant_count = sum(1 for r in all_results.values() if r.get("text_v2"))
    expected = len(entries)
    missing = expected - covered

    logger.info(f"[Stage 4] DONE. {covered}/{expected} lines translated, "
                f"{variant_count} variants")
    if missing > 0:
        logger.warning(f"[Stage 4] {missing} lines NOT translated (will retry in Stage 5)")

    return all_results
