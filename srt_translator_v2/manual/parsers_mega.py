"""
Parsers cho mega-chunk manual mode (v4).

Parse response JSON từ user paste vào → save DB.

Format mới khác v3:
  - translate: {"lines": [{"i", "spk", "v1", "v2"}], "new_terms": [...]}
  - bible_unified: {"cast": {...}, "world": {...}, "glossary": {...}}
  - chunks_full: {"chunks": [...]}
  - review_pass1: {"decisions": [...]}
  - review_pass2: {"fixes": [...], "arc_notes": "..."}
"""
from __future__ import annotations
import json
import logging
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
from manual.parsers import ApplyResult, _clean_response, _parse_json_safely

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════
# STAGE: BIBLE UNIFIED
# ═════════════════════════════════════════════════════════════════

def _apply_bible_unified(
    db: Session, project_id: int, raw_response: str,
    meta: dict, config: PipelineConfig,
) -> ApplyResult:
    """Parse JSON gộp cast+world+glossary → save 3 phần riêng vào DB.

    Format mới v4.1:
      - Character có thêm tier, line_count, catchphrase
      - Glossary chia 5 nhóm: titles, places_orgs, concepts, cliches, idioms
        (parser flatten về 1 list GlossaryTerm với field `cat` phân loại)
    Format cũ (terms list) vẫn được hỗ trợ.
    """
    from dubeditor.translate_service import (
        save_bible_to_db, load_active_bible_from_db,
    )
    from models import (
        Bible as V3Bible, Cast as V3Cast, World as V3World,
        Glossary as V3Glossary, Character as V3Character,
        GlossaryTerm, StoryArc,
    )

    data = _parse_json_safely(raw_response, default_root={})
    if not isinstance(data, dict):
        return ApplyResult(
            stage="bible_unified", unit_key="default", ok=False,
            summary="Response không phải JSON object.",
            errors=["invalid_root"],
        )

    cast_data = data.get("cast") or {}
    world_data = data.get("world") or {}
    glossary_data = data.get("glossary") or {}

    warnings = []
    errors = []

    # --- CAST ---
    chars_raw = cast_data.get("characters") or []
    characters = []
    for c in chars_raw:
        try:
            kwargs = dict(
                zh=c.get("zh", "").strip(),
                vi=c.get("vi", "").strip(),
                alias=c.get("alias") or [],
                g=c.get("g") or "?",
                role=c.get("role") or "phu",
                age=c.get("age"),
                char=c.get("char") or "",
                rel=c.get("rel") or {},
            )
            # v4.1 optional fields — chỉ pass nếu Character model có
            for opt in ("tier", "line_count", "catchphrase"):
                if opt in c:
                    kwargs[opt] = c[opt]
            try:
                characters.append(V3Character(**kwargs))
            except TypeError:
                # Model cũ không có v4.1 fields — strip rồi retry
                for opt in ("tier", "line_count", "catchphrase"):
                    kwargs.pop(opt, None)
                characters.append(V3Character(**kwargs))
        except Exception as e:
            warnings.append(f"Skip character {c.get('zh', '?')}: {e}")

    if not characters:
        errors.append("không parse được nhân vật nào")
        return ApplyResult(
            stage="bible_unified", unit_key="default", ok=False,
            summary="Cast rỗng — không tạo Bible được.",
            errors=errors, warnings=warnings,
        )

    cast = V3Cast(characters=characters)

    # --- WORLD ---
    arcs_raw = world_data.get("arcs") or []
    arcs = []
    for i, a in enumerate(arcs_raw):
        try:
            r = a.get("r") or [0, 0]
            arcs.append(StoryArc(
                index=a.get("index", i),
                r=tuple(r),
                t=a.get("t") or f"Arc {i}",
                tone=a.get("tone") or "neutral",
                summary=a.get("summary"),
            ))
        except Exception as e:
            warnings.append(f"Skip arc {i}: {e}")

    # v4.2: VALIDATE arcs coverage — phải cover [1, total_subs], không gap, không overlap
    try:
        from dubeditor.models import Subtitle as DBSubtitle
        total_subs = (db.query(DBSubtitle.index)
                        .filter(DBSubtitle.project_id == project_id)
                        .count())
    except Exception:
        total_subs = 0

    if arcs and total_subs > 0:
        # Sort by start
        arcs_sorted = sorted(arcs, key=lambda x: x.r[0])

        # Check + auto-fix
        fixed_arcs = []
        prev_end = 0
        for idx, a in enumerate(arcs_sorted):
            s, e = a.r[0], a.r[1]

            # Clip end về total_subs
            if e > total_subs:
                warnings.append(
                    f"Arc {idx} ({a.t}): r[1]={e} vượt total {total_subs}, clip về {total_subs}"
                )
                e = total_subs

            # Fix gap: nếu arc đầu không bắt đầu từ 1, force = 1
            if idx == 0 and s != 1:
                warnings.append(f"Arc 0 không bắt đầu từ dòng 1 (was {s}), fix về 1")
                s = 1
            # Fix gap giữa arcs: nếu start > prev_end+1, lùi về prev_end+1
            elif idx > 0 and s > prev_end + 1:
                warnings.append(
                    f"Arc {idx} ({a.t}): gap từ {prev_end + 1} đến {s - 1}, fix start về {prev_end + 1}"
                )
                s = prev_end + 1
            # Fix overlap: nếu start <= prev_end, đẩy lên prev_end + 1
            elif idx > 0 and s <= prev_end:
                warnings.append(
                    f"Arc {idx} ({a.t}): overlap với arc trước (start={s} <= prev_end={prev_end}), "
                    f"fix start về {prev_end + 1}"
                )
                s = prev_end + 1

            # Đảm bảo s <= e
            if s > e:
                warnings.append(f"Arc {idx} ({a.t}): start>end sau fix, skip arc này")
                continue

            fixed_arcs.append(StoryArc(
                index=len(fixed_arcs),
                r=(s, e),
                t=a.t,
                tone=a.tone,
                summary=getattr(a, "summary", None),
            ))
            prev_end = e

        # Extend arc cuối tới total_subs nếu chưa cover
        if fixed_arcs and fixed_arcs[-1].r[1] < total_subs:
            last = fixed_arcs[-1]
            warnings.append(
                f"Arc cuối ({last.t}) chỉ cover tới {last.r[1]}, "
                f"extend tới {total_subs} (LLM đã ảo giác về độ dài phim)"
            )
            fixed_arcs[-1] = StoryArc(
                index=last.index,
                r=(last.r[0], total_subs),
                t=last.t,
                tone=last.tone,
                summary=getattr(last, "summary", None),
            )

        arcs = fixed_arcs

    world = V3World(
        genre=world_data.get("genre") or [],
        genre_id=world_data.get("genre_id") or "other",
        era=world_data.get("era") or "?",
        tone=world_data.get("tone") or "",
        plot=world_data.get("plot") or "",
        arcs=arcs,
    )

    # --- GLOSSARY ---
    # Hỗ trợ 2 format: v4.1 (5 nhóm) hoặc v3 cũ (terms list)
    terms = []

    # Format mới v4.1: 5 nhóm riêng
    GLOSSARY_GROUPS = [
        ("titles", "title"),
        ("places_orgs", "place_org"),
        ("concepts", "concept"),
        ("cliches", "cliche"),
        ("idioms", "idiom"),
    ]
    parsed_new_format = False
    for group_key, cat_value in GLOSSARY_GROUPS:
        items = glossary_data.get(group_key)
        if not isinstance(items, list):
            continue
        parsed_new_format = True
        for t in items:
            if not isinstance(t, dict):
                continue
            try:
                zh = (t.get("zh") or "").strip()
                vi = (t.get("vi") or "").strip()
                if not zh or not vi:
                    continue
                term_kwargs = dict(
                    zh=zh, vi=vi, cat=cat_value,
                    note=t.get("note"),
                )
                # v4.1 optional fields
                for opt in ("n", "type", "usage", "trope", "register"):
                    if opt in t:
                        term_kwargs[opt] = t[opt]
                try:
                    terms.append(GlossaryTerm(**term_kwargs))
                except TypeError:
                    # Model cũ không có optional fields
                    for opt in ("n", "type", "usage", "trope", "register"):
                        term_kwargs.pop(opt, None)
                    terms.append(GlossaryTerm(**term_kwargs))
            except Exception as e:
                warnings.append(f"Skip term {t.get('zh', '?')}: {e}")

    # Format v3 fallback: terms list
    if not parsed_new_format:
        terms_raw = glossary_data.get("terms") or []
        for t in terms_raw:
            try:
                terms.append(GlossaryTerm(
                    zh=t.get("zh", "").strip(),
                    vi=t.get("vi", "").strip(),
                    cat=t.get("cat", "khac"),
                    note=t.get("note"),
                ))
            except Exception as e:
                warnings.append(f"Skip term {t.get('zh', '?')}: {e}")

    glossary = V3Glossary(terms=terms)

    bible = V3Bible(cast=cast, world=world, glossary=glossary)

    # Save DB
    try:
        save_bible_to_db(db, project_id, bible)
    except Exception as e:
        errors.append(f"DB save failed: {e}")
        return ApplyResult(
            stage="bible_unified", unit_key="default", ok=False,
            summary=f"Lỗi save DB: {e}",
            errors=errors, warnings=warnings,
        )

    # Stats breakdown
    cast_by_tier = {}
    for ch in characters:
        tier = getattr(ch, "tier", None) or "(no_tier)"
        cast_by_tier[tier] = cast_by_tier.get(tier, 0) + 1
    cast_summary = ", ".join(f"{k}={v}" for k, v in cast_by_tier.items())

    terms_by_cat = {}
    for t in terms:
        c = t.cat or "khac"
        terms_by_cat[c] = terms_by_cat.get(c, 0) + 1
    terms_summary = ", ".join(f"{k}={v}" for k, v in terms_by_cat.items())

    summary_text = (
        f"Saved Bible: {len(characters)} nhân vật"
        + (f" ({cast_summary})" if cast_summary else "")
        + f", {len(arcs)} arcs"
        + f", {len(terms)} glossary terms"
        + (f" [{terms_summary}]" if terms_summary else "")
    )

    return ApplyResult(
        stage="bible_unified", unit_key="default", ok=True,
        summary=summary_text,
        counts={
            "characters": len(characters),
            "arcs": len(arcs),
            "terms": len(terms),
            **{f"cast_{k}": v for k, v in cast_by_tier.items()},
            **{f"terms_{k}": v for k, v in terms_by_cat.items()},
        },
        warnings=warnings,
    )


# ═════════════════════════════════════════════════════════════════
# STAGE: CHUNKS + SCENES FULL
# ═════════════════════════════════════════════════════════════════

def _apply_chunks_full(
    db: Session, project_id: int, raw_response: str,
    meta: dict, config: PipelineConfig,
) -> ApplyResult:
    """Parse chunks + scenes toàn phim → save DB."""
    from dubeditor.translate_service import save_chunks_to_db
    from models import ChunkMap as V3ChunkMap, Chunk as V3Chunk, Scene as V3Scene

    data = _parse_json_safely(raw_response, default_root={"chunks": []})
    if not isinstance(data, dict):
        return ApplyResult(
            stage="chunks_full", unit_key="default", ok=False,
            summary="Response không phải JSON object.",
            errors=["invalid_root"],
        )

    chunks_raw = data.get("chunks") or []
    if not chunks_raw:
        return ApplyResult(
            stage="chunks_full", unit_key="default", ok=False,
            summary="Không parse được chunk nào.",
            errors=["no_chunks"],
        )

    warnings = []
    chunks = []
    for i, c in enumerate(chunks_raw):
        try:
            r = c.get("r") or [0, 0]
            arc_index = c.get("arc_index", 0)
            title = c.get("t") or f"chunk_{i}"
            scenes_raw = c.get("scenes") or []
            scenes = []
            for sc in scenes_raw:
                try:
                    sc_r = sc.get("r") or [0, 0]
                    scenes.append(V3Scene(
                        r=tuple(sc_r),
                        ch=sc.get("ch") or [],
                        e=sc.get("e") or "neutral",
                        intensity=sc.get("intensity", 5),
                        loc=sc.get("loc") or "",
                        tag=sc.get("tag"),
                    ))
                except Exception as e:
                    warnings.append(f"Skip scene in chunk {i}: {e}")
            chunks.append(V3Chunk(
                r=tuple(r),
                t=title,
                arc_index=arc_index,
                scenes=scenes,
            ))
        except Exception as e:
            warnings.append(f"Skip chunk {i}: {e}")

    if not chunks:
        return ApplyResult(
            stage="chunks_full", unit_key="default", ok=False,
            summary="Tất cả chunks fail parse.",
            errors=["all_chunks_failed"],
            warnings=warnings,
        )

    chunk_map = V3ChunkMap(chunks=chunks)

    try:
        save_chunks_to_db(db, project_id, chunk_map)
    except Exception as e:
        return ApplyResult(
            stage="chunks_full", unit_key="default", ok=False,
            summary=f"DB save failed: {e}",
            errors=[str(e)],
            warnings=warnings,
        )

    total_scenes = sum(len(c.scenes) for c in chunks)
    return ApplyResult(
        stage="chunks_full", unit_key="default", ok=True,
        summary=f"Saved {len(chunks)} chunks, {total_scenes} scenes",
        counts={"chunks": len(chunks), "scenes": total_scenes},
        warnings=warnings,
    )


# ═════════════════════════════════════════════════════════════════
# STAGE: TRANSLATE MEGA (gộp speaker + translate + new_terms)
# ═════════════════════════════════════════════════════════════════

def _apply_translate_mega(
    db: Session, project_id: int, raw_response: str,
    meta: dict, config: PipelineConfig,
) -> ApplyResult:
    """Parse JSON `{lines: [{i, spk, v1, v2}], new_terms: [...]}` → save DB.

    v4.3:
      - Hỗ trợ 3 speaker_mode: full / medium / simple (đọc từ meta.speaker_mode)
      - Mode FULL: gán speaker_zh + link character_id (như v4.2)
      - Mode MEDIUM: gán speaker_zh + map sang 1 trong 7 slot, lưu Subtitle.speaker_slot
      - Mode SIMPLE: spk = M/F → lưu trực tiếp speaker_slot
    """
    from dubeditor.translate_service import (
        save_translations_to_db, load_active_bible_from_db,
        save_speakers_to_db,
    )
    from dubeditor.models import Subtitle, Character
    from manual.speaker_modes import (
        MODE_INFO, build_character_to_slot_map, resolve_slot_from_speaker,
    )

    line_range = meta.get("line_range") or [0, 0]
    start, end = line_range[0], line_range[1]

    # v4.3: đọc speaker_mode từ meta (default full để backward compat)
    speaker_mode = meta.get("speaker_mode") or "full"
    if speaker_mode not in MODE_INFO:
        speaker_mode = "full"

    # v4.2 fix: fallback nếu meta thiếu line_range
    if not (start and end and start <= end):
        rng = (db.query(Subtitle.index)
                 .filter(Subtitle.project_id == project_id)
                 .order_by(Subtitle.index).all())
        if rng:
            start = rng[0][0]
            end = rng[-1][0]
            logger.warning(
                f"[mega translate] meta thiếu line_range, fallback "
                f"toàn project [{start}, {end}]"
            )
        else:
            return ApplyResult(
                stage="translate_mega",
                unit_key=str(meta.get("mega_index", "?")),
                ok=False, summary="Meta thiếu line_range và project rỗng.",
                errors=["missing_line_range"],
            )

    data = _parse_json_safely(raw_response, default_root={"lines": [], "new_terms": []})
    if not isinstance(data, dict):
        return ApplyResult(
            stage="translate_mega", unit_key=str(meta.get("mega_index", "?")),
            ok=False, summary="Response không phải JSON object.",
            errors=["invalid_root"],
        )

    lines = data.get("lines") or []
    new_terms = data.get("new_terms") or []

    if not lines:
        return ApplyResult(
            stage="translate_mega", unit_key=f"mega_{meta.get('mega_index', '?')}",
            ok=False, summary="Không parse được dòng dịch nào.",
            errors=["no_lines"],
        )

    bible = load_active_bible_from_db(db, project_id)
    if not bible:
        return ApplyResult(
            stage="translate_mega", unit_key=f"mega_{meta.get('mega_index', '?')}",
            ok=False, summary="Thiếu Bible — chạy build_bible trước.",
            errors=["missing_bible"],
        )

    # v4.3: build char→slot map (chỉ cần cho mode medium/simple)
    char_to_slot = build_character_to_slot_map(bible, speaker_mode)

    warnings = []
    translation_results = {}
    speaker_updates = {}      # idx → speaker_zh raw
    slot_updates = {}         # idx → slot key (medium/simple)
    v2_missing_count = 0
    v2_count = 0
    noise_count = 0
    slot_resolved_count = 0
    slot_unresolved_count = 0

    for entry in lines:
        try:
            if not isinstance(entry, dict):
                warnings.append(f"Skip non-dict entry: {entry}")
                continue

            line_idx = int(entry.get("i", -1))
            if line_idx < 1:
                continue
            if not (start <= line_idx <= end):
                warnings.append(f"Line {line_idx} ngoài range mega [{start}, {end}], skip")
                continue

            spk = (entry.get("spk") or "").strip() or "?"
            v1_raw = entry.get("v1")
            v2_raw = entry.get("v2")

            v1 = v1_raw.strip() if isinstance(v1_raw, str) else ""
            v2 = None
            if isinstance(v2_raw, str):
                v2_stripped = v2_raw.strip()
                v2 = v2_stripped if v2_stripped else None

            is_noise = not v1
            if is_noise:
                noise_count += 1
            else:
                if v2:
                    v2_count += 1
                else:
                    v2_missing_count += 1
                    v2 = v1

            translation_results[line_idx] = {
                "text_v1": v1,
                "text_v2": v2,
                "is_noise": is_noise,
            }

            # v4.3: xử lý speaker theo mode
            if not is_noise and spk and spk != "?":
                if speaker_mode == "full":
                    # Như v4.2: speaker_zh = tên TQ, link character_id
                    speaker_updates[line_idx] = spk
                elif speaker_mode == "simple":
                    # spk có thể là "M"/"F" trực tiếp HOẶC tên TQ (fallback)
                    slot = resolve_slot_from_speaker(spk, "simple", char_to_slot)
                    if slot:
                        slot_updates[line_idx] = slot
                        slot_resolved_count += 1
                        # Vẫn lưu speaker_zh nếu là tên TQ thật
                        if spk not in ("M", "F", "m", "f"):
                            speaker_updates[line_idx] = spk
                    else:
                        slot_unresolved_count += 1
                        warnings.append(
                            f"Line {line_idx}: spk='{spk}' không phải M/F và "
                            f"không tra được trong Bible"
                        )
                else:  # medium
                    # AI gán tên TQ → tool map sang slot
                    slot = resolve_slot_from_speaker(spk, "medium", char_to_slot)
                    if slot:
                        slot_updates[line_idx] = slot
                        slot_resolved_count += 1
                        # Vẫn lưu speaker_zh để giữ data character
                        speaker_updates[line_idx] = spk
                    else:
                        slot_unresolved_count += 1
                        # Vẫn lưu speaker_zh dù không map được slot
                        speaker_updates[line_idx] = spk
                        warnings.append(
                            f"Line {line_idx}: không map được speaker '{spk}' "
                            f"sang slot — character này có thể chưa có trong Bible"
                        )
        except Exception as e:
            warnings.append(f"Skip entry {entry}: {e}")

    if not translation_results:
        return ApplyResult(
            stage="translate_mega", unit_key=f"mega_{meta.get('mega_index', '?')}",
            ok=False, summary="Không có dòng nào parse được.",
            errors=["all_failed"],
            warnings=warnings,
        )

    if v2_missing_count:
        warnings.append(
            f"{v2_missing_count} dòng thiếu v2 (đã fallback v2=v1). "
            f"LLM cần trả về cả v1+v2 cho mọi dòng thoại."
        )

    # Save translations
    try:
        save_translations_to_db(db, project_id, translation_results, bible)
    except Exception as e:
        return ApplyResult(
            stage="translate_mega", unit_key=f"mega_{meta.get('mega_index', '?')}",
            ok=False, summary=f"Save translations failed: {e}",
            errors=[str(e)], warnings=warnings,
        )

    # Save speaker_zh + link character_id (chỉ với mode full/medium có spk dạng tên TQ)
    speakers_saved = 0
    chars_linked = 0
    if speaker_updates:
        try:
            speaker_results = {
                idx: {"speaker_zh": spk, "confidence": "h"}
                for idx, spk in speaker_updates.items()
            }
            save_speakers_to_db(db, project_id, speaker_results, bible)
            speakers_saved = len(speaker_results)
            linked = (db.query(Subtitle.id)
                        .filter(Subtitle.project_id == project_id,
                                Subtitle.index.in_(list(speaker_updates.keys())),
                                Subtitle.character_id.isnot(None))
                        .count())
            chars_linked = linked
        except Exception as e:
            db.rollback()
            warnings.append(f"Speaker save partial failed: {e}")

    # v4.3: Save speaker_slot vào Subtitle (mode medium/simple)
    slots_saved = 0
    if slot_updates:
        try:
            if hasattr(Subtitle, "speaker_slot"):
                subs = (db.query(Subtitle)
                          .filter(Subtitle.project_id == project_id,
                                  Subtitle.index.in_(list(slot_updates.keys())))
                          .all())
                for s in subs:
                    slot = slot_updates.get(s.index)
                    if slot:
                        s.speaker_slot = slot
                        slots_saved += 1
                db.commit()
            else:
                warnings.append(
                    "Field Subtitle.speaker_slot chưa migrate — "
                    "restart server sau khi update models.py"
                )
        except Exception as e:
            db.rollback()
            warnings.append(f"Save speaker_slot failed: {e}")

    # Merge new_terms vào Bible glossary
    new_terms_added = 0
    if new_terms:
        try:
            new_terms_added = _merge_new_terms_to_bible(db, project_id, bible, new_terms)
        except Exception as e:
            warnings.append(f"new_terms merge failed: {e}")

    # Build summary theo mode
    if speaker_mode == "full":
        spk_summary = f"speakers: {speakers_saved} (link NV: {chars_linked})"
    else:
        spk_summary = (f"slots: {slots_saved}/{slot_resolved_count} resolved, "
                       f"{slot_unresolved_count} unresolved")

    return ApplyResult(
        stage="translate_mega",
        unit_key=f"mega_{meta.get('mega_index', '?')}",
        ok=True,
        summary=(f"[Mode {speaker_mode}] Saved {len(translation_results)} dòng "
                 f"(v2 đủ: {v2_count}, v2 thiếu: {v2_missing_count}, "
                 f"noise: {noise_count}, {spk_summary}, "
                 f"new_terms: {new_terms_added})"),
        counts={
            "total": len(translation_results),
            "v2": v2_count,
            "v2_missing": v2_missing_count,
            "noise": noise_count,
            "speakers_saved": speakers_saved,
            "characters_linked": chars_linked,
            "slots_saved": slots_saved,
            "slots_unresolved": slot_unresolved_count,
            "new_terms_added": new_terms_added,
            "speaker_mode": speaker_mode,
        },
        warnings=warnings,
    )


def _merge_new_terms_to_bible(db: Session, project_id: int, bible, new_terms: list) -> int:
    """Merge new_terms từ AI vào Bible glossary (chỉ thêm term chưa có)."""
    from dubeditor.translate_service import save_bible_to_db
    from models import GlossaryTerm

    if not new_terms:
        return 0

    existing_zh = {t.zh for t in bible.glossary.terms}
    added = 0
    for nt in new_terms:
        if not isinstance(nt, dict):
            continue
        zh = (nt.get("zh") or "").strip()
        vi = (nt.get("vi") or "").strip()
        if not zh or not vi:
            continue
        if zh in existing_zh:
            continue
        bible.glossary.terms.append(GlossaryTerm(
            zh=zh, vi=vi,
            n=nt.get("n", 1),
            note=nt.get("note"),
        ))
        existing_zh.add(zh)
        added += 1

    if added:
        save_bible_to_db(db, project_id, bible)
    return added


# ═════════════════════════════════════════════════════════════════
# STAGE: REVIEW PASS 1
# ═════════════════════════════════════════════════════════════════

def _apply_review_pass1(
    db: Session, project_id: int, raw_response: str,
    meta: dict, config: PipelineConfig,
) -> ApplyResult:
    """Apply decisions từ Pass 1 — chỉ apply FIX, log KEEP."""
    from dubeditor.models import Subtitle

    issues = meta.get("issues") or []
    issues_by_id = {iss["id"]: iss for iss in issues}

    if not issues:
        return ApplyResult(
            stage="review_pass1", unit_key="default", ok=True,
            summary="Pass 1 không có issue (skip).",
            counts={"fixed": 0, "kept": 0},
        )

    data = _parse_json_safely(raw_response, default_root={"decisions": []})
    if not isinstance(data, dict):
        return ApplyResult(
            stage="review_pass1", unit_key="default", ok=False,
            summary="Response không phải JSON object.",
            errors=["invalid_root"],
        )

    decisions = data.get("decisions") or []
    if not decisions:
        return ApplyResult(
            stage="review_pass1", unit_key="default", ok=False,
            summary="Không parse được decision nào.",
            errors=["no_decisions"],
        )

    warnings = []
    fixed = 0
    kept = 0
    fix_summary = []

    line_updates = {}  # line_index → {"text_v1": ..., "text_v2": ...}

    for dec in decisions:
        if not isinstance(dec, dict):
            continue
        iss_id = dec.get("id") or ""
        action = (dec.get("action") or "").upper()
        new_v1 = dec.get("new_v1")
        new_v2 = dec.get("new_v2")
        reason = dec.get("reason") or ""

        issue = issues_by_id.get(iss_id)
        if not issue:
            warnings.append(f"Decision có id '{iss_id}' không khớp issue nào")
            continue

        line_idx = issue["line_index"]

        if action == "FIX":
            if not isinstance(new_v1, str) or not new_v1.strip():
                warnings.append(f"FIX {iss_id} dòng {line_idx}: new_v1 rỗng, skip")
                continue
            upd = {"text_v1": new_v1.strip()}
            if isinstance(new_v2, str) and new_v2.strip():
                upd["text_v2"] = new_v2.strip()
            line_updates[line_idx] = upd
            fixed += 1
            fix_summary.append(f"L{line_idx} ({issue['type']}): {reason}")
        elif action == "KEEP":
            kept += 1
        else:
            warnings.append(f"Decision {iss_id}: action '{action}' không hợp lệ")

    # Apply updates vào DB
    if line_updates:
        try:
            subs = (db.query(Subtitle)
                      .filter(Subtitle.project_id == project_id,
                              Subtitle.index.in_(list(line_updates.keys())))
                      .all())
            for s in subs:
                upd = line_updates.get(s.index)
                if not upd:
                    continue
                if "text_v1" in upd:
                    # Update field tương thích (text_vi hoặc text_v1 tùy model)
                    if hasattr(s, "text_v1"):
                        s.text_v1 = upd["text_v1"]
                    if hasattr(s, "text_vi"):
                        s.text_vi = upd["text_v1"]
                if "text_v2" in upd and hasattr(s, "text_v2"):
                    s.text_v2 = upd["text_v2"]
            db.commit()
        except Exception as e:
            db.rollback()
            return ApplyResult(
                stage="review_pass1", unit_key="default", ok=False,
                summary=f"DB save failed: {e}",
                errors=[str(e)], warnings=warnings,
            )

    summary_text = f"Pass 1: FIX {fixed}/{len(decisions)}, KEEP {kept}"
    if fix_summary:
        summary_text += f"\nFixes:\n" + "\n".join(f"  - {s}" for s in fix_summary[:10])
        if len(fix_summary) > 10:
            summary_text += f"\n  ... +{len(fix_summary) - 10} more"

    return ApplyResult(
        stage="review_pass1", unit_key="default", ok=True,
        summary=summary_text,
        counts={"fixed": fixed, "kept": kept, "total": len(decisions)},
        warnings=warnings,
    )


# ═════════════════════════════════════════════════════════════════
# STAGE: REVIEW PASS 2
# ═════════════════════════════════════════════════════════════════

def _apply_review_pass2(
    db: Session, project_id: int, raw_response: str,
    meta: dict, config: PipelineConfig,
) -> ApplyResult:
    """Apply fixes từ Pass 2 — per-arc polish.

    v4.5: hỗ trợ SPEAKER_WRONG — AI có thể đề xuất sửa speaker assignment.
    """
    from dubeditor.models import Subtitle
    from dubeditor.translate_service import load_active_bible_from_db, save_speakers_to_db

    arc_index = meta.get("arc_index", -1)
    line_range = meta.get("line_range") or [0, 0]
    start, end = line_range[0], line_range[1]

    data = _parse_json_safely(raw_response, default_root={"fixes": []})
    if not isinstance(data, dict):
        return ApplyResult(
            stage="review_pass2", unit_key=f"arc_{arc_index}", ok=False,
            summary="Response không phải JSON object.",
            errors=["invalid_root"],
        )

    fixes = data.get("fixes") or []
    arc_notes = data.get("arc_notes") or ""

    warnings = []
    line_updates = {}            # {idx: {text_v1, text_v2}}
    speaker_updates = {}         # v4.5: {idx: new_speaker_zh}
    fix_count = 0
    cluster_count = 0
    speaker_fix_count = 0

    for fix in fixes:
        if not isinstance(fix, dict):
            continue
        try:
            line_idx = int(fix.get("i", -1))
            if line_idx < 1 or not (start <= line_idx <= end):
                warnings.append(f"Fix line {line_idx} ngoài range arc [{start}-{end}], skip")
                continue

            fix_type = (fix.get("type") or "").upper()
            new_v1 = fix.get("new_v1")
            new_v2 = fix.get("new_v2")
            new_speaker = fix.get("new_speaker_zh")   # v4.5

            upd = {}
            if isinstance(new_v1, str) and new_v1.strip():
                upd["text_v1"] = new_v1.strip()
            if isinstance(new_v2, str) and new_v2.strip():
                upd["text_v2"] = new_v2.strip()
            if upd:
                line_updates[line_idx] = upd
                fix_count += 1

            # v4.5: SPEAKER_WRONG — sửa speaker
            if fix_type == "SPEAKER_WRONG" or new_speaker:
                if isinstance(new_speaker, str) and new_speaker.strip():
                    speaker_updates[line_idx] = new_speaker.strip()
                    speaker_fix_count += 1
                else:
                    warnings.append(
                        f"Line {line_idx}: type=SPEAKER_WRONG nhưng thiếu new_speaker_zh"
                    )

            # cluster_fix (optional) — chỉ sửa text, không sửa speaker
            cluster_fix = fix.get("cluster_fix") or []
            for cf in cluster_fix:
                if not isinstance(cf, dict):
                    continue
                cf_idx = int(cf.get("i", -1))
                if cf_idx < 1 or not (start <= cf_idx <= end):
                    continue
                cf_v1 = cf.get("new_v1")
                cf_v2 = cf.get("new_v2")
                cf_upd = {}
                if isinstance(cf_v1, str) and cf_v1.strip():
                    cf_upd["text_v1"] = cf_v1.strip()
                if isinstance(cf_v2, str) and cf_v2.strip():
                    cf_upd["text_v2"] = cf_v2.strip()
                if cf_upd:
                    line_updates[cf_idx] = cf_upd
                    cluster_count += 1
        except Exception as e:
            warnings.append(f"Skip fix {fix}: {e}")

    if not line_updates and not speaker_updates:
        return ApplyResult(
            stage="review_pass2", unit_key=f"arc_{arc_index}", ok=True,
            summary=f"Pass 2 Arc {arc_index}: không có fix nào áp dụng. "
                    f"Notes: {arc_notes or '(không có)'}",
            counts={"fixed": 0, "cluster_fixes": 0, "speaker_fixes": 0},
        )

    # Apply text updates
    if line_updates:
        try:
            subs = (db.query(Subtitle)
                      .filter(Subtitle.project_id == project_id,
                              Subtitle.index.in_(list(line_updates.keys())))
                      .all())
            for s in subs:
                upd = line_updates.get(s.index)
                if not upd:
                    continue
                if "text_v1" in upd:
                    if hasattr(s, "text_v1"):
                        s.text_v1 = upd["text_v1"]
                    if hasattr(s, "text_vi"):
                        s.text_vi = upd["text_v1"]
                if "text_v2" in upd and hasattr(s, "text_v2"):
                    s.text_v2 = upd["text_v2"]
            db.commit()
        except Exception as e:
            db.rollback()
            return ApplyResult(
                stage="review_pass2", unit_key=f"arc_{arc_index}", ok=False,
                summary=f"DB save text failed: {e}",
                errors=[str(e)], warnings=warnings,
            )

    # v4.5: Apply speaker updates (via save_speakers_to_db để link character_id)
    if speaker_updates:
        try:
            bible = load_active_bible_from_db(db, project_id)
            if bible:
                speaker_results = {
                    idx: {"speaker_zh": spk, "confidence": "h"}
                    for idx, spk in speaker_updates.items()
                }
                save_speakers_to_db(db, project_id, speaker_results, bible)
            else:
                warnings.append(
                    "Không load được Bible — speaker update không link character_id"
                )
        except Exception as e:
            db.rollback()
            warnings.append(f"Speaker update partial failed: {e}")

    summary_text = f"Pass 2 Arc {arc_index}: fix {fix_count} dòng (text)"
    if cluster_count:
        summary_text += f" + {cluster_count} cluster fixes"
    if speaker_fix_count:
        summary_text += f" + {speaker_fix_count} speaker fixes"
    if arc_notes:
        summary_text += f"\nArc notes: {arc_notes}"

    return ApplyResult(
        stage="review_pass2", unit_key=f"arc_{arc_index}", ok=True,
        summary=summary_text,
        counts={
            "fixed": fix_count,
            "cluster_fixes": cluster_count,
            "speaker_fixes": speaker_fix_count,
        },
        warnings=warnings,
    )


# ═════════════════════════════════════════════════════════════════
# DISPATCHER
# ═════════════════════════════════════════════════════════════════

_MEGA_APPLIERS = {
    "bible_unified":   _apply_bible_unified,
    # "chunks_full":   BỎ ở v4.2 — không còn dùng chunks/scenes
    "translate_mega":  _apply_translate_mega,
    "review_pass1":    _apply_review_pass1,
    "review_pass2":    _apply_review_pass2,
}


def apply_response_mega(
    stage: str,
    db: Session,
    project_id: int,
    raw_response: str,
    meta: dict,
    config: PipelineConfig,
) -> ApplyResult:
    """Apply response cho stages mega (v4 manual mode)."""
    if stage not in _MEGA_APPLIERS:
        raise ValueError(
            f"Stage '{stage}' không hợp lệ. "
            f"Hợp lệ: {list(_MEGA_APPLIERS.keys())}"
        )
    return _MEGA_APPLIERS[stage](db, project_id, raw_response, meta, config)
