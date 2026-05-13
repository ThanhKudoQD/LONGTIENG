"""
Stage 3 — Speaker Assignment.

Per-scene: gán speaker cho mỗi dòng thoại.
Chạy song song nhiều scene cùng lúc (theo concurrency config).
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


def format_scene_dialogue(scene: Scene, entries_by_idx: dict[int, SrtEntry]) -> str:
    """Format thoại của 1 scene cho prompt."""
    lines = []
    for i in range(scene.start_line, scene.end_line + 1):
        e = entries_by_idx.get(i)
        if e:
            lines.append(f"{e.index} | {e.text}")
    return "\n".join(lines)


async def process_one_scene(
    scene: Scene,
    bible: Bible,
    entries_by_idx: dict[int, SrtEntry],
    prompt_template: str,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> dict[int, dict]:
    """Process 1 scene, trả về map line_index -> {speaker_zh, confidence, reason}."""
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

        dialogue = format_scene_dialogue(scene, entries_by_idx)

        prompt = (prompt_template
                  .replace("{CAST_JSON}", cast_compact)
                  .replace("{GLOSSARY_JSON}", glossary_compact)
                  .replace("{SCENE_INDEX}", str(scene.index))
                  .replace("{SCENE_LOCATION}", scene.location)
                  .replace("{SCENE_EMOTION}", f"{scene.emotion_primary} ({scene.emotion_arc})")
                  .replace("{SCENE_SUMMARY}", scene.summary)
                  .replace("{CHARACTERS_PRESENT}", ", ".join(scene.characters_present))
                  .replace("{SCENE_DIALOGUE}", dialogue))

        req = LLMRequest(
            prompt=prompt,
            model=config.models.medium,
            api_key=config.api_key,
            temperature=0.2,
            max_output=8000,
            json_mode=True,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client)
            tracker.add("3_speaker", resp)
            data = parse_json_response(resp.text, default={"lines": []})
        except Exception as e:
            logger.warning(f"[Stage 3] Scene {scene.index} failed: {e}")
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

    semaphore = asyncio.Semaphore(config.concurrency.speaker)

    async with httpx.AsyncClient() as client:
        tasks = [
            process_one_scene(s, bible, entries_by_idx, prompt_template,
                              config, tracker, client, semaphore)
            for s in scene_map.scenes
        ]

        all_results = {}
        completed = 0
        total = len(tasks)

        for coro in asyncio.as_completed(tasks):
            scene_result = await coro
            all_results.update(scene_result)
            completed += 1
            if completed % 10 == 0 or completed == total:
                logger.info(f"   [Stage 3] {completed}/{total} scenes done")

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
