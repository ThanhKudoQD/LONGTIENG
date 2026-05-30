"""
Stage 4 — Translate (v3.14).

Cải tiến v3.14:
- BỎ emotion + intensity khỏi output AI (tiết kiệm ~28% output token)
- Output dạng ARRAY COMPACT [line_index, text_v1, text_v2_or_null] thay vì object
- Key "t" thay "translations" (ngắn hơn cho cache prefix)
- Backward-compat: parser vẫn đọc được format object cũ

Trước đó (v3.2):
- Prompt 5 TẦNG: đúng nghĩa / tự nhiên / tone-nhân vật / văn hóa-cảm xúc / không gộp
- Inject GENRE PACK theo bible.world.genre_id
- Câu Việt mượt, có ví dụ ❌→✅ cho tầng 2

Stage 0 đã làm sạch SRT (set text="" cho dòng noise).
Stage 4 SKIP các dòng có text="" khi gửi AI để tiết kiệm token,
và YÊU CẦU AI dịch đầy đủ mọi dòng nhận được (không trả rỗng).
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
# GENRE PACK LOADER
# ─────────────────────────────────────────────────────────────────

_GENRE_PACK_CACHE: dict[str, dict] = {}


def load_genre_pack(genre_id: str, config: PipelineConfig) -> Optional[dict]:
    """Load genre pack JSON theo genre_id (cached in-memory).

    Returns None nếu genre_id="other" hoặc file không tồn tại.
    """
    if not genre_id or genre_id == "other":
        return None

    if genre_id in _GENRE_PACK_CACHE:
        return _GENRE_PACK_CACHE[genre_id]

    # Tìm file trong genre_packs/
    pack_dir = config.prompts_dir.parent / "genre_packs"
    pack_file = pack_dir / f"{genre_id}.json"

    if not pack_file.exists():
        logger.warning(f"[Stage 4] Genre pack file not found: {pack_file}")
        _GENRE_PACK_CACHE[genre_id] = None
        return None

    try:
        with open(pack_file, encoding="utf-8") as f:
            data = json.load(f)
        _GENRE_PACK_CACHE[genre_id] = data
        logger.info(f"[Stage 4] Loaded genre pack: {genre_id} ({data.get('name_vi', '?')})")
        return data
    except Exception as e:
        logger.warning(f"[Stage 4] Failed to load genre pack {genre_id}: {e}")
        _GENRE_PACK_CACHE[genre_id] = None
        return None


def format_genre_pack_for_prompt(pack: Optional[dict]) -> str:
    """Format genre pack thành chuỗi gọn để inject vào prompt.

    Trả về '(Không có genre pack cho phim này)' nếu pack=None.
    """
    if not pack:
        return "(Không có genre pack — dùng quy tắc xưng hô mặc định)"

    out = []
    out.append(f"Thể loại: {pack.get('name_vi', pack.get('id', '?'))}")

    tone = pack.get("tone_signature")
    if tone:
        out.append(f"Tone đặc trưng: {tone}")

    # Xưng hô đặc thù thể loại
    pronouns = pack.get("typical_pronouns") or {}
    if pronouns:
        out.append("\nXưng hô đặc thù thể loại:")
        for k, v in pronouns.items():
            out.append(f"- {k}: {v}")

    # Cách gọi / thuật ngữ
    terms = pack.get("common_terms") or []
    if terms:
        out.append("\nCụm điển hình / chức vụ:")
        for t in terms[:25]:  # giới hạn 25 term tránh quá dài
            zh = t.get("zh", "")
            vi = t.get("vi", "")
            note = t.get("notes") or ""
            note_str = f" — {note}" if note else ""
            out.append(f"- {zh} → {vi}{note_str}")

    # Banned modern (cấm dùng trong thể loại)
    banned = pack.get("banned_modern") or pack.get("banned") or []
    if banned:
        out.append("\nCẤM dùng trong thể loại này:")
        for b in banned:
            out.append(f"✗ {b}")

    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────
# CONTEXT FORMATTING
# ─────────────────────────────────────────────────────────────────

def format_characters_in_chunk(chunk: Chunk, bible: Bible) -> str:
    """Format chi tiết nhân vật trong chunk."""
    chars_in_chunk = set()
    for sc in chunk.scenes:
        chars_in_chunk.update(sc.ch)
    if not chars_in_chunk:
        for c in bible.cast.characters[:15]:
            chars_in_chunk.add(c.zh)

    lines = []
    for ch in bible.cast.characters:
        if ch.zh not in chars_in_chunk:
            continue
        age_str = f", {ch.age}" if ch.age else ""
        lines.append(
            f"- {ch.vi} ({ch.zh}): {ch.g}, {ch.role}{age_str}\n"
            f"    {ch.char}."
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
    """Format scenes của chunk cho prompt (có intensity để Stage 4 shift xưng hô)."""
    if not chunk.scenes:
        return f"(Chunk này không chia scenes, là 1 mạch liền: dòng {chunk.r[0]}-{chunk.r[1]})"

    lines = []
    for i, sc in enumerate(chunk.scenes):
        chars_str = ", ".join(sc.ch)
        tag_str = f" [{sc.tag}]" if sc.tag else ""
        lines.append(
            f"Scene {i+1} (dòng {sc.r[0]}-{sc.r[1]}): "
            f"[{chars_str}], emotion={sc.e}, intensity={sc.intensity}{tag_str}"
        )
    return "\n".join(lines)


def format_dialogue_input(
    chunk: Chunk,
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
) -> str:
    """Format thoại CẦN DỊCH với speaker (KHÔNG duration).

    Bỏ qua dòng đã bị Stage 0 đánh dấu noise (entry.text rỗng) —
    KHÔNG gửi lên AI để tiết kiệm token và tránh confuse AI.
    Index gốc vẫn giữ nguyên (skip line_index trong output là điều bình thường).
    """
    lines = []
    for i in range(chunk.r[0], chunk.r[1] + 1):
        e = entries_by_idx.get(i)
        if not e:
            continue
        # Skip dòng noise (Stage 0 đã set text="")
        if not (e.text or "").strip():
            continue
        speaker_info = speaker_map.get(i, {})
        speaker_zh = speaker_info.get("speaker_zh") or "?"
        lines.append(f"{e.index} | {speaker_zh} | {e.text}")
    return "\n".join(lines) if lines else "(Không có dòng nào trong chunk)"


def format_context_window(
    entries_by_idx: dict[int, SrtEntry],
    speaker_map: dict[int, dict],
    start_line: int,
    end_line: int,
) -> str:
    """Format context trước/sau (sliding window). Chỉ text TQ + speaker.

    Cũng bỏ qua dòng noise như format_dialogue_input.
    """
    if start_line > end_line:
        return "(Không có)"

    lines = []
    for i in range(start_line, end_line + 1):
        e = entries_by_idx.get(i)
        if not e:
            continue
        # Skip dòng noise (Stage 0 đã set text="")
        if not (e.text or "").strip():
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
    """Dịch 1 chunk, return map line_idx → translation info.

    AI tự quyết noise bằng text_v1="".
    """
    async with semaphore:
        # Build context blocks
        characters_in_chunk = format_characters_in_chunk(chunk, bible)
        relationships = format_relationships(chunk, bible)
        glossary_chunk = format_glossary_chunk(chunk, entries_by_idx, bible)
        scenes_in_chunk = format_scenes_in_chunk(chunk)
        dialogue_input = format_dialogue_input(chunk, entries_by_idx, speaker_map)

        # Sliding window context
        overlap = config.chunk.overlap_lines
        context_before = format_context_window(
            entries_by_idx, speaker_map,
            max(1, chunk.r[0] - overlap),
            chunk.r[0] - 1,
        )
        context_after = format_context_window(
            entries_by_idx, speaker_map,
            chunk.r[1] + 1,
            min(len(entries), chunk.r[1] + overlap),
        )

        # Arc info — bao gồm SUMMARY
        arc = bible.world.arcs[chunk.arc_index] if chunk.arc_index < len(bible.world.arcs) else None
        arc_title = arc.t if arc else ""
        arc_tone = arc.tone if arc else "neutral"
        arc_summary = (arc.summary if arc and arc.summary else "(không có tóm tắt)")

        # Load + format Genre Pack theo genre_id từ Bible.world
        genre_pack = load_genre_pack(bible.world.genre_id, config)
        genre_pack_str = format_genre_pack_for_prompt(genre_pack)

        # Build prompt
        prompt = (prompt_template
                  .replace("{CHUNK_TITLE}", chunk.t)
                  .replace("{ARC_TITLE}", arc_title)
                  .replace("{ARC_TONE}", arc_tone)
                  .replace("{ARC_SUMMARY}", arc_summary)
                  .replace("{GENRE_PACK}", genre_pack_str)
                  .replace("{CHARACTERS_IN_CHUNK}", characters_in_chunk)
                  .replace("{RELATIONSHIPS}", relationships)
                  .replace("{GLOSSARY_CHUNK}", glossary_chunk)
                  .replace("{SCENES_IN_CHUNK}", scenes_in_chunk)
                  .replace("{CONTEXT_BEFORE}", context_before)
                  .replace("{CONTEXT_AFTER}", context_after)
                  .replace("{DIALOGUE_INPUT}", dialogue_input))

        # Cached prefix: phần trước "PHẦN BIẾN — CONTEXT CHUNK"
        cached_prefix = None
        if config.cache.enabled:
            split_marker = "PHẦN BIẾN — CONTEXT CHUNK"
            if split_marker in prompt:
                idx = prompt.index(split_marker)
                cached_prefix = prompt[:idx]
                prompt_variable = prompt[idx:]
                if len(cached_prefix) >= config.cache.min_tokens_to_cache * 3:
                    prompt = prompt_variable
                else:
                    cached_prefix = None

        req = LLMRequest(
            prompt=prompt,
            cached_prefix=cached_prefix,
            model=config.models.get_model_for("stage4"),
            api_key=config.get_api_key_for(config.models.get_model_for("stage4")),
            temperature=0.4,
            # v3 FIX: chunk 300 dòng × 2 bản dịch × 80 token = 48K. 16K cũ quá ít,
            # đặc biệt khi thinking=True. Set max — cap_max_output tự giới hạn.
            max_output=65536,
            json_mode=True,
            thinking=config.models.get_thinking_for("stage4"),
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client,
                                  stage_tag=f"4_translate_c{chunk.r[0]}")
            tracker.add("4_translate", resp)
            data = parse_json_response(resp.text, default={"t": []})
        except Exception as e:
            logger.warning(f"[Stage 4] Chunk {chunk.r[0]}-{chunk.r[1]} failed: {e}")
            return {}

        result = {}
        noise_count = 0

        # v3.14: Format mới — array compact [line_index, text_v1, text_v2_or_null]
        # Key: "t" (ngắn hơn "translations" để tiết kiệm cache prefix).
        # Backward-compat: vẫn đọc được format cũ dạng object nếu AI trả nhầm.
        items = data.get("t") or data.get("translations") or []

        for entry in items:
            try:
                # Format mới: array
                if isinstance(entry, list):
                    if len(entry) < 2:
                        continue
                    line_idx = int(entry[0])
                    text_v1_raw = entry[1] if len(entry) >= 2 else None
                    text_v2_raw = entry[2] if len(entry) >= 3 else None
                # Backward-compat: object format cũ
                elif isinstance(entry, dict):
                    line_idx = int(entry.get("line_index", -1))
                    text_v1_raw = entry.get("text_v1")
                    text_v2_raw = entry.get("text_v2")
                else:
                    continue

                if line_idx < 1:
                    continue
                if not (chunk.r[0] <= line_idx <= chunk.r[1]):
                    continue

                text_v1 = (text_v1_raw or "").strip() if isinstance(text_v1_raw, str) else ""
                text_v2 = None
                if isinstance(text_v2_raw, str):
                    text_v2 = text_v2_raw.strip() or None

                # v3.14: Bỏ emotion + intensity khỏi pipeline.
                # Tiết kiệm ~28% output token.
                # Default null trong DB → TTS tự fallback "normal" mode qua
                # voice_modes.emotion_to_mode(None) → "normal".
                result[line_idx] = {
                    "speaker_vi": "",   # không còn dùng (đã có từ Stage 3)
                    "text_v1": text_v1,
                    "text_v2": text_v2,
                    "emotion": None,
                    "intensity": None,
                    "is_noise": False,
                }
            except Exception as e:
                logger.debug(f"[Stage 4] Skip invalid translation: {e}")
                continue

        if noise_count:
            logger.info(f"[Stage 4] Chunk {chunk.r[0]}-{chunk.r[1]}: "
                        f"{noise_count} lines marked as noise by AI")

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
    emotion: Optional[str],
    intensity: Optional[int],
    is_hook: bool,
    is_peak: bool,
    config: PipelineConfig,
) -> bool:
    """Quyết định có giữ text_v2 không (theo config variant.mode).

    AI đã tự quyết v2=null khi thấy trùng v1. Hàm này enforce thêm theo mode user:
    - off: bỏ tất cả v2
    - always: giữ tất cả v2 AI trả
    - important_only: chỉ giữ ở scene quan trọng / emotion mạnh

    v3.14: emotion/intensity giờ có thể là None (Stage 4 không sinh nữa).
    Fallback: dùng is_hook/is_peak từ Stage 2 — vẫn đủ tốt để quyết định.
    """
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

    # v3.14: emotion/intensity có thể None → chỉ check khi có data
    if emotion and emotion in config.variant.important_emotions:
        return True
    if intensity is not None and intensity >= config.variant.important_intensity_min:
        return True
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
    """Stage 4 — dịch toàn phim. AI tự quyết noise."""
    logger.info("=" * 60)
    logger.info("STAGE 4 — TRANSLATE (5 tầng + Genre Pack)")
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

            if on_chunk_done:
                try:
                    res = on_chunk_done(chunk_result)
                    if asyncio.iscoroutine(res):
                        await res
                except Exception as e:
                    logger.warning(f"[Stage 4] checkpoint failed: {e}")

    # Stats
    covered = len(all_results)
    variant_count = sum(1 for r in all_results.values() if r.get("text_v2"))
    noise_count = sum(1 for r in all_results.values() if r.get("is_noise"))
    expected = len(entries)
    missing = expected - covered

    logger.info(f"[Stage 4] DONE. {covered}/{expected} lines, "
                f"{variant_count} variants v2, {noise_count} noise (AI-marked), "
                f"cost so far: ${tracker.total_cost_usd:.4f}")
    if missing > 0:
        logger.warning(f"[Stage 4] {missing} lines NOT translated (will retry in Stage 5)")

    return all_results
