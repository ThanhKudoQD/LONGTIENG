"""
Stage 5 — Polish/Retry (v3).

Đã đơn giản hóa: chỉ retry dòng còn tiếng Trung / rỗng / placeholder.
KHÔNG quét consistency / glossary / CPS condense bằng AI nữa.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Optional, Callable

import httpx

from config import PipelineConfig
from core.llm_client import LLMRequest, call_llm, parse_json_response, CostTracker
from core.srt_parser import calculate_cps
from models import (
    Bible, SubtitleLine, ReviewIssue, PolishReport, normalize_emotion,
)

logger = logging.getLogger(__name__)


_CHINESE_RE = re.compile(r'[\u4e00-\u9fff]')


def load_prompt(name: str, config: PipelineConfig) -> str:
    path = config.prompts_dir / f"{name}.txt"
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────
# DETECT LINES NEED RETRY (code logic)
# ─────────────────────────────────────────────────────────────────

def has_chinese_chars(text: str) -> bool:
    """Check còn ký tự Trung trong text."""
    if not text:
        return False
    return bool(_CHINESE_RE.search(text))


def detect_lines_to_retry(lines: list[SubtitleLine]) -> list[SubtitleLine]:
    """Phát hiện dòng cần retry."""
    result = []
    for line in lines:
        text = line.text_active
        # 1. Còn tiếng Trung
        if has_chinese_chars(text):
            line.needs_review = True
            line.review_reason = "Còn ký tự tiếng Trung"
            result.append(line)
            continue
        # 2. Rỗng
        if not text or not text.strip():
            line.needs_review = True
            line.review_reason = "Bản dịch rỗng"
            result.append(line)
            continue
        # 3. Placeholder
        if text.startswith("[CHƯA DỊCH") or text.startswith("[UNTRANSLATED"):
            line.needs_review = True
            line.review_reason = "Placeholder chưa dịch"
            result.append(line)
            continue
    return result


# ─────────────────────────────────────────────────────────────────
# RETRY VIA LLM (batch 10 dòng/call)
# ─────────────────────────────────────────────────────────────────

def format_bible_summary(bible: Bible) -> str:
    """Tóm tắt Bible compact cho retry prompt."""
    cast_short = []
    for c in bible.cast.characters[:15]:
        cast_short.append(f"- {c.zh} → {c.vi} ({c.g}, {c.role})")
    cast_str = "\n".join(cast_short)
    return (
        f"Thể loại: {', '.join(bible.world.genre)}\n"
        f"Era: {bible.world.era}\n"
        f"Tone: {bible.world.tone}\n\n"
        f"Nhân vật chính:\n{cast_str}"
    )


def format_glossary_block(bible: Bible) -> str:
    """Format glossary cho retry prompt."""
    lines = []
    for term in bible.glossary.terms[:50]:  # cap 50 terms
        lines.append(f"- {term.zh} → \"{term.vi}\"")
    return "\n".join(lines) if lines else "(Không có)"


async def retry_batch(
    batch: list[SubtitleLine],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
) -> dict[int, dict]:
    """Retry dịch 1 batch dòng. Return map line_idx → translation."""
    async with semaphore:
        bible_summary = format_bible_summary(bible)
        glossary = format_glossary_block(bible)

        lines_str = []
        for line in batch:
            duration = line.duration
            lines_str.append(
                f"{line.index} | {line.speaker_vi or '?'} | "
                f"{line.emotion or 'neutral'} | "
                f"{line.text_zh} | {duration:.1f}s"
            )
        lines_input = "\n".join(lines_str)

        prompt_template = load_prompt("retry", config)
        prompt = (prompt_template
                  .replace("{BIBLE_SUMMARY}", bible_summary)
                  .replace("{GLOSSARY}", glossary)
                  .replace("{LINES_TO_RETRY}", lines_input))

        req = LLMRequest(
            prompt=prompt,
            model=config.models.light,
            api_key=config.api_key,
            temperature=0.3,
            max_output=8000,
            json_mode=True,
            thinking=config.models.light_thinking,
            max_retries=config.concurrency.retry_max,
        )

        try:
            resp = await call_llm(req, client=client, stage_tag="5_retry")
            tracker.add("5_retry", resp)
            data = parse_json_response(resp.text, default={"translations": []})
        except Exception as e:
            logger.warning(f"[Stage 5] Retry batch failed: {e}")
            return {}

        result = {}
        for t in data.get("translations", []) or []:
            try:
                line_idx = int(t.get("line_index", -1))
                if line_idx < 1:
                    continue
                result[line_idx] = {
                    "speaker_vi": (t.get("speaker_vi") or "").strip() or None,
                    "text_v1": (t.get("text_v1") or "").strip() or None,
                    "text_v2": (t.get("text_v2") or "").strip() or None,
                    "emotion": normalize_emotion(t.get("emotion")),
                    "intensity": _clamp_intensity(t.get("intensity")),
                }
            except Exception:
                continue
        return result


def _clamp_intensity(val) -> int:
    try:
        return max(1, min(10, int(float(val))))
    except (TypeError, ValueError):
        return 5


# ─────────────────────────────────────────────────────────────────
# COMPUTE CPS (code only, không AI)
# ─────────────────────────────────────────────────────────────────

def compute_cps_for_lines(lines: list[SubtitleLine]) -> None:
    """Tính CPS cho mỗi dòng (in-place)."""
    for line in lines:
        text = line.text_active
        if not text or line.duration <= 0:
            line.cps_value = 0.0
            continue
        line.cps_value = calculate_cps(text, line.duration)


# ─────────────────────────────────────────────────────────────────
# MAIN STAGE 5
# ─────────────────────────────────────────────────────────────────

async def run_stage5_polish(
    lines: list[SubtitleLine],
    bible: Bible,
    config: PipelineConfig,
    tracker: CostTracker,
    on_retry_done: Optional[Callable] = None,
) -> tuple[list[SubtitleLine], PolishReport]:
    """Stage 5 — đơn giản: retry dòng thiếu + compute CPS."""
    logger.info("=" * 60)
    logger.info("STAGE 5 — POLISH (RETRY ONLY)")
    logger.info("=" * 60)

    # 1. Compute CPS
    compute_cps_for_lines(lines)

    # 2. Detect lines to retry
    to_retry = detect_lines_to_retry(lines)
    logger.info(f"[Stage 5] {len(to_retry)} lines need retry "
                f"out of {len(lines)} total")

    issues = []
    retried_count = 0
    fixed_count = 0

    if to_retry:
        # 3. Batch 10 dòng/call
        BATCH_SIZE = 10
        batches = [to_retry[i:i+BATCH_SIZE] for i in range(0, len(to_retry), BATCH_SIZE)]
        logger.info(f"[Stage 5] {len(batches)} retry batches")

        semaphore = asyncio.Semaphore(config.concurrency.polish)
        all_retry_results = {}

        async with httpx.AsyncClient() as client:
            tasks = [
                retry_batch(batch, bible, config, tracker, client, semaphore)
                for batch in batches
            ]
            for coro in asyncio.as_completed(tasks):
                batch_result = await coro
                all_retry_results.update(batch_result)
                retried_count += len(batch_result)

                if on_retry_done:
                    try:
                        res = on_retry_done(batch_result)
                        if asyncio.iscoroutine(res):
                            await res
                    except Exception as e:
                        logger.warning(f"[Stage 5] checkpoint failed: {e}")

        # 4. Apply retry results
        line_by_idx = {l.index: l for l in lines}
        for line_idx, info in all_retry_results.items():
            line = line_by_idx.get(line_idx)
            if not line:
                continue
            new_text_v1 = info.get("text_v1")
            if new_text_v1 and not has_chinese_chars(new_text_v1):
                line.text_v1 = new_text_v1
                line.text_v2 = info.get("text_v2")
                if info.get("speaker_vi"):
                    line.speaker_vi = info["speaker_vi"]
                if info.get("emotion"):
                    line.emotion = info["emotion"]
                if info.get("intensity"):
                    line.intensity = info["intensity"]
                line.needs_review = False
                line.review_reason = ""
                fixed_count += 1

        # 5. Re-compute CPS sau retry
        compute_cps_for_lines(lines)

        # 6. Build issues cho dòng vẫn còn vấn đề
        for line in to_retry:
            if line.needs_review:
                issues.append(ReviewIssue(
                    line_index=line.index,
                    issue_type="untranslated",
                    current_text=line.text_active,
                    reason=line.review_reason,
                ))

    still_problematic = sum(1 for l in lines if l.needs_review)

    report = PolishReport(
        issues=issues,
        retried_count=retried_count,
        fixed_count=fixed_count,
        still_problematic=still_problematic,
        summary=(
            f"Retry {retried_count} dòng, sửa {fixed_count}, "
            f"còn {still_problematic} cần review tay"
        ),
    )

    logger.info(f"[Stage 5] DONE. {report.summary}")
    return lines, report
