"""
Stage 3 — Speaker Assignment.

v3 strategy: gom nhiều scenes liền nhau thành 1 batch ~N dòng (config.batch.speaker_lines_per_call)
để giảm số calls + chia sẻ Bible context. Mỗi batch vẫn giữ scene boundary trong prompt
để LLM biết khi nào đổi cảnh.
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
from models import Bible, Scene, SceneMap, SubtitleLine

logger = logging.getLogger(__name__)


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# Batching: gom scenes thành batches ~N dòng
# ─────────────────────────────────────────────────────────────────

def build_scene_batches(scenes: list[Scene], lines_per_call: int) -> list[list[Scene]]:
    """Gom các scenes LIỀN NHAU thành 1 batch sao cho tổng dòng ≈ lines_per_call.

    Không tách scene ra giữa chừng (giữ boundary tự nhiên).
    Scene đơn lẻ vượt lines_per_call vẫn tự thành 1 batch.
    """
    batches: list[list[Scene]] = []
    current: list[Scene] = []
    current_lines = 0

    for sc in scenes:
        sc_len = sc.end_line - sc.start_line + 1
        # Nếu thêm scene này vượt threshold VÀ current đã có scene → flush
        if current and (current_lines + sc_len > lines_per_call):
            batches.append(current)
            current = [sc]
            current_lines = sc_len
        else:
            current.append(sc)
            current_lines += sc_len

    if current:
        batches.append(current)
    return batches


def format_batch_dialogue(scenes: list[Scene], entries_by_idx: dict[int, SrtEntry]) -> str:
    """Format thoại của 1 batch gồm nhiều scenes, có marker scene boundary."""
    parts = []
    for sc in scenes:
        parts.append(f"=== SCENE {sc.index} — {sc.location or '?'} | "
                     f"emotion: {sc.emotion_primary} ===")
        if sc.summary:
            parts.append(f"   (tóm tắt: {sc.summary})")
        if sc.characters_present:
            parts.append(f"   (nhân vật mặt: {', '.join(sc.characters_present)})")
        for i in range(sc.start_line, sc.end_line + 1):
            e = entries_by_idx.get(i)
            if e:
                parts.append(f"{e.index} | {e.text}")
        parts.append("")  # blank line giữa scenes
    return "\n".join(parts).rstrip()


async def process_one_batch(
    batch: list[Scene],
    bible: Bible,
    entries_by_idx: dict[int, SrtEntry],
    prompt_template: str,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> dict[int, dict]:
    """Process 1 batch (nhiều scenes liền), trả về map line_index -> speaker info."""
    async with semaphore:
        cast_compact = json.dumps([
            {
                "zh": c.zh,
                "vi": c.vi,
                "role": c.role,
                "gender": c.gender,
                "speaking_style": c.speaking_style,
                "self_address_default": c.self_address.default,
            }
            for c in bible.cast.characters
        ], ensure_ascii=False, indent=2)

        glossary_compact = json.dumps([
            {"zh": t.zh, "vi": t.vi}
            for t in bible.glossary.terms if t.category in ("title", "nickname")
        ], ensure_ascii=False, indent=2)

        dialogue = format_batch_dialogue(batch, entries_by_idx)

        # Aggregate context cho batch
        first_scene = batch[0]
        last_scene = batch[-1]
        scene_range = f"{first_scene.index}-{last_scene.index}" if len(batch) > 1 else str(first_scene.index)
        all_chars_present = sorted({c for sc in batch for c in sc.characters_present})

        prompt = (prompt_template
                  .replace("{CAST_JSON}", cast_compact)
                  .replace("{GLOSSARY_JSON}", glossary_compact)
                  .replace("{SCENE_INDEX}", scene_range)
                  .replace("{SCENE_LOCATION}", "nhiều cảnh" if len(batch) > 1 else (first_scene.location or ""))
                  .replace("{SCENE_EMOTION}", f"{first_scene.emotion_primary} → {last_scene.emotion_primary}")
                  .replace("{SCENE_SUMMARY}", f"Batch {scene_range}: " + (first_scene.summary or ""))
                  .replace("{CHARACTERS_PRESENT}", ", ".join(all_chars_present))
                  .replace("{SCENE_DIALOGUE}", dialogue))

        req = LLMRequest(
            prompt=prompt,
            model=config.models.medium,
            api_key=config.api_key,
            temperature=0.2,
            max_output=16000,   # tăng từ 8000 để đủ chỗ cho batch nhiều dòng
            json_mode=True,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client)
            tracker.add("3_speaker", resp)
            data = parse_json_response(resp.text, default={"lines": []})
            lines_count = len(data.get("lines", []) or [])
            if lines_count == 0:
                logger.warning(
                    f"[Stage 3] Batch {scene_range}: LLM returned 0 lines. "
                    f"Resp preview: {(resp.text or '')[:200]!r}"
                )
        except Exception as e:
            logger.warning(f"[Stage 3] Batch {scene_range} failed: {e}")
            return {}

        result = {}
        for line_data in data.get("lines", []) or []:
            try:
                line_idx = int(line_data.get("line_index", -1))
                if line_idx < 1:
                    continue
                result[line_idx] = {
                    "speaker_zh": line_data.get("speaker_zh", "?") or "?",
                    "confidence": line_data.get("confidence", "low"),
                    "reason": line_data.get("reason", "") or "",
                }
            except Exception:
                continue

        return result


async def run_stage3_speaker(
    entries: list[SrtEntry],
    bible: Bible,
    scene_map: SceneMap,
    config: PipelineConfig,
    tracker: CostTracker,
) -> dict[int, dict]:
    """Chạy Stage 3 — speaker cho toàn phim.

    Returns: map line_index -> {speaker_zh, confidence, reason, scene_index}
    """
    logger.info("=" * 60)
    logger.info("STAGE 3 — SPEAKER ASSIGNMENT")
    logger.info("=" * 60)

    prompt_template = load_prompt("speaker", config)
    entries_by_idx = {e.index: e for e in entries}

    # v3: batch nhiều scenes liền thành 1 call
    batches = build_scene_batches(scene_map.scenes, config.batch.speaker_lines_per_call)
    total_lines = sum(sc.end_line - sc.start_line + 1 for sc in scene_map.scenes)
    logger.info(f"[Stage 3] {len(scene_map.scenes)} scenes → {len(batches)} batches "
                f"(~{total_lines / max(len(batches), 1):.0f} lines/batch)")

    semaphore = asyncio.Semaphore(config.concurrency.speaker)

    async with httpx.AsyncClient() as client:
        tasks = [
            process_one_batch(batch, bible, entries_by_idx, prompt_template,
                              config, tracker, client, semaphore)
            for batch in batches
        ]

        all_results = {}
        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            batch_result = await coro
            all_results.update(batch_result)
            completed += 1
            if completed % 5 == 0 or completed == total:
                logger.info(f"   [Stage 3] {completed}/{total} batches done")

    # Map line → scene_index
    line_to_scene = {}
    for s in scene_map.scenes:
        for i in range(s.start_line, s.end_line + 1):
            line_to_scene[i] = s.index

    # Augment with scene info + name lookup
    for line_idx, info in all_results.items():
        info["scene_index"] = line_to_scene.get(line_idx)
        # Lookup speaker_vi
        speaker_zh = info.get("speaker_zh", "?")
        speaker_vi = ""
        if speaker_zh and speaker_zh != "?":
            ch = bible.cast.get_by_zh(speaker_zh)
            speaker_vi = ch.vi if ch else speaker_zh  # fallback to zh if not found
        info["speaker_vi"] = speaker_vi

    # Stats
    high = sum(1 for r in all_results.values() if r.get("confidence") == "high")
    mid = sum(1 for r in all_results.values() if r.get("confidence") == "mid")
    low = sum(1 for r in all_results.values() if r.get("confidence") == "low")
    logger.info(f"[Stage 3] DONE. {len(all_results)} lines tagged. "
                f"High={high}, Mid={mid}, Low={low}")

    return all_results