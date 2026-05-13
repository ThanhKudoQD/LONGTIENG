"""
Pipeline Orchestrator.

Chạy tuần tự 5 stage và build TranslationResult cuối.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import PipelineConfig
from core.llm_client import CostTracker
from core.srt_parser import SrtEntry, parse_srt_file, srt_stats, build_srt, format_time
from models import (
    Bible, SceneMap, SubtitleLine, TranslationResult, PolishReport,
)
from stages import (
    run_stage1_bible, run_stage2_scenes, run_stage3_speaker,
    run_stage4_translate, run_stage5_polish,
)
from stages.stage1_bible import load_genre_pack

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Kết quả 1 lần chạy pipeline."""
    bible: Bible
    scene_map: SceneMap
    translation: TranslationResult
    polish_report: PolishReport
    cost: CostTracker


async def run_full_pipeline(
    srt_path: str,
    config: PipelineConfig,
) -> PipelineResult:
    """Chạy toàn bộ 5 stage."""
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║  SRT TRANSLATOR v2 — Full Pipeline                       ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    # ─── Parse SRT ────────────────────────────────────────────
    logger.info(f"📂 Loading SRT: {srt_path}")
    entries = parse_srt_file(srt_path)
    stats = srt_stats(entries)
    logger.info(f"   {stats['total_lines']} lines, "
                f"{stats['total_duration_min']} min, "
                f"avg CPS {stats['avg_cps']}")

    # ─── Auto-tune config theo size (v3) ──────────────────────
    # Tự chỉnh batch sizes + compact mode theo total subs.
    config.auto_tune_for_size(len(entries))
    logger.info(
        f"⚙️  Auto-tune: compact={config.compact.enabled}, "
        f"speaker={config.batch.speaker_lines_per_call} lines/call, "
        f"translate={config.batch.translate_lines_per_call} lines/call"
    )

    tracker = CostTracker()

    # ─── Stage 1: Bible ───────────────────────────────────────
    bible = await run_stage1_bible(entries, config, tracker)

    # ─── Stage 2: Scenes ──────────────────────────────────────
    scene_map = await run_stage2_scenes(entries, bible, config, tracker)

    # ─── Stage 3: Speaker ─────────────────────────────────────
    speaker_map = await run_stage3_speaker(entries, bible, scene_map, config, tracker)

    # ─── Stage 4: Translate ───────────────────────────────────
    genre_pack = None
    if bible.genre_pack_id:
        genre_pack = load_genre_pack(bible.genre_pack_id, config)

    translation_map = await run_stage4_translate(
        entries, bible, scene_map, speaker_map, config, tracker,
        genre_pack=genre_pack,
    )

    # Build SubtitleLine list
    lines = []
    for e in entries:
        speaker_info = speaker_map.get(e.index, {})
        trans_info = translation_map.get(e.index, {})

        line = SubtitleLine(
            index=e.index,
            start_time_sec=e.start_sec,
            end_time_sec=e.end_sec,
            text_zh=e.text,
            text_vi=trans_info.get("text_vi", "") or "",
            speaker_zh=speaker_info.get("speaker_zh"),
            speaker_vi=trans_info.get("speaker_vi") or speaker_info.get("speaker_vi"),
            speaker_confidence=speaker_info.get("confidence", "low"),
            speaker_reason=speaker_info.get("reason", ""),
            emotion=trans_info.get("emotion"),
            intensity=trans_info.get("intensity", 5),
            scene_index=speaker_info.get("scene_index"),
        )

        # Mark scene flags
        if line.scene_index is not None and line.scene_index < len(scene_map.scenes):
            scene = scene_map.scenes[line.scene_index]
            line.is_hook = scene.is_hook

        # Speaker low confidence → review
        if speaker_info.get("confidence") == "low":
            line.needs_review = True
            line.review_reason = "Speaker low confidence"

        # Untranslated → review
        if not line.text_vi:
            line.needs_review = True
            line.review_reason = (line.review_reason + "; " if line.review_reason else "") + "Untranslated"
            # Placeholder: keep zh
            line.text_vi = f"[CHƯA DỊCH: {line.text_zh}]"

        lines.append(line)

    # ─── Stage 5: Polish ──────────────────────────────────────
    lines, polish_report = await run_stage5_polish(lines, bible, config, tracker)

    # Build TranslationResult
    total_cps = [l.cps_value for l in lines if l.cps_value]
    avg_cps = sum(total_cps) / len(total_cps) if total_cps else 0
    review_count = sum(1 for l in lines if l.needs_review)

    translation = TranslationResult(
        lines=lines,
        total_lines=len(lines),
        avg_cps=avg_cps,
        lines_needing_review=review_count,
    )

    # ─── Final stats ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("✅ PIPELINE COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total lines: {translation.total_lines}")
    logger.info(f"Avg CPS: {avg_cps:.2f}")
    logger.info(f"Lines needing review: {review_count}")
    logger.info(f"Polish rating: {polish_report.overall_rating}")
    logger.info("")
    logger.info(tracker.summary())

    return PipelineResult(
        bible=bible,
        scene_map=scene_map,
        translation=translation,
        polish_report=polish_report,
        cost=tracker,
    )


# ─────────────────────────────────────────────────────────────────
# SAVE HELPERS
# ─────────────────────────────────────────────────────────────────

def save_pipeline_outputs(
    result: PipelineResult,
    output_dir: str,
    base_name: str = "output",
) -> dict[str, str]:
    """Save toàn bộ output: SRT, Bible, Scene Map, Polish Report.

    Trả về dict tên → path.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    paths = {}

    # 1. SRT tiếng Việt
    srt_entries = []
    for line in result.translation.lines:
        srt_entries.append(SrtEntry(
            index=line.index,
            start_sec=line.start_time_sec,
            end_sec=line.end_time_sec,
            text=line.text_vi,
        ))
    srt_path = out_dir / f"{base_name}.vi.srt"
    srt_path.write_text(build_srt(srt_entries), encoding="utf-8")
    paths["srt_vi"] = str(srt_path)

    # 2. Bible JSON
    bible_path = out_dir / f"{base_name}.bible.json"
    bible_path.write_text(
        result.bible.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8"
    )
    paths["bible"] = str(bible_path)

    # 3. Scene Map JSON
    scenes_path = out_dir / f"{base_name}.scenes.json"
    scenes_path.write_text(
        result.scene_map.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8"
    )
    paths["scenes"] = str(scenes_path)

    # 4. Polish Report JSON
    report_path = out_dir / f"{base_name}.polish_report.json"
    report_path.write_text(
        result.polish_report.model_dump_json(indent=2, exclude_none=True),
        encoding="utf-8"
    )
    paths["polish_report"] = str(report_path)

    # 5. Review queue (CSV) — các dòng cần check tay
    import csv
    review_path = out_dir / f"{base_name}.review_queue.csv"
    with open(review_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "line_idx", "time", "speaker", "speaker_confidence",
            "emotion", "cps", "text_zh", "text_vi", "review_reason"
        ])
        for line in result.translation.lines:
            if line.needs_review:
                writer.writerow([
                    line.index,
                    format_time(line.start_time_sec),
                    line.speaker_vi or "",
                    line.speaker_confidence,
                    line.emotion or "",
                    f"{line.cps_value:.1f}" if line.cps_value else "",
                    line.text_zh,
                    line.text_vi,
                    line.review_reason,
                ])
    paths["review_queue"] = str(review_path)

    # 6. Full translation table (CSV)
    full_path = out_dir / f"{base_name}.full.csv"
    with open(full_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "idx", "start", "end", "scene", "speaker_zh", "speaker_vi",
            "confidence", "emotion", "intensity", "cps", "needs_review",
            "text_zh", "text_vi"
        ])
        for line in result.translation.lines:
            writer.writerow([
                line.index,
                format_time(line.start_time_sec),
                format_time(line.end_time_sec),
                line.scene_index or "",
                line.speaker_zh or "",
                line.speaker_vi or "",
                line.speaker_confidence,
                line.emotion or "",
                line.intensity,
                f"{line.cps_value:.1f}" if line.cps_value else "",
                "YES" if line.needs_review else "",
                line.text_zh,
                line.text_vi,
            ])
    paths["full_table"] = str(full_path)

    # 7. Cost summary
    cost_path = out_dir / f"{base_name}.cost.txt"
    cost_path.write_text(result.cost.summary(), encoding="utf-8")
    paths["cost"] = str(cost_path)

    logger.info(f"💾 Saved outputs to {out_dir}/")
    for name, p in paths.items():
        logger.info(f"   {name}: {Path(p).name}")

    return paths