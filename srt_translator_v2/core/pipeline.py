"""
Pipeline Orchestrator v3.

Chạy tuần tự 5 stage + build TranslationResult cuối.

Stages:
1. Bible      → Cast + World + Glossary
2. Chunks     → 1 call/arc → chunks + scenes lồng nhau
3. Speaker    → 1 call/chunk
4. Translate  → 1 call/chunk (2 variants v1/v2)
5. Polish     → code retry dòng còn TQ / rỗng

Có hỗ trợ checkpoint callbacks để DubEditor save DB sau mỗi chunk.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

from config import PipelineConfig
from core.llm_client import CostTracker
from core.srt_parser import SrtEntry, parse_srt_file, srt_stats, build_srt, format_time, calculate_cps
from models import (
    Bible, ChunkMap, SubtitleLine, TranslationResult, PolishReport,
)
from stages import (
    run_stage1_bible, run_stage2_chunks, run_stage3_speaker,
    run_stage4_translate, run_stage5_polish,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# RESULT
# ─────────────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Kết quả 1 lần chạy pipeline."""
    bible: Bible
    chunk_map: ChunkMap
    speaker_map: dict[int, dict]
    translation: TranslationResult
    polish_report: PolishReport
    cost: CostTracker
    entries: list[SrtEntry] = field(default_factory=list)

    @property
    def scene_map(self) -> ChunkMap:
        """Backwards compat alias."""
        return self.chunk_map


# ─────────────────────────────────────────────────────────────────
# CHECKPOINT CALLBACKS (cho DubEditor)
# ─────────────────────────────────────────────────────────────────

@dataclass
class PipelineCallbacks:
    """Callbacks để DubEditor checkpoint sau mỗi stage / chunk."""
    on_stage1_done: Optional[Callable[[Bible], None]] = None
    on_stage2_done: Optional[Callable[[ChunkMap], None]] = None
    on_stage3_chunk_done: Optional[Callable[[dict], None]] = None
    on_stage4_chunk_done: Optional[Callable[[dict], None]] = None
    on_stage5_done: Optional[Callable[[PolishReport], None]] = None


# ─────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────

async def run_full_pipeline(
    srt_path: str,
    config: PipelineConfig,
    callbacks: Optional[PipelineCallbacks] = None,
) -> PipelineResult:
    """Chạy toàn bộ 5 stages."""
    logger.info("╔══════════════════════════════════════════════════════════╗")
    logger.info("║  SRT TRANSLATOR v3 — Full Pipeline                       ║")
    logger.info("╚══════════════════════════════════════════════════════════╝")

    callbacks = callbacks or PipelineCallbacks()

    # ─── Parse SRT ────────────────────────────────────────────
    logger.info(f"📂 Loading SRT: {srt_path}")
    entries = parse_srt_file(srt_path)
    stats = srt_stats(entries)
    logger.info(f"   {stats['total_lines']} lines, "
                f"{stats['total_duration_min']:.1f} min, "
                f"avg CPS {stats['avg_cps']:.1f}")

    # Auto-tune config theo size
    config.auto_tune_for_size(stats["total_lines"])
    logger.info(f"   Project: {config.project_type} | "
                f"Chunk target: {config.chunk.target_lines} | "
                f"Compact: {config.compact.enabled} | "
                f"Variant: {config.variant.mode}")

    tracker = CostTracker()

    # ─── STAGE 1: Bible ───────────────────────────────────────
    bible = await run_stage1_bible(entries, config, tracker)
    if callbacks.on_stage1_done:
        try:
            callbacks.on_stage1_done(bible)
        except Exception as e:
            logger.warning(f"on_stage1_done failed: {e}")

    # ─── STAGE 2: Chunks + Scenes ─────────────────────────────
    chunk_map = await run_stage2_chunks(entries, bible, config, tracker)
    if callbacks.on_stage2_done:
        try:
            callbacks.on_stage2_done(chunk_map)
        except Exception as e:
            logger.warning(f"on_stage2_done failed: {e}")

    # ─── STAGE 3: Speaker ─────────────────────────────────────
    speaker_map = await run_stage3_speaker(
        entries, bible, chunk_map, config, tracker,
        on_chunk_done=callbacks.on_stage3_chunk_done,
    )

    # ─── STAGE 4: Translate (2 variants) ──────────────────────
    translation_map = await run_stage4_translate(
        entries, bible, chunk_map, speaker_map, config, tracker,
        on_chunk_done=callbacks.on_stage4_chunk_done,
    )

    # ─── Build SubtitleLines ──────────────────────────────────
    lines = []
    for e in entries:
        line = SubtitleLine(
            index=e.index,
            start_time_sec=e.start_sec,
            end_time_sec=e.end_sec,
            text_zh=e.text,
        )

        # Apply speaker
        sp_info = speaker_map.get(e.index)
        if sp_info:
            line.speaker_zh = sp_info.get("speaker_zh")
            line.speaker_confidence = sp_info.get("confidence", "l")
            line.scene_index = sp_info.get("scene_index")
            line.arc_index = sp_info.get("arc_index")

            # Tìm chunk_index
            for c_idx, chunk in enumerate(chunk_map.chunks):
                if chunk.r[0] <= e.index <= chunk.r[1]:
                    line.chunk_index = c_idx
                    break

        # Resolve speaker_vi từ Bible
        if line.speaker_zh:
            ch_info = bible.cast.get_by_zh(line.speaker_zh)
            if ch_info:
                line.speaker_vi = ch_info.vi

        # Apply translation
        tr_info = translation_map.get(e.index)
        if tr_info:
            line.text_v1 = tr_info.get("text_v1")
            line.text_v2 = tr_info.get("text_v2")
            line.emotion = tr_info.get("emotion")
            line.intensity = tr_info.get("intensity", 5)
            if tr_info.get("speaker_vi"):
                line.speaker_vi = tr_info["speaker_vi"]
            line.variant_selected = 1  # mặc định v1
        else:
            # Chưa dịch → placeholder
            line.text_v1 = "[CHƯA DỊCH]"
            line.needs_review = True

        # Tìm scene info để set hook/peak flags
        scene = chunk_map.get_scene_for_line(e.index)
        if scene:
            line.is_hook = scene.is_hook
            line.is_emotion_peak = scene.is_emotion_peak

        lines.append(line)

    # ─── STAGE 5: Polish (retry) ──────────────────────────────
    lines, polish_report = await run_stage5_polish(
        lines, bible, config, tracker,
    )
    if callbacks.on_stage5_done:
        try:
            callbacks.on_stage5_done(polish_report)
        except Exception as e:
            logger.warning(f"on_stage5_done failed: {e}")

    # ─── Build TranslationResult ──────────────────────────────
    translated_count = sum(1 for l in lines if l.text_v1 and l.text_v1 != "[CHƯA DỊCH]")
    variants_count = sum(1 for l in lines if l.text_v2)
    cps_values = [l.cps_value for l in lines if l.cps_value is not None and l.cps_value > 0]
    avg_cps = sum(cps_values) / len(cps_values) if cps_values else 0.0
    needs_review_count = sum(1 for l in lines if l.needs_review)

    result = TranslationResult(
        lines=lines,
        total_lines=len(lines),
        translated_count=translated_count,
        variants_count=variants_count,
        avg_cps=avg_cps,
        lines_needing_review=needs_review_count,
    )

    # ─── Summary log ──────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("PIPELINE DONE")
    logger.info("=" * 60)
    logger.info(f"  Translated: {translated_count}/{len(lines)} lines")
    logger.info(f"  Variants v2: {variants_count} lines")
    logger.info(f"  Avg CPS: {avg_cps:.2f}")
    logger.info(f"  Needs review: {needs_review_count} lines")
    logger.info(tracker.summary())

    return PipelineResult(
        bible=bible,
        chunk_map=chunk_map,
        speaker_map=speaker_map,
        translation=result,
        polish_report=polish_report,
        cost=tracker,
        entries=entries,
    )


# ─────────────────────────────────────────────────────────────────
# EXPORT HELPERS
# ─────────────────────────────────────────────────────────────────

def export_srt(result: PipelineResult, output_path: str, use_variant: int = 1) -> None:
    """Export SRT từ kết quả pipeline.

    use_variant:
      1: dùng text_v1 (sát nghĩa)
      2: dùng text_v2 nếu có, fallback v1
      0: dùng line.text_active (theo variant_selected mỗi line)
    """
    out_entries = []
    for line in result.translation.lines:
        if use_variant == 1:
            text = line.text_v1 or ""
        elif use_variant == 2:
            text = line.text_v2 or line.text_v1 or ""
        else:
            text = line.text_active

        out_entries.append(SrtEntry(
            index=line.index,
            start_sec=line.start_time_sec,
            end_sec=line.end_time_sec,
            text=text,
        ))

    srt_text = build_srt(out_entries)
    Path(output_path).write_text(srt_text, encoding="utf-8")
    logger.info(f"✅ Exported SRT to {output_path}")
