"""
Stage 2 — Scene Detection.

Đọc Bible + SRT, chia phim thành 150-250 phân cảnh kịch.
1 call duy nhất với model có context dài.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import SrtEntry
from models import Bible, Scene, SceneMap

logger = logging.getLogger(__name__)


def format_srt_for_scene_detect(entries: list[SrtEntry]) -> str:
    """Format SRT cho scene detection — cần timing để detect khoảng nhảy thời gian."""
    return "\n".join(
        f"{e.index} | {e.start_sec:.1f}s-{e.end_sec:.1f}s | {e.text}"
        for e in entries
    )


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


def validate_scene_continuity(scenes: list[Scene], total_lines: int) -> list[Scene]:
    """Đảm bảo các scene liên tục, không gap, không overlap."""
    if not scenes:
        return scenes

    scenes = sorted(scenes, key=lambda s: s.start_line)

    # Re-index
    fixed = []
    for i, s in enumerate(scenes):
        s.index = i
        fixed.append(s)

    # Check gap / overlap
    for i in range(1, len(fixed)):
        prev = fixed[i - 1]
        curr = fixed[i]
        if curr.start_line != prev.end_line + 1:
            logger.warning(
                f"[Scene continuity] Gap/overlap between scene {i-1} (end={prev.end_line}) "
                f"and {i} (start={curr.start_line}). Fixing by extending prev."
            )
            # Patch — extend prev to fill gap, or trim if overlap
            if curr.start_line > prev.end_line + 1:
                prev.end_line = curr.start_line - 1
            else:
                curr.start_line = prev.end_line + 1

    # Đảm bảo scene đầu start = 1
    if fixed[0].start_line > 1:
        fixed[0].start_line = 1

    # Đảm bảo scene cuối end = total_lines
    if fixed[-1].end_line < total_lines:
        fixed[-1].end_line = total_lines

    # Loại scene rỗng
    valid = [s for s in fixed if s.start_line <= s.end_line]

    return valid


async def run_stage2_scenes(
    entries: list[SrtEntry],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
) -> SceneMap:
    """Chạy Stage 2 — scene detection."""
    logger.info("=" * 60)
    logger.info("STAGE 2 — SCENE DETECTION")
    logger.info("=" * 60)

    prompt_template = load_prompt("scene_detect", config)
    srt_text = format_srt_for_scene_detect(entries)

    # Bible compact (không cần full glossary cho scene detect)
    bible_compact = json.dumps({
        "cast": [
            {"zh": c.zh, "vi": c.vi, "role": c.role, "gender": c.gender}
            for c in bible.cast.characters
        ],
        "world": {
            "genre_main": bible.world.genre_main,
            "genre_sub": bible.world.genre_sub,
            "plot_summary": bible.world.plot_summary,
            "tone_overall": bible.world.tone_overall,
        },
        "story_arcs": [
            {
                "index": a.index,
                "title": a.title,
                "summary": a.summary,
                "start_line": a.start_line,
                "end_line": a.end_line,
            }
            for a in bible.world.story_arcs
        ],
    }, ensure_ascii=False, indent=2)

    prompt = (prompt_template
              .replace("{BIBLE_JSON}", bible_compact)
              .replace("{SRT_FULL}", srt_text))

    # Chọn model — Flash cũng được, vì task này không cần creativity
    model = config.models.medium  # dùng Flash để rẻ hơn
    req = LLMRequest(
        prompt=prompt,
        model=model,
        api_key=config.api_key,
        temperature=0.2,
        max_output=32000,  # output lớn — 200 scenes × ~150 char/scene
        json_mode=True,
        max_retries=config.concurrency.retry_max,
    )

    async with httpx.AsyncClient() as client:
        resp = await call_llm(req, client=client)
    tracker.add("2_scenes", resp)

    data = parse_json_response(resp.text, default={"scenes": []})

    scenes = []
    line_to_time = {e.index: (e.start_sec, e.end_sec) for e in entries}

    for s_data in data.get("scenes", []) or []:
        try:
            start_line = int(s_data.get("start_line", 0))
            end_line = int(s_data.get("end_line", 0))
            if start_line < 1 or end_line < start_line:
                continue

            # Lookup timing
            start_time = line_to_time.get(start_line, (0.0, 0.0))[0]
            end_time = line_to_time.get(end_line, (0.0, 0.0))[1]

            scenes.append(Scene(
                index=int(s_data.get("index", len(scenes))),
                start_line=start_line,
                end_line=end_line,
                start_time_sec=start_time,
                end_time_sec=end_time,
                location=s_data.get("location", "") or "",
                time_of_day=s_data.get("time_of_day"),
                characters_present=s_data.get("characters_present", []) or [],
                emotion_primary=s_data.get("emotion_primary", "neutral"),
                emotion_arc=s_data.get("emotion_arc", "") or "",
                summary=s_data.get("summary", "") or "",
                purpose=s_data.get("purpose", "") or "",
                story_arc_index=s_data.get("story_arc_index"),
                is_hook=bool(s_data.get("is_hook", False)),
                is_emotion_peak=bool(s_data.get("is_emotion_peak", False)),
            ))
        except Exception as e:
            logger.warning(f"[Stage 2] Skipped malformed scene: {e}")

    # Validate continuity
    scenes = validate_scene_continuity(scenes, total_lines=len(entries))

    scene_map = SceneMap(
        scenes=scenes,
        total_lines=len(entries),
        total_duration_sec=entries[-1].end_sec - entries[0].start_sec if entries else 0,
    )

    logger.info(f"[Stage 2] DONE. {len(scenes)} scenes detected.")
    if scenes:
        avg_lines = sum(s.end_line - s.start_line + 1 for s in scenes) / len(scenes)
        peak_count = sum(1 for s in scenes if s.is_emotion_peak)
        hook_count = sum(1 for s in scenes if s.is_hook)
        logger.info(f"   Avg {avg_lines:.1f} lines/scene, "
                    f"{peak_count} emotion peaks, {hook_count} hooks")

    return scene_map
