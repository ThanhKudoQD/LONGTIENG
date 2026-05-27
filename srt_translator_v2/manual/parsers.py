"""
Parser & applier cho chế độ Dịch Thủ công.

Mỗi stage có hàm apply_<stage>(db, project_id, raw_response, meta, config):
  - parse raw_response (text user paste vào, có thể có ```json fence,
    có preamble từ AI, ...) → JSON
  - validate + transform thành cấu trúc V3 models
  - save vào DB (dùng lại save_*_to_db hiện có)
  - trả ApplyResult với thống kê
"""
from __future__ import annotations
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from sqlalchemy.orm import Session

_TRANSLATOR_DIR = Path(__file__).parent.parent
if str(_TRANSLATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATOR_DIR))

from config import PipelineConfig
from core.llm_client import parse_json_response

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────

@dataclass
class ApplyResult:
    """Kết quả apply 1 response."""
    stage: str
    unit_key: str
    ok: bool
    summary: str           # "Saved 42 characters", "Apply 12 chunks", ...
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Common helpers
# ─────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?", re.MULTILINE)
_FENCE_END_RE = re.compile(r"\n?```\s*$", re.MULTILINE)


def _clean_response(raw: str) -> str:
    """Clean raw response: strip markdown fence, trim whitespace."""
    if not raw:
        return ""
    s = raw.strip()
    s = _FENCE_RE.sub("", s)
    s = _FENCE_END_RE.sub("", s)
    return s.strip()


def _parse_json_safely(raw: str, default_root: Any) -> Any:
    """Parse JSON với fallback recovery (dùng parse_json_response của llm_client)."""
    cleaned = _clean_response(raw)
    if not cleaned:
        raise ValueError("Response rỗng sau khi clean")
    return parse_json_response(cleaned, default=default_root)


# ─────────────────────────────────────────────────────────────────
# Stage 0 — Normalize
# ─────────────────────────────────────────────────────────────────

def _apply_stage0(db: Session, project_id: int, raw_response: str,
                   meta: dict, config: PipelineConfig) -> ApplyResult:
    from stages.stage0_normalize import parse_decisions, apply_decisions
    from dubeditor.translate_service import db_subtitles_to_srt_entries
    from dubeditor.models import Subtitle

    if meta.get("empty"):
        return ApplyResult(
            stage="normalize",
            unit_key="default",
            ok=True,
            summary="Không có gì để apply (đã skip).",
        )

    data = _parse_json_safely(raw_response, default_root={"decisions": []})
    if not isinstance(data, dict):
        data = {"decisions": data if isinstance(data, list) else []}

    suspicious_indices = set(meta.get("suspicious_indices", []))
    if not suspicious_indices:
        return ApplyResult(
            stage="normalize", unit_key="default", ok=False,
            summary="Meta thiếu suspicious_indices — rebuild prompt rồi paste lại.",
            errors=["missing_meta"],
        )

    decisions = parse_decisions(data, suspicious_indices)

    # Load entries để apply
    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id)
              .order_by(Subtitle.index).all())
    entries = db_subtitles_to_srt_entries(subs)

    update_map = apply_decisions(entries, decisions)

    # Save vào DB (dùng lại logic _save_normalize_updates từ TranslateRunner)
    _save_normalize_updates(db, project_id, update_map)

    removed = sum(1 for d in decisions if d.action == "remove")
    cleaned = sum(1 for d in decisions if d.action == "clean")
    kept = sum(1 for d in decisions if d.action == "keep")

    return ApplyResult(
        stage="normalize",
        unit_key="default",
        ok=True,
        summary=f"Apply {len(decisions)} quyết định: "
                f"{removed} xóa, {cleaned} sửa, {kept} giữ",
        counts={"removed": removed, "cleaned": cleaned, "kept": kept,
                "total_decisions": len(decisions)},
    )


def _save_normalize_updates(db: Session, project_id: int, update_map: dict):
    """Inline copy của TranslateRunner._save_normalize_updates để không lệ thuộc class."""
    from dubeditor.models import Subtitle

    if not update_map:
        return
    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id)
              .all())
    by_idx = {s.index: s for s in subs}

    for idx, info in update_map.items():
        sub = by_idx.get(idx)
        if not sub:
            continue
        action = info.get("action")
        if action == "remove":
            sub.text = ""
            sub.is_noise = True
            if hasattr(sub, "normalize_action"):
                sub.normalize_action = "remove"
            if hasattr(sub, "normalize_reason"):
                sub.normalize_reason = info.get("reason", "")
        elif action == "clean":
            new_text = info.get("new_text", "")
            if hasattr(sub, "original_text") and not sub.original_text:
                sub.original_text = info.get("original_raw", sub.text)
            sub.text = new_text
            sub.is_noise = False
            if hasattr(sub, "normalize_action"):
                sub.normalize_action = "clean"
            if hasattr(sub, "normalize_reason"):
                sub.normalize_reason = info.get("reason", "")
    db.commit()


# ─────────────────────────────────────────────────────────────────
# Stage 1A.1 — Cast
# ─────────────────────────────────────────────────────────────────

def _apply_stage1a_cast(db: Session, project_id: int, raw_response: str,
                          meta: dict, config: PipelineConfig) -> ApplyResult:
    from models import Cast, Character, World, Glossary, Bible as V3Bible
    from dubeditor.translate_service import (
        load_active_bible_from_db, save_bible_to_db
    )

    data = _parse_json_safely(raw_response, default_root={"c": []})
    if not isinstance(data, dict):
        data = {"c": data if isinstance(data, list) else []}

    characters_raw = data.get("c") or data.get("characters") or []
    characters = []
    dropped_aliases = 0
    dropped_rels = 0
    warnings = []

    for ch_data in characters_raw:
        try:
            zh = (ch_data.get("z") or ch_data.get("zh") or "")
            # Dedupe alias (như Stage 1A logic chính)
            raw_alias = ch_data.get("a") or ch_data.get("alias") or []
            if not isinstance(raw_alias, list):
                raw_alias = []
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

            # Dedupe rel
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
            warnings.append(f"Skip character: {e}")

    if not characters:
        return ApplyResult(
            stage="bible_cast", unit_key="default", ok=False,
            summary="Không parse được nhân vật nào từ response.",
            errors=["no_characters_parsed"],
            warnings=warnings,
        )

    # Merge với Bible hiện có (giữ World + Glossary nếu đã tồn tại)
    existing = load_active_bible_from_db(db, project_id)
    if existing:
        bible = V3Bible(
            cast=Cast(characters=characters),
            world=existing.world,
            glossary=existing.glossary,
        )
    else:
        bible = V3Bible(
            cast=Cast(characters=characters),
            world=World(),
            glossary=Glossary(),
        )

    from core.llm_client import CostTracker
    save_bible_to_db(db, project_id, bible, CostTracker())

    notes = []
    if dropped_aliases:
        notes.append(f"deduped {dropped_aliases} alias trùng")
    if dropped_rels:
        notes.append(f"deduped {dropped_rels} rel trùng")
    notes_str = f" ({'; '.join(notes)})" if notes else ""

    return ApplyResult(
        stage="bible_cast",
        unit_key="default",
        ok=True,
        summary=f"Saved {len(characters)} nhân vật{notes_str}",
        counts={"characters": len(characters),
                "dropped_aliases": dropped_aliases,
                "dropped_rels": dropped_rels},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Stage 1A.2 — Glossary
# ─────────────────────────────────────────────────────────────────

def _apply_stage1a_glossary(db: Session, project_id: int, raw_response: str,
                              meta: dict, config: PipelineConfig) -> ApplyResult:
    from models import GlossaryTerm, Glossary, Cast, World, Bible as V3Bible
    from dubeditor.translate_service import (
        load_active_bible_from_db, save_bible_to_db
    )

    data = _parse_json_safely(raw_response, default_root={"t": []})
    if not isinstance(data, dict):
        data = {"t": data if isinstance(data, list) else []}

    raw_terms_input = data.get("t") or data.get("terms") or []
    raw_terms = []
    warnings = []

    for entry in raw_terms_input:
        try:
            if isinstance(entry, list):
                if len(entry) < 3:
                    continue
                z = entry[0] or ""
                v = entry[1] or ""
                c = entry[2] or "khac"
                n = entry[3] if len(entry) >= 4 else None
                if isinstance(n, str) and not n.strip():
                    n = None
            elif isinstance(entry, dict):
                z = entry.get("z") or entry.get("zh") or ""
                v = entry.get("v") or entry.get("vi") or ""
                c = entry.get("c") or entry.get("cat") or entry.get("category") or "khac"
                n = entry.get("n") or entry.get("note")
            else:
                continue

            if z and v:
                raw_terms.append(GlossaryTerm(zh=z, vi=v, cat=c, note=n))
        except Exception as e:
            warnings.append(f"Skip term: {e}")

    # Merge với Bible hiện có
    existing = load_active_bible_from_db(db, project_id)
    if existing:
        bible = V3Bible(
            cast=existing.cast,
            world=existing.world,
            glossary=Glossary(terms=raw_terms),
        )
    else:
        bible = V3Bible(
            cast=Cast(),
            world=World(),
            glossary=Glossary(terms=raw_terms),
        )

    from core.llm_client import CostTracker
    save_bible_to_db(db, project_id, bible, CostTracker())

    return ApplyResult(
        stage="bible_glossary",
        unit_key="default",
        ok=True,
        summary=f"Saved {len(raw_terms)} thuật ngữ",
        counts={"terms": len(raw_terms)},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Stage 1B — World + Arcs
# ─────────────────────────────────────────────────────────────────

def _apply_stage1b_world(db: Session, project_id: int, raw_response: str,
                          meta: dict, config: PipelineConfig) -> ApplyResult:
    from models import World, StoryArc, Bible as V3Bible
    from dubeditor.translate_service import (
        load_active_bible_from_db, save_bible_to_db
    )
    from stages.stage1_bible import _normalize_arcs

    data = _parse_json_safely(raw_response, default_root={})
    if not isinstance(data, dict):
        return ApplyResult(
            stage="bible_world", unit_key="default", ok=False,
            summary="Response không phải JSON object.",
            errors=["invalid_json"],
        )

    total_lines = int(meta.get("total_lines") or 0)

    arcs = []
    warnings = []
    for i, arc_data in enumerate(data.get("arcs", []) or []):
        try:
            r = arc_data.get("r", [1, total_lines or 1])
            if not isinstance(r, (list, tuple)) or len(r) != 2:
                r = [arc_data.get("start_line", 1),
                     arc_data.get("end_line", total_lines or 1)]
            arcs.append(StoryArc(
                index=arc_data.get("index", i),
                r=(int(r[0]), int(r[1])),
                t=arc_data.get("t", "") or arc_data.get("title", ""),
                summary=arc_data.get("summary", "") or arc_data.get("s", ""),
                tone=arc_data.get("tone", "neutral") or "neutral",
            ))
        except Exception as e:
            warnings.append(f"Skip arc: {e}")

    if not arcs:
        arcs.append(StoryArc(
            index=0, r=(1, total_lines or 1),
            t="Toàn phim", summary="", tone="neutral",
        ))

    arcs = _normalize_arcs(arcs, total_lines=(total_lines or 1),
                            max_arcs=config.chunk.max_arcs)

    VALID_GENRE_IDS = {
        "modern_ceo_romance", "ancient_palace", "reborn_revenge",
        "mafia_lord", "war_god_return", "other",
    }
    raw_genre_id = (data.get("genre_id") or "other").strip()
    if raw_genre_id not in VALID_GENRE_IDS:
        warnings.append(f"genre_id '{raw_genre_id}' không hợp lệ → fallback 'other'")
        raw_genre_id = "other"

    world = World(
        genre=data.get("genre", []) or [],
        genre_id=raw_genre_id,
        era=data.get("era", "hiện đại") or "hiện đại",
        tone=data.get("tone", "") or "",
        plot=data.get("plot", "") or "",
        arcs=arcs,
    )

    existing = load_active_bible_from_db(db, project_id)
    if existing:
        bible = V3Bible(cast=existing.cast, world=world, glossary=existing.glossary)
    else:
        from models import Cast, Glossary
        bible = V3Bible(cast=Cast(), world=world, glossary=Glossary())

    from core.llm_client import CostTracker
    save_bible_to_db(db, project_id, bible, CostTracker())

    return ApplyResult(
        stage="bible_world",
        unit_key="default",
        ok=True,
        summary=f"Saved World: genre={world.genre_id}, "
                f"{len(arcs)} arcs (era={world.era})",
        counts={"arcs": len(arcs)},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Stage 2 — Chunks + Scenes (per arc, merge vào ChunkMap)
# ─────────────────────────────────────────────────────────────────

def _apply_stage2(db: Session, project_id: int, raw_response: str,
                   meta: dict, config: PipelineConfig) -> ApplyResult:
    from models import ChunkMap as V3ChunkMap
    from stages.stage2_scenes import parse_chunk_dict, _normalize_chunks
    from dubeditor.translate_service import (
        load_chunks_from_db, save_chunks_to_db
    )

    arc_index = meta.get("arc_index")
    arc_range = meta.get("arc_range")
    if arc_index is None or not arc_range:
        return ApplyResult(
            stage="chunks", unit_key=meta.get("unit_key", "?"), ok=False,
            summary="Meta thiếu arc_index/arc_range.",
            errors=["missing_meta"],
        )

    data = _parse_json_safely(raw_response, default_root={"chunks": []})
    if not isinstance(data, dict):
        data = {"chunks": data if isinstance(data, list) else []}

    new_chunks = []
    warnings = []
    for c in data.get("chunks", []) or []:
        chunk = parse_chunk_dict(c, arc_index)
        if chunk:
            new_chunks.append(chunk)

    if not new_chunks:
        return ApplyResult(
            stage="chunks", unit_key=f"arc_{arc_index}", ok=False,
            summary="Không parse được chunk nào.",
            errors=["no_chunks_parsed"],
        )

    # Normalize chunks của arc này
    from models import StoryArc
    arc_stub = StoryArc(index=arc_index, r=(arc_range[0], arc_range[1]),
                         t="", summary="", tone="neutral")
    new_chunks = _normalize_chunks(new_chunks, arc_stub)

    # Merge với chunks hiện có: thay thế chunks của arc này, giữ arcs khác
    existing_cm = load_chunks_from_db(db, project_id)
    other_chunks = [c for c in existing_cm.chunks if c.arc_index != arc_index]
    merged = sorted(other_chunks + new_chunks,
                     key=lambda c: (c.arc_index, c.r[0]))
    new_cm = V3ChunkMap(chunks=merged)

    save_chunks_to_db(db, project_id, new_cm)

    return ApplyResult(
        stage="chunks",
        unit_key=f"arc_{arc_index}",
        ok=True,
        summary=f"Saved {len(new_chunks)} chunks cho arc {arc_index} "
                f"({sum(len(c.scenes) for c in new_chunks)} scenes)",
        counts={"chunks": len(new_chunks),
                "scenes": sum(len(c.scenes) for c in new_chunks)},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Stage 3 — Speaker (per chunk)
# ─────────────────────────────────────────────────────────────────

def _apply_stage3(db: Session, project_id: int, raw_response: str,
                   meta: dict, config: PipelineConfig) -> ApplyResult:
    from dubeditor.translate_service import (
        save_speakers_to_db, load_active_bible_from_db
    )

    chunk_range = meta.get("chunk_range")
    if not chunk_range:
        return ApplyResult(
            stage="speaker", unit_key="?", ok=False,
            summary="Meta thiếu chunk_range.",
            errors=["missing_meta"],
        )
    start, end = chunk_range[0], chunk_range[1]

    data = _parse_json_safely(raw_response, default_root={"speakers": []})
    if not isinstance(data, dict):
        data = {"speakers": data if isinstance(data, list) else []}

    speaker_results = {}
    warnings = []

    for entry in data.get("speakers", []) or []:
        try:
            if isinstance(entry, dict):
                line_idx = int(entry.get("line_index") or entry.get("idx", -1))
                speaker_zh = str(entry.get("speaker_zh") or entry.get("speaker", ""))
                confidence = str(entry.get("confidence", "l"))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 3:
                line_idx = int(entry[0])
                speaker_zh = str(entry[1])
                confidence = str(entry[2])
            else:
                continue

            if line_idx < 1 or not (start <= line_idx <= end):
                continue

            confidence = confidence.lower()
            if confidence not in ("h", "m", "l"):
                confidence = "l"

            speaker_results[line_idx] = {
                "speaker_zh": speaker_zh if speaker_zh != "?" else None,
                "confidence": confidence,
            }
        except Exception as e:
            warnings.append(f"Skip speaker entry: {e}")

    if not speaker_results:
        return ApplyResult(
            stage="speaker", unit_key=f"chunk_{start}_{end}", ok=False,
            summary="Không parse được speaker nào.",
            errors=["no_speakers_parsed"],
        )

    bible = load_active_bible_from_db(db, project_id)
    if not bible:
        return ApplyResult(
            stage="speaker", unit_key=f"chunk_{start}_{end}", ok=False,
            summary="Thiếu Bible — chạy Stage 1 trước.",
            errors=["missing_bible"],
        )

    save_speakers_to_db(db, project_id, speaker_results, bible)

    high = sum(1 for v in speaker_results.values() if v["confidence"] == "h")
    mid = sum(1 for v in speaker_results.values() if v["confidence"] == "m")
    low = sum(1 for v in speaker_results.values() if v["confidence"] == "l")

    return ApplyResult(
        stage="speaker",
        unit_key=f"chunk_{start}_{end}",
        ok=True,
        summary=f"Saved {len(speaker_results)} speaker "
                f"(h:{high}, m:{mid}, l:{low})",
        counts={"total": len(speaker_results), "h": high, "m": mid, "l": low},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Stage 4 — Translate (per chunk)
# ─────────────────────────────────────────────────────────────────

def _apply_stage4(db: Session, project_id: int, raw_response: str,
                   meta: dict, config: PipelineConfig) -> ApplyResult:
    from dubeditor.translate_service import (
        save_translations_to_db, load_active_bible_from_db
    )

    chunk_range = meta.get("chunk_range")
    if not chunk_range:
        return ApplyResult(
            stage="translate", unit_key="?", ok=False,
            summary="Meta thiếu chunk_range.",
            errors=["missing_meta"],
        )
    start, end = chunk_range[0], chunk_range[1]

    data = _parse_json_safely(raw_response, default_root={"t": []})
    if not isinstance(data, dict):
        data = {"t": data if isinstance(data, list) else []}

    items = data.get("t") or data.get("translations") or []
    translation_results = {}
    warnings = []
    noise_count = 0

    for entry in items:
        try:
            if isinstance(entry, list):
                if len(entry) < 2:
                    continue
                line_idx = int(entry[0])
                text_v1_raw = entry[1] if len(entry) >= 2 else None
                text_v2_raw = entry[2] if len(entry) >= 3 else None
            elif isinstance(entry, dict):
                line_idx = int(entry.get("line_index", -1))
                text_v1_raw = entry.get("text_v1")
                text_v2_raw = entry.get("text_v2")
            else:
                continue

            if line_idx < 1 or not (start <= line_idx <= end):
                continue

            text_v1 = (text_v1_raw or "").strip() if isinstance(text_v1_raw, str) else ""
            text_v2 = None
            if isinstance(text_v2_raw, str):
                text_v2 = text_v2_raw.strip() or None

            # AI tự quyết noise bằng text_v1=""
            is_noise = not text_v1
            if is_noise:
                noise_count += 1

            translation_results[line_idx] = {
                "text_v1": text_v1,
                "text_v2": text_v2,
                "is_noise": is_noise,
            }
        except Exception as e:
            warnings.append(f"Skip translation entry: {e}")

    if not translation_results:
        return ApplyResult(
            stage="translate", unit_key=f"chunk_{start}_{end}", ok=False,
            summary="Không parse được dòng dịch nào.",
            errors=["no_translations_parsed"],
        )

    bible = load_active_bible_from_db(db, project_id)
    if not bible:
        return ApplyResult(
            stage="translate", unit_key=f"chunk_{start}_{end}", ok=False,
            summary="Thiếu Bible.",
            errors=["missing_bible"],
        )

    save_translations_to_db(db, project_id, translation_results, bible)

    variants = sum(1 for v in translation_results.values() if v.get("text_v2"))
    return ApplyResult(
        stage="translate",
        unit_key=f"chunk_{start}_{end}",
        ok=True,
        summary=f"Saved {len(translation_results)} dòng dịch "
                f"({variants} có v2, {noise_count} noise)",
        counts={"total": len(translation_results),
                "variants_v2": variants,
                "noise": noise_count},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Stage 5 — Polish (per batch)
# ─────────────────────────────────────────────────────────────────

def _apply_stage5(db: Session, project_id: int, raw_response: str,
                   meta: dict, config: PipelineConfig) -> ApplyResult:
    from dubeditor.models import Subtitle
    from core.srt_parser import calculate_cps

    if meta.get("empty"):
        return ApplyResult(
            stage="polish", unit_key="empty", ok=True,
            summary="Không có gì để apply.",
        )

    line_indices = meta.get("line_indices") or []
    if not line_indices:
        return ApplyResult(
            stage="polish", unit_key=meta.get("unit_key", "?"), ok=False,
            summary="Meta thiếu line_indices.",
            errors=["missing_meta"],
        )

    data = _parse_json_safely(raw_response, default_root={"translations": []})
    if not isinstance(data, dict):
        data = {"translations": data if isinstance(data, list) else []}

    target_set = set(line_indices)
    updates = {}
    warnings = []

    for t in data.get("translations", []) or []:
        try:
            if isinstance(t, list):
                if len(t) < 2:
                    continue
                line_idx = int(t[0])
                text_v1 = (t[1] or "").strip() if isinstance(t[1], str) else ""
                text_v2 = None
                if len(t) >= 3 and isinstance(t[2], str):
                    text_v2 = t[2].strip() or None
            elif isinstance(t, dict):
                line_idx = int(t.get("line_index", -1))
                text_v1 = (t.get("text_v1") or "").strip()
                text_v2 = t.get("text_v2")
                if isinstance(text_v2, str):
                    text_v2 = text_v2.strip() or None
                else:
                    text_v2 = None
            else:
                continue

            if line_idx not in target_set or not text_v1:
                continue
            updates[line_idx] = {"text_v1": text_v1, "text_v2": text_v2}
        except Exception as e:
            warnings.append(f"Skip retry entry: {e}")

    if not updates:
        return ApplyResult(
            stage="polish", unit_key=meta.get("unit_key", "?"), ok=False,
            summary="Không parse được dòng dịch lại nào.",
            errors=["no_retries_parsed"],
        )

    # Apply vào DB
    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id,
                       Subtitle.index.in_(list(updates.keys())))
              .all())
    for sub in subs:
        info = updates.get(sub.index)
        if not info:
            continue
        sub.text_v1 = info["text_v1"]
        sub.text_v2 = info.get("text_v2")
        sub.text = info["text_v1"]
        duration = max(0.01, sub.end_time - sub.start_time)
        sub.cps_value = calculate_cps(info["text_v1"], duration)
        # Clear flag — dòng đã được retry thành công
        sub.needs_review = False
        sub.review_reason = None
        sub.is_noise = False
    db.commit()

    return ApplyResult(
        stage="polish",
        unit_key=meta.get("unit_key", "?"),
        ok=True,
        summary=f"Apply retry cho {len(updates)}/{len(line_indices)} dòng",
        counts={"applied": len(updates), "expected": len(line_indices)},
        warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────

_STAGE_APPLIERS = {
    "normalize":       _apply_stage0,
    "bible_cast":      _apply_stage1a_cast,
    "bible_glossary":  _apply_stage1a_glossary,
    "bible_world":     _apply_stage1b_world,
    "chunks":          _apply_stage2,
    "speaker":         _apply_stage3,
    "translate":       _apply_stage4,
    "polish":          _apply_stage5,
}


def apply_response(
    stage: str,
    db: Session,
    project_id: int,
    raw_response: str,
    meta: dict,
    config: PipelineConfig,
) -> ApplyResult:
    """Parse response user paste vào và save vào DB.

    Args:
        stage: tên stage (xem _STAGE_APPLIERS keys)
        db: SQLAlchemy session
        project_id: ID project
        raw_response: text user paste (có thể chứa fence ```json, preamble AI)
        meta: metadata từ BuiltPrompt khi build prompt (chứa line_range, ...)
        config: PipelineConfig

    Returns:
        ApplyResult với ok=True/False, summary, counts, warnings, errors.
    """
    if stage not in _STAGE_APPLIERS:
        return ApplyResult(
            stage=stage, unit_key="?", ok=False,
            summary=f"Stage '{stage}' không hợp lệ",
            errors=["invalid_stage"],
        )

    if not raw_response or not raw_response.strip():
        return ApplyResult(
            stage=stage, unit_key=meta.get("unit_key", "?"), ok=False,
            summary="Response rỗng",
            errors=["empty_response"],
        )

    applier = _STAGE_APPLIERS[stage]
    try:
        return applier(db, project_id, raw_response, meta or {}, config)
    except Exception as e:
        logger.exception(f"[manual.apply] stage={stage} failed")
        return ApplyResult(
            stage=stage, unit_key=meta.get("unit_key", "?"), ok=False,
            summary=f"Lỗi khi apply: {type(e).__name__}: {e}",
            errors=[str(e)],
        )
