"""
Prompt builders cho chế độ Dịch Thủ công.

Tái sử dụng logic build prompt từ stages/* nhưng KHÔNG gọi LLM. Trả về:
  - prompt: chuỗi text user sẽ copy ra LLM web
  - meta: metadata cần thiết để apply_response parse đúng (vd. unit_key,
          line range, model gợi ý, JSON schema mong đợi)

Khái niệm "unit": 1 lần copy-paste của user. Mỗi stage có cách chia unit khác:
  - stage0_normalize:    1 unit  (toàn phim, 1 prompt)
  - stage1a_cast:        1 unit
  - stage1a_glossary:    1 unit
  - stage1b_world:       1 unit  (cần cast đã xong)
  - stage2_chunks:       N units = số arc  (mỗi arc 1 prompt)
  - stage3_speaker:      N units = số chunk
  - stage4_translate:    N units = số chunk
  - stage5_polish:       N units = số batch (10 dòng/batch)

list_units(stage, project_id, db) trả về danh sách unit_key có sẵn để
frontend hiển thị dropdown / progress.
"""
from __future__ import annotations
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from sqlalchemy.orm import Session

# Add srt_translator_v2 to sys.path nếu chưa
_TRANSLATOR_DIR = Path(__file__).parent.parent
if str(_TRANSLATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATOR_DIR))

from config import PipelineConfig
from core.srt_parser import SrtEntry

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────

@dataclass
class StageUnit:
    """1 đơn vị copy-paste của 1 stage."""
    unit_key: str           # vd "arc_0", "chunk_1-250", "batch_3"
    label: str              # vd "Arc 1: Lần đầu gặp gỡ (dòng 1-250)"
    status: str = "pending" # pending | done


@dataclass
class BuiltPrompt:
    """Output của build_prompt — gồm prompt text + metadata."""
    stage: str              # "normalize", "bible_cast", ...
    unit_key: str           # "default" nếu stage có 1 unit duy nhất
    label: str
    prompt: str             # text user copy ra LLM web
    meta: dict[str, Any] = field(default_factory=dict)
    # meta gồm: line_range, suggested_model, json_root_key, ...


# ─────────────────────────────────────────────────────────────────
# Helpers — load entries từ DB
# ─────────────────────────────────────────────────────────────────

def _load_entries(db: Session, project_id: int) -> list[SrtEntry]:
    """Load DB subtitles thành SrtEntry list (đã sort theo index)."""
    # Import muộn để tránh circular
    from dubeditor.translate_service import db_subtitles_to_srt_entries
    from dubeditor.models import Subtitle
    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id)
              .order_by(Subtitle.index)
              .all())
    return db_subtitles_to_srt_entries(subs)


def _load_bible(db: Session, project_id: int):
    """Load active Bible từ DB → V3Bible. Raise nếu chưa có."""
    from dubeditor.translate_service import load_active_bible_from_db
    bible = load_active_bible_from_db(db, project_id)
    if not bible:
        raise ValueError("Chưa có Bible — chạy Stage 1 trước")
    return bible


def _load_chunk_map(db: Session, project_id: int):
    """Load chunks + scenes từ DB → V3ChunkMap. Raise nếu chưa có."""
    from dubeditor.translate_service import load_chunks_from_db
    cm = load_chunks_from_db(db, project_id)
    if not cm or not cm.chunks:
        raise ValueError("Chưa có Chunks — chạy Stage 2 trước")
    return cm


def _load_speaker_map(db: Session, project_id: int) -> dict[int, dict]:
    """Load speaker map từ DB. Trả {} nếu chưa có.

    Subtitle chỉ lưu speaker_zh; speaker_vi resolve từ Character table
    (theo character_id hoặc name_zh match).
    """
    from dubeditor.models import Subtitle, Character
    # Build zh → vi map từ Character
    vi_by_zh = {}
    for c in db.query(Character).filter(Character.project_id == project_id).all():
        if c.name_zh and c.name:
            vi_by_zh[c.name_zh] = c.name

    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id)
              .all())
    speaker_map = {}
    for s in subs:
        if s.speaker_zh:
            speaker_map[s.index] = {
                "speaker_zh": s.speaker_zh,
                "speaker_vi": vi_by_zh.get(s.speaker_zh, ""),
                "confidence": s.speaker_confidence or "l",
            }
    return speaker_map


# ─────────────────────────────────────────────────────────────────
# Stage 0 — Normalize
# ─────────────────────────────────────────────────────────────────

def _build_stage0(db: Session, project_id: int, config: PipelineConfig) -> list[BuiltPrompt]:
    from stages.stage0_normalize import build_data_lines, load_prompt
    from core.suspicious_scanner import scan_suspicious

    entries = _load_entries(db, project_id)
    if not entries:
        raise ValueError("Project không có subtitles")

    flags = scan_suspicious(entries)
    if not flags:
        return [BuiltPrompt(
            stage="normalize",
            unit_key="default",
            label=f"Stage 0 — Không có dòng khả nghi ({len(entries)} dòng)",
            prompt="(Không cần chạy Stage 0 — không phát hiện dòng nghi ngờ nào.)",
            meta={"empty": True, "suspicious_count": 0, "total": len(entries)},
        )]

    context_window = max(0, config.stage0.context_window)
    data_text, lines_sent = build_data_lines(entries, flags, context_window)
    prompt_template = load_prompt("normalize", config)
    prompt = prompt_template.replace("{DATA_LINES}", data_text)

    return [BuiltPrompt(
        stage="normalize",
        unit_key="default",
        label=f"Stage 0 — Chuẩn hóa ({lines_sent} dòng gửi LLM, "
              f"{len(flags)} nghi ngờ)",
        prompt=prompt,
        meta={
            "suspicious_indices": [f.line_index for f in flags],
            "lines_sent": lines_sent,
            "json_root_key": "decisions",
        },
    )]


# ─────────────────────────────────────────────────────────────────
# Stage 1A.1 — Cast
# ─────────────────────────────────────────────────────────────────

def _build_stage1a_cast(db: Session, project_id: int, config: PipelineConfig) -> list[BuiltPrompt]:
    from stages.stage1_bible import format_srt_for_prompt, load_prompt

    entries = _load_entries(db, project_id)
    if not entries:
        raise ValueError("Project không có subtitles")

    prompt_template = load_prompt("bible_cast", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    prompt = prompt_template.replace("{SRT_FULL}", srt_text)

    return [BuiltPrompt(
        stage="bible_cast",
        unit_key="default",
        label=f"Stage 1A.1 — Cast ({len(entries)} dòng)",
        prompt=prompt,
        meta={"json_root_key": "c", "total_lines": len(entries)},
    )]


# ─────────────────────────────────────────────────────────────────
# Stage 1A.2 — Glossary
# ─────────────────────────────────────────────────────────────────

def _build_stage1a_glossary(db: Session, project_id: int, config: PipelineConfig) -> list[BuiltPrompt]:
    from stages.stage1_bible import format_srt_for_prompt, load_prompt

    entries = _load_entries(db, project_id)
    if not entries:
        raise ValueError("Project không có subtitles")

    prompt_template = load_prompt("bible_glossary", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    prompt = prompt_template.replace("{SRT_FULL}", srt_text)

    return [BuiltPrompt(
        stage="bible_glossary",
        unit_key="default",
        label=f"Stage 1A.2 — Glossary ({len(entries)} dòng)",
        prompt=prompt,
        meta={"json_root_key": "t", "total_lines": len(entries)},
    )]


# ─────────────────────────────────────────────────────────────────
# Stage 1B — World + Arcs
# ─────────────────────────────────────────────────────────────────

def _build_stage1b_world(db: Session, project_id: int, config: PipelineConfig) -> list[BuiltPrompt]:
    """Cần Cast đã có sẵn (gọi sau 1A.1)."""
    from stages.stage1_bible import format_srt_for_prompt, load_prompt

    entries = _load_entries(db, project_id)
    if not entries:
        raise ValueError("Project không có subtitles")

    # Load Cast hiện tại
    try:
        bible = _load_bible(db, project_id)
        cast = bible.cast
    except ValueError:
        raise ValueError("Chưa có Cast — chạy Stage 1A.1 (Cast) trước")

    prompt_template = load_prompt("bible_world", config)
    srt_text = format_srt_for_prompt(entries, with_timing=False)
    cast_brief = "\n".join(
        f"- {c.zh} → {c.vi} ({c.role}, {c.char})"
        for c in cast.characters[:15]
    )

    prompt = (prompt_template
              .replace("{SRT_FULL}", srt_text)
              .replace("{CAST_BRIEF}", cast_brief)
              .replace("{TOTAL_LINES}", str(len(entries))))

    return [BuiltPrompt(
        stage="bible_world",
        unit_key="default",
        label=f"Stage 1B — World + Arcs ({len(cast.characters)} nhân vật ref)",
        prompt=prompt,
        meta={
            "total_lines": len(entries),
            "cast_size": len(cast.characters),
        },
    )]


# ─────────────────────────────────────────────────────────────────
# Stage 2 — Chunks + Scenes (per arc)
# ─────────────────────────────────────────────────────────────────

def _build_stage2_one_arc(arc, entries: list[SrtEntry], bible,
                           config: PipelineConfig) -> BuiltPrompt:
    from stages.stage2_scenes import format_arc_srt, build_bible_reference, load_prompt

    prompt_template = load_prompt("chunks_and_scenes", config)
    arc_srt = format_arc_srt(entries, arc)
    bible_ref = build_bible_reference(bible)

    prompt = (prompt_template
              .replace("{BIBLE_REFERENCE}", bible_ref)
              .replace("{ARC_INDEX}", str(arc.index))
              .replace("{ARC_TITLE}", arc.t)
              .replace("{ARC_TONE}", arc.tone)
              .replace("{ARC_SUMMARY}", arc.summary or "(không có tóm tắt)")
              .replace("{ARC_START}", str(arc.r[0]))
              .replace("{ARC_END}", str(arc.r[1]))
              .replace("{ARC_SRT}", arc_srt)
              .replace("{CHUNK_TARGET}", str(config.chunk.target_lines))
              .replace("{MAX_CHUNKS}", str(config.chunk.max_chunks_per_arc)))

    return BuiltPrompt(
        stage="chunks",
        unit_key=f"arc_{arc.index}",
        label=f"Arc {arc.index}: {arc.t} (dòng {arc.r[0]}-{arc.r[1]})",
        prompt=prompt,
        meta={
            "arc_index": arc.index,
            "arc_range": [arc.r[0], arc.r[1]],
            "arc_title": arc.t,
            "json_root_key": "chunks",
        },
    )


def _build_stage2(db: Session, project_id: int, config: PipelineConfig,
                  unit_key: Optional[str] = None) -> list[BuiltPrompt]:
    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)

    if not bible.world.arcs:
        raise ValueError("Chưa có arcs trong Bible — chạy Stage 1B trước")

    prompts = []
    for arc in bible.world.arcs:
        if unit_key and unit_key != f"arc_{arc.index}":
            continue
        prompts.append(_build_stage2_one_arc(arc, entries, bible, config))

    if unit_key and not prompts:
        raise ValueError(f"Không tìm thấy unit '{unit_key}' trong Stage 2")
    return prompts


# ─────────────────────────────────────────────────────────────────
# Stage 3 — Speaker (per chunk)
# ─────────────────────────────────────────────────────────────────

def _build_stage3_one_chunk(chunk, entries, bible, prev_speaker_map,
                              config: PipelineConfig) -> BuiltPrompt:
    from stages.stage3_speaker import (
        get_chunk_characters, format_arc_characters, format_relationships_in_chunk,
        format_scenes_info, format_chunk_srt, format_context_lines,
        format_carry_over, find_arc_for_chunk, load_prompt,
    )

    chars_in_chunk = get_chunk_characters(chunk, bible)
    arc_chars = format_arc_characters(bible, chars_in_chunk)
    relationships = format_relationships_in_chunk(bible, chars_in_chunk)
    scenes_info = format_scenes_info(chunk)
    chunk_srt = format_chunk_srt(entries, chunk)

    arc = find_arc_for_chunk(chunk, bible)
    arc_title = arc.t if arc else f"Arc {chunk.arc_index}"
    arc_summary = (arc.summary if arc and arc.summary else "(không có tóm tắt)")

    window = config.speaker.context_window
    total_lines = max(e.index for e in entries) if entries else 0
    context_before = format_context_lines(entries,
                                            max(1, chunk.r[0] - window),
                                            chunk.r[0] - 1)
    context_after = format_context_lines(entries,
                                           chunk.r[1] + 1,
                                           min(total_lines, chunk.r[1] + window))

    carry_over = format_carry_over(
        entries=entries,
        prev_results=prev_speaker_map,
        chunk_start=chunk.r[0],
        carry_lines=config.speaker.carry_over_lines,
        bible=bible,
    )

    prompt_template = load_prompt("speaker", config)
    prompt = (prompt_template
              .replace("{ARC_CHARACTERS}", arc_chars)
              .replace("{RELATIONSHIPS}", relationships)
              .replace("{ARC_TITLE}", arc_title)
              .replace("{ARC_SUMMARY}", arc_summary)
              .replace("{CHUNK_TITLE}", chunk.t or f"Chunk {chunk.r[0]}-{chunk.r[1]}")
              .replace("{CHUNK_START}", str(chunk.r[0]))
              .replace("{CHUNK_END}", str(chunk.r[1]))
              .replace("{SCENES_INFO}", scenes_info)
              .replace("{CARRY_OVER}", carry_over)
              .replace("{CONTEXT_BEFORE}", context_before)
              .replace("{CONTEXT_AFTER}", context_after)
              .replace("{CHUNK_SRT}", chunk_srt))

    return BuiltPrompt(
        stage="speaker",
        unit_key=f"chunk_{chunk.r[0]}_{chunk.r[1]}",
        label=f"Chunk dòng {chunk.r[0]}-{chunk.r[1]}: {chunk.t or '(chưa đặt tên)'}",
        prompt=prompt,
        meta={
            "chunk_range": [chunk.r[0], chunk.r[1]],
            "arc_index": chunk.arc_index,
            "json_root_key": "speakers",
        },
    )


def _build_stage3(db: Session, project_id: int, config: PipelineConfig,
                  unit_key: Optional[str] = None) -> list[BuiltPrompt]:
    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)
    chunk_map = _load_chunk_map(db, project_id)
    speaker_map = _load_speaker_map(db, project_id)

    prompts = []
    for chunk in chunk_map.chunks:
        ck = f"chunk_{chunk.r[0]}_{chunk.r[1]}"
        if unit_key and unit_key != ck:
            continue
        # Lấy speakers của chunk trước (line < chunk.r[0]) làm carry-over
        prev_in_arc = {ln: info for ln, info in speaker_map.items()
                       if ln < chunk.r[0]}
        prompts.append(_build_stage3_one_chunk(
            chunk, entries, bible, prev_in_arc, config
        ))

    if unit_key and not prompts:
        raise ValueError(f"Không tìm thấy unit '{unit_key}' trong Stage 3")
    return prompts


# ─────────────────────────────────────────────────────────────────
# Stage 4 — Translate (per chunk)
# ─────────────────────────────────────────────────────────────────

def _build_stage4_one_chunk(chunk, entries, entries_by_idx, bible,
                              speaker_map, config: PipelineConfig) -> BuiltPrompt:
    from stages.stage4_translate import (
        format_characters_in_chunk, format_relationships,
        format_glossary_chunk, format_scenes_in_chunk,
        format_dialogue_input, format_context_window,
        load_genre_pack, format_genre_pack_for_prompt, load_prompt,
    )

    characters_in_chunk = format_characters_in_chunk(chunk, bible)
    relationships = format_relationships(chunk, bible)
    glossary_chunk = format_glossary_chunk(chunk, entries_by_idx, bible)
    scenes_in_chunk = format_scenes_in_chunk(chunk)
    dialogue_input = format_dialogue_input(chunk, entries_by_idx, speaker_map)

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

    arc = bible.world.arcs[chunk.arc_index] if chunk.arc_index < len(bible.world.arcs) else None
    arc_title = arc.t if arc else ""
    arc_tone = arc.tone if arc else "neutral"
    arc_summary = (arc.summary if arc and arc.summary else "(không có tóm tắt)")

    genre_pack = load_genre_pack(bible.world.genre_id, config)
    genre_pack_str = format_genre_pack_for_prompt(genre_pack)

    prompt_template = load_prompt("translate_chunk", config)
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

    return BuiltPrompt(
        stage="translate",
        unit_key=f"chunk_{chunk.r[0]}_{chunk.r[1]}",
        label=f"Chunk dòng {chunk.r[0]}-{chunk.r[1]}: {chunk.t or '(chưa đặt tên)'}",
        prompt=prompt,
        meta={
            "chunk_range": [chunk.r[0], chunk.r[1]],
            "arc_index": chunk.arc_index,
            "json_root_key": "t",
        },
    )


def _build_stage4(db: Session, project_id: int, config: PipelineConfig,
                  unit_key: Optional[str] = None) -> list[BuiltPrompt]:
    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)
    chunk_map = _load_chunk_map(db, project_id)
    speaker_map = _load_speaker_map(db, project_id)
    entries_by_idx = {e.index: e for e in entries}

    prompts = []
    for chunk in chunk_map.chunks:
        ck = f"chunk_{chunk.r[0]}_{chunk.r[1]}"
        if unit_key and unit_key != ck:
            continue
        prompts.append(_build_stage4_one_chunk(
            chunk, entries, entries_by_idx, bible, speaker_map, config
        ))

    if unit_key and not prompts:
        raise ValueError(f"Không tìm thấy unit '{unit_key}' trong Stage 4")
    return prompts


# ─────────────────────────────────────────────────────────────────
# Stage 5 — Polish/Retry (per batch)
# ─────────────────────────────────────────────────────────────────

_POLISH_BATCH_SIZE = 10


def _load_polish_lines(db: Session, project_id: int):
    """Load SubtitleLine v3 + flag dòng cần retry."""
    from dubeditor.models import Subtitle
    from models import SubtitleLine
    from stages.stage5_polish import detect_lines_to_retry

    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id)
              .order_by(Subtitle.index)
              .all())
    lines = []
    for s in subs:
        lines.append(SubtitleLine(
            index=s.index,
            start_time_sec=s.start_time,
            end_time_sec=s.end_time,
            text_zh=s.original_text or "",
            text_v1=s.text_v1 or s.text or "",
            text_v2=s.text_v2,
            variant_selected=s.variant_selected or 1,
            speaker_zh=s.speaker_zh,
            speaker_vi=None,
            speaker_confidence=s.speaker_confidence or "l",
            emotion=s.emotion,
            intensity=s.intensity or 5,
            needs_review=s.needs_review or False,
            review_reason=s.review_reason or "",
        ))
    to_retry = detect_lines_to_retry(lines)
    return lines, to_retry


def _build_stage5_one_batch(batch, all_lines, bible, batch_idx: int,
                              config: PipelineConfig) -> BuiltPrompt:
    from stages.stage5_polish import (
        format_bible_summary, format_relationships_full,
        format_glossary_block, format_line_context, load_prompt,
    )
    from stages.stage4_translate import load_genre_pack, format_genre_pack_for_prompt

    bible_summary = format_bible_summary(bible)
    glossary = format_glossary_block(bible)
    relationships = format_relationships_full(bible)

    genre_pack = load_genre_pack(bible.world.genre_id, config)
    genre_pack_str = format_genre_pack_for_prompt(genre_pack)

    lines_blocks = []
    for line in batch:
        duration = line.duration
        ctx_before, ctx_after = format_line_context(
            all_lines, line.index, context_window=3
        )
        block = (
            f"━━━ DÒNG {line.index} ━━━\n"
            f"Context trước:\n{ctx_before}\n\n"
            f"DỊCH LẠI: {line.index} | {line.speaker_vi or '?'} | "
            f"emotion={line.emotion or 'neutral'} | "
            f"text_zh={line.text_zh} | duration={duration:.1f}s\n\n"
            f"Context sau:\n{ctx_after}"
        )
        lines_blocks.append(block)
    lines_input = "\n\n".join(lines_blocks)

    prompt_template = load_prompt("retry", config)
    prompt = (prompt_template
              .replace("{BIBLE_SUMMARY}", bible_summary)
              .replace("{GENRE_PACK}", genre_pack_str)
              .replace("{RELATIONSHIPS}", relationships)
              .replace("{GLOSSARY}", glossary)
              .replace("{LINES_TO_RETRY}", lines_input))

    line_indices = [l.index for l in batch]
    return BuiltPrompt(
        stage="polish",
        unit_key=f"batch_{batch_idx}",
        label=f"Batch {batch_idx + 1} ({len(batch)} dòng: "
              f"{line_indices[0]}-{line_indices[-1]})",
        prompt=prompt,
        meta={
            "batch_idx": batch_idx,
            "line_indices": line_indices,
            "json_root_key": "translations",
        },
    )


def _build_stage5(db: Session, project_id: int, config: PipelineConfig,
                  unit_key: Optional[str] = None) -> list[BuiltPrompt]:
    bible = _load_bible(db, project_id)
    all_lines, to_retry = _load_polish_lines(db, project_id)

    if not to_retry:
        return [BuiltPrompt(
            stage="polish",
            unit_key="empty",
            label="Stage 5 — Không có dòng cần retry",
            prompt="(Không cần chạy Stage 5 — không có dòng còn tiếng Trung / rỗng.)",
            meta={"empty": True},
        )]

    # Chia batch
    batches = []
    for i in range(0, len(to_retry), _POLISH_BATCH_SIZE):
        batches.append(to_retry[i:i + _POLISH_BATCH_SIZE])

    prompts = []
    for idx, batch in enumerate(batches):
        bk = f"batch_{idx}"
        if unit_key and unit_key != bk:
            continue
        prompts.append(_build_stage5_one_batch(
            batch, all_lines, bible, idx, config
        ))

    if unit_key and not prompts:
        raise ValueError(f"Không tìm thấy unit '{unit_key}' trong Stage 5")
    return prompts


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

# Map stage name → builder function
_STAGE_BUILDERS = {
    "normalize":       _build_stage0,
    "bible_cast":      _build_stage1a_cast,
    "bible_glossary":  _build_stage1a_glossary,
    "bible_world":     _build_stage1b_world,
    "chunks":          _build_stage2,
    "speaker":         _build_stage3,
    "translate":       _build_stage4,
    "polish":          _build_stage5,
}

# Stage có nhiều unit (cần unit_key)
_MULTI_UNIT_STAGES = {"chunks", "speaker", "translate", "polish"}


def build_prompt(
    stage: str,
    db: Session,
    project_id: int,
    config: PipelineConfig,
    unit_key: Optional[str] = None,
) -> list[BuiltPrompt]:
    """Build prompt cho 1 stage.

    Args:
        stage: tên stage (xem _STAGE_BUILDERS keys)
        db: SQLAlchemy session
        project_id: ID project
        config: PipelineConfig (dùng để load template, không cần api_key)
        unit_key: với multi-unit stages — chỉ build 1 unit cụ thể.
                  None → build TẤT CẢ unit (trả list nhiều phần tử).

    Returns:
        list BuiltPrompt. Single-unit stage trả list 1 phần tử.

    Raises:
        ValueError nếu stage không tồn tại, thiếu dependency (vd. Stage 2 cần Bible).
    """
    if stage not in _STAGE_BUILDERS:
        raise ValueError(
            f"Stage '{stage}' không hợp lệ. Hợp lệ: {list(_STAGE_BUILDERS.keys())}"
        )

    builder = _STAGE_BUILDERS[stage]

    # Single-unit stages
    if stage not in _MULTI_UNIT_STAGES:
        return builder(db, project_id, config)

    # Multi-unit stages
    return builder(db, project_id, config, unit_key=unit_key)


def list_units(
    stage: str,
    db: Session,
    project_id: int,
    config: PipelineConfig,
) -> list[StageUnit]:
    """Liệt kê các unit có sẵn cho 1 stage (không build prompt, chỉ metadata).

    Frontend dùng để hiển thị progress: stage đang ở unit nào, còn lại bao nhiêu.
    """
    if stage not in _STAGE_BUILDERS:
        raise ValueError(f"Stage '{stage}' không hợp lệ")

    if stage not in _MULTI_UNIT_STAGES:
        return [StageUnit(unit_key="default", label=stage)]

    # Multi-unit — build hết để lấy label (nhẹ hơn ko build prompt thực)
    if stage == "chunks":
        bible = _load_bible(db, project_id)
        return [
            StageUnit(
                unit_key=f"arc_{arc.index}",
                label=f"Arc {arc.index}: {arc.t} (dòng {arc.r[0]}-{arc.r[1]})",
            )
            for arc in bible.world.arcs
        ]

    if stage in ("speaker", "translate"):
        chunk_map = _load_chunk_map(db, project_id)
        return [
            StageUnit(
                unit_key=f"chunk_{c.r[0]}_{c.r[1]}",
                label=f"Chunk dòng {c.r[0]}-{c.r[1]}: {c.t or '(chưa đặt tên)'}",
            )
            for c in chunk_map.chunks
        ]

    if stage == "polish":
        try:
            _, to_retry = _load_polish_lines(db, project_id)
        except Exception:
            return []
        if not to_retry:
            return [StageUnit(unit_key="empty", label="Không có dòng cần retry")]
        batches_count = (len(to_retry) + _POLISH_BATCH_SIZE - 1) // _POLISH_BATCH_SIZE
        units = []
        for idx in range(batches_count):
            start = idx * _POLISH_BATCH_SIZE
            end = min(start + _POLISH_BATCH_SIZE, len(to_retry))
            batch = to_retry[start:end]
            units.append(StageUnit(
                unit_key=f"batch_{idx}",
                label=f"Batch {idx + 1} ({len(batch)} dòng: "
                      f"{batch[0].index}-{batch[-1].index})",
            ))
        return units

    return []
