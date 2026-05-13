"""
dubeditor/translate_service.py
Cầu nối giữa SRT Translator v2 pipeline và DB của DubEditor.

Đây là layer chuyển đổi:
- v2 pipeline làm việc với Pydantic models (Bible, Cast, Scene, SubtitleLine)
- DubEditor lưu trong SQLAlchemy (Bible, Scene, Character, Subtitle)

Service này:
1. Load SRT từ DB (subtitles) → SrtEntry để pipeline xử lý
2. Run từng stage của pipeline, sau mỗi stage SAVE kết quả vào DB
3. Push SSE progress events cho FE theo dõi

Pipeline v2 chạy KHÔNG CẦN file SRT — chỉ cần list SrtEntry trong memory.
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Callable, Any

from sqlalchemy.orm import Session

from dubeditor.models import (
    Project, Subtitle, Character,
    Bible as DBBible, Scene as DBScene, StoryArc as DBStoryArc,
    PolishIssue as DBPolishIssue,
)

logger = logging.getLogger(__name__)

# ─── Path setup cho pipeline v2 ───────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).parent.parent
V2_DIR = PROJECT_ROOT / "srt_translator_v2"

if str(V2_DIR) not in sys.path:
    sys.path.insert(0, str(V2_DIR))

# Import pipeline v2
from config import PipelineConfig, default_config
from core.llm_client import CostTracker
from core.srt_parser import SrtEntry, calculate_cps
from models import (
    Bible as V2Bible, Cast as V2Cast, World as V2World, Glossary as V2Glossary,
    Character as V2Character, Pronouns as V2Pronouns, StoryArc as V2StoryArc,
    GlossaryTerm as V2GlossaryTerm,
    Scene as V2Scene, SceneMap as V2SceneMap,
)
from stages.stage1_bible import (
    run_stage1_bible, load_genre_pack, list_available_packs, auto_match_genre_pack,
)
from stages.stage2_scenes import run_stage2_scenes
from stages.stage3_speaker import run_stage3_speaker
from stages.stage4_translate import run_stage4_translate
from stages.stage5_polish import run_stage5_polish


# ─── Type alias cho progress callback ─────────────────────────────────────────

ProgressCallback = Callable[[str, float, str, Optional[dict]], Any]
# (stage, progress%, message, detail) → awaitable hoặc None


# ─── Load/Save: DB ↔ Pipeline ─────────────────────────────────────────────────

def db_subtitles_to_srt_entries(subs: list[Subtitle]) -> list[SrtEntry]:
    """Convert DB Subtitle records → SrtEntry cho pipeline v2.

    Dùng original_text (text_zh) làm input cho pipeline.
    """
    entries = []
    for s in sorted(subs, key=lambda x: x.index):
        text = s.original_text or s.text or ""
        if not text.strip():
            continue
        entries.append(SrtEntry(
            index=s.index,
            start_sec=s.start_time,
            end_sec=s.end_time,
            text=text,
        ))
    return entries


def save_bible_to_db(db: Session, project_id: int, v2_bible: V2Bible,
                     cost_tracker: CostTracker) -> DBBible:
    """Lưu Bible v2 (Pydantic) → DB.

    Logic:
    1. Deactivate Bible cũ
    2. Tạo Bible mới với version++ và is_active=True
    3. UPSERT Characters từ Bible.cast (giữ Character.id cũ nếu match name_zh)
    4. Tạo StoryArcs
    """
    # Deactivate Bible cũ
    db.query(DBBible).filter(
        DBBible.project_id == project_id,
        DBBible.is_active == True,  # noqa: E712
    ).update({"is_active": False})

    # Version mới
    last = db.query(DBBible).filter(
        DBBible.project_id == project_id
    ).order_by(DBBible.version.desc()).first()
    new_version = (last.version + 1) if last else 1

    # Cost ở stage Bible (1a + 1b + 1c)
    bible_cost = 0.0
    bible_tokens_in = 0
    bible_tokens_out = 0
    for stage_key in ("1a_cast", "1b_world", "1c_glossary"):
        if stage_key in cost_tracker.by_stage:
            s = cost_tracker.by_stage[stage_key]
            bible_cost += s["cost"]
            bible_tokens_in += s["tokens_in"]
            bible_tokens_out += s["tokens_out"]

    db_bible = DBBible(
        project_id=project_id,
        version=new_version,
        is_active=True,
        cast_json=v2_bible.cast.model_dump_json(exclude_none=True),
        world_json=v2_bible.world.model_dump_json(exclude_none=True),
        glossary_json=v2_bible.glossary.model_dump_json(exclude_none=True),
        genre_pack_id=v2_bible.genre_pack_id,
        tokens_in=bible_tokens_in,
        tokens_out=bible_tokens_out,
        cost_usd=round(bible_cost, 6),
    )
    db.add(db_bible)
    db.flush()

    # Upsert Characters
    existing_chars = db.query(Character).filter(Character.project_id == project_id).all()
    existing_by_zh = {c.name_zh: c for c in existing_chars if c.name_zh}
    existing_by_name = {c.name: c for c in existing_chars}

    color_palette = [
        '#185FA5', '#993C1D', '#0F6E56', '#854F0B', '#534AB7',
        '#D4537E', '#3B6D11', '#0C6E7A', '#7A2D6E', '#5F5E5A',
    ]
    color_idx = 0

    for v2_char in v2_bible.cast.characters:
        # Match: trước theo name_zh, sau theo name
        existing = existing_by_zh.get(v2_char.zh) or existing_by_name.get(v2_char.vi)

        char_data = {
            "name":             v2_char.vi or v2_char.zh or "?",
            "name_zh":          v2_char.zh,
            "aliases_zh":       json.dumps(v2_char.aliases_zh, ensure_ascii=False),
            "aliases_vi":       json.dumps(v2_char.aliases_vi, ensure_ascii=False),
            "role":             v2_char.role,
            "gender":           v2_char.gender,
            "age_group":        v2_char.age_group,
            "social_status":    v2_char.social_status,
            "personality":      v2_char.personality,
            "speaking_style":   v2_char.speaking_style,
            "self_address":     v2_char.self_address.model_dump_json(exclude_none=True),
            "addresses":        json.dumps(v2_char.addresses, ensure_ascii=False),
            "relationships_json": json.dumps(v2_char.relationships, ensure_ascii=False),
            "notes":            v2_char.notes,
        }

        if existing:
            for k, v in char_data.items():
                setattr(existing, k, v)
        else:
            new_char = Character(
                project_id=project_id,
                color=color_palette[color_idx % len(color_palette)],
                **char_data,
            )
            db.add(new_char)
            color_idx += 1

    # Story arcs
    db.query(DBStoryArc).filter(DBStoryArc.project_id == project_id).delete()
    for arc in v2_bible.world.story_arcs:
        db.add(DBStoryArc(
            project_id=project_id,
            arc_index=arc.index,
            title=arc.title,
            summary=arc.summary,
            start_line=arc.start_line,
            end_line=arc.end_line,
            emotional_tone=arc.emotional_tone,
            key_events=json.dumps(arc.key_events, ensure_ascii=False),
        ))

    db.commit()
    db.refresh(db_bible)
    return db_bible


def load_active_bible_from_db(db: Session, project_id: int) -> Optional[V2Bible]:
    """Load Bible v2 từ DB → Pydantic models để pipeline tiếp tục."""
    db_bible = db.query(DBBible).filter(
        DBBible.project_id == project_id,
        DBBible.is_active == True,  # noqa: E712
    ).first()

    if not db_bible:
        return None

    try:
        cast_data = json.loads(db_bible.cast_json or "{}")
        world_data = json.loads(db_bible.world_json or "{}")
        glossary_data = json.loads(db_bible.glossary_json or "{}")

        return V2Bible(
            project_id=project_id,
            cast=V2Cast(**cast_data) if cast_data else V2Cast(),
            world=V2World(**world_data) if world_data else V2World(),
            glossary=V2Glossary(**glossary_data) if glossary_data else V2Glossary(),
            genre_pack_id=db_bible.genre_pack_id,
        )
    except Exception as e:
        logger.error(f"[load_active_bible] Parse error: {e}")
        return None


def save_scenes_to_db(db: Session, project_id: int,
                      v2_scene_map: V2SceneMap) -> list[DBScene]:
    """Lưu SceneMap v2 → DB. Xóa scenes cũ trước."""
    db.query(DBScene).filter(DBScene.project_id == project_id).delete()

    # Build arc_index → arc_id map
    arcs = db.query(DBStoryArc).filter(DBStoryArc.project_id == project_id).all()
    arc_id_by_index = {a.arc_index: a.id for a in arcs}

    db_scenes = []
    for v2_scene in v2_scene_map.scenes:
        arc_id = arc_id_by_index.get(v2_scene.story_arc_index) if v2_scene.story_arc_index is not None else None
        db_scene = DBScene(
            project_id=project_id,
            scene_index=v2_scene.index,
            start_line=v2_scene.start_line,
            end_line=v2_scene.end_line,
            start_time_sec=v2_scene.start_time_sec,
            end_time_sec=v2_scene.end_time_sec,
            location=v2_scene.location,
            time_of_day=v2_scene.time_of_day,
            characters_present=json.dumps(v2_scene.characters_present, ensure_ascii=False),
            emotion_primary=v2_scene.emotion_primary,
            emotion_arc=v2_scene.emotion_arc,
            summary=v2_scene.summary,
            purpose=v2_scene.purpose,
            story_arc_id=arc_id,
            is_hook=v2_scene.is_hook,
            is_emotion_peak=v2_scene.is_emotion_peak,
            status="pending",
        )
        db.add(db_scene)
        db_scenes.append(db_scene)

    db.flush()
    db.commit()

    # Map subtitles → scene_id
    for db_scene in db_scenes:
        db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.index >= db_scene.start_line,
            Subtitle.index <= db_scene.end_line,
        ).update({"scene_id": db_scene.id})
    db.commit()

    return db_scenes


def load_scenes_from_db(db: Session, project_id: int) -> V2SceneMap:
    """Load Scenes từ DB → Pydantic SceneMap."""
    db_scenes = db.query(DBScene).filter(
        DBScene.project_id == project_id
    ).order_by(DBScene.scene_index).all()

    arcs = db.query(DBStoryArc).filter(DBStoryArc.project_id == project_id).all()
    arc_index_by_id = {a.id: a.arc_index for a in arcs}

    v2_scenes = []
    for s in db_scenes:
        try:
            chars = json.loads(s.characters_present or "[]")
        except json.JSONDecodeError:
            chars = []

        v2_scenes.append(V2Scene(
            index=s.scene_index,
            start_line=s.start_line,
            end_line=s.end_line,
            start_time_sec=s.start_time_sec,
            end_time_sec=s.end_time_sec,
            location=s.location or "",
            time_of_day=s.time_of_day,
            characters_present=chars,
            emotion_primary=s.emotion_primary or "neutral",
            emotion_arc=s.emotion_arc or "",
            summary=s.summary or "",
            purpose=s.purpose or "",
            story_arc_index=arc_index_by_id.get(s.story_arc_id),
            is_hook=bool(s.is_hook),
            is_emotion_peak=bool(s.is_emotion_peak),
        ))

    # Calculate totals
    subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).all()
    total_dur = 0.0
    if subs:
        total_dur = max(s.end_time for s in subs) - min(s.start_time for s in subs)

    return V2SceneMap(
        scenes=v2_scenes,
        total_lines=len(subs),
        total_duration_sec=total_dur,
    )


def save_speakers_to_db(db: Session, project_id: int,
                        speaker_map: dict[int, dict]) -> None:
    """Apply speaker assignments → Subtitle.character_id + speaker fields."""
    # Load characters mapping name → id
    chars = db.query(Character).filter(Character.project_id == project_id).all()
    char_by_name = {c.name: c.id for c in chars if c.name}
    char_by_zh = {c.name_zh: c.id for c in chars if c.name_zh}

    # Update subtitles
    subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).all()
    for sub in subs:
        info = speaker_map.get(sub.index)
        if not info:
            continue

        speaker_zh = info.get("speaker_zh", "?")
        speaker_vi = info.get("speaker_vi", "")
        confidence = info.get("confidence", "low")
        reason = info.get("reason", "")

        sub.speaker_zh = speaker_zh if speaker_zh != "?" else None
        sub.speaker_confidence = confidence
        sub.speaker_reason = reason

        # Map character_id
        cid = char_by_zh.get(speaker_zh) or char_by_name.get(speaker_vi)
        if cid:
            sub.character_id = cid

        # Mark review nếu confidence low
        if confidence == "low":
            sub.needs_review = True
            sub.review_reason = (sub.review_reason or "") + " | speaker_low"

    db.commit()


def save_translations_to_db(db: Session, project_id: int,
                            translation_map: dict[int, dict]) -> None:
    """Apply translations → Subtitle.text + emotion + intensity."""
    from models.scene import normalize_emotion   # lazy import — sys.path setup at top

    subs = db.query(Subtitle).filter(Subtitle.project_id == project_id).all()
    chars = db.query(Character).filter(Character.project_id == project_id).all()
    char_by_name = {c.name: c for c in chars}

    for sub in subs:
        info = translation_map.get(sub.index)
        if not info:
            continue

        text_vi = info.get("text_vi", "")
        if text_vi:
            sub.text = text_vi
            sub.text_draft = text_vi  # initial draft = bản dịch trước polish

        # Normalize emotion từ LLM → enum chuẩn trước khi lưu DB.
        # Tránh tình trạng Stage 5 đọc DB lên rồi Pydantic reject.
        raw_emotion = info.get("emotion")
        sub.emotion = normalize_emotion(raw_emotion) if raw_emotion else None

        # Intensity: clamp 1-10
        try:
            intensity = int(float(info.get("intensity", 5)))
        except (TypeError, ValueError):
            intensity = 5
        sub.intensity = max(1, min(10, intensity))

        # CPS
        duration = sub.end_time - sub.start_time
        if duration > 0 and text_vi:
            sub.cps_value = round(calculate_cps(text_vi, duration), 2)

        # Re-map character_id từ speaker_vi nếu chưa có
        speaker_vi = info.get("speaker_vi", "")
        if speaker_vi and not sub.character_id:
            ch = char_by_name.get(speaker_vi)
            if ch:
                sub.character_id = ch.id

    db.commit()


def save_polish_to_db(db: Session, project_id: int,
                      lines, polish_report) -> None:
    """Apply polish results: condensed text + issues."""
    # 1. Apply condensed text + needs_review flags
    db_subs_by_idx = {s.index: s for s in
                       db.query(Subtitle).filter(Subtitle.project_id == project_id).all()}

    for line in lines:
        sub = db_subs_by_idx.get(line.index)
        if not sub:
            continue
        if line.text_vi and line.text_vi != sub.text:
            sub.text = line.text_vi
        sub.cps_value = line.cps_value
        sub.needs_review = bool(line.needs_review)
        if line.review_reason:
            sub.review_reason = line.review_reason
        if line.condensed_from:
            sub.text_draft = line.condensed_from

    # 2. Replace polish issues
    db.query(DBPolishIssue).filter(DBPolishIssue.project_id == project_id).delete()
    for iss in polish_report.issues:
        sub = db_subs_by_idx.get(iss.line_index)
        db.add(DBPolishIssue(
            project_id=project_id,
            subtitle_id=sub.id if sub else None,
            line_index=iss.line_index,
            issue_type=iss.issue_type,
            description=iss.description,
            current_text=iss.current_text,
            suggested_text=iss.suggested_text,
            confidence=iss.confidence,
            evidence=iss.evidence,
        ))

    db.commit()


# ─── Pipeline runner — gom 5 stage ────────────────────────────────────────────

class TranslateRunner:
    """Chạy pipeline v2 trên 1 project, tích hợp DB.

    Có thể chạy:
    - Full pipeline (Stage 1→5)
    - 1 stage cụ thể (resume từ middle)

    Push progress qua callback. Lưu kết quả vào DB sau mỗi stage.
    """

    def __init__(self, db: Session, project_id: int,
                 config: PipelineConfig,
                 on_progress: Optional[ProgressCallback] = None,
                 on_llm_call: Optional[Callable] = None):
        self.db = db
        self.project_id = project_id
        self.config = config
        self.on_progress = on_progress
        self.on_llm_call = on_llm_call  # callback (payload: dict) khi mỗi llm call xong
        self.tracker = CostTracker()
        self._cancelled = False
        self._llm_call_counter = 0

    async def _emit(self, stage: str, progress: float, message: str,
                    detail: Optional[dict] = None):
        if self.on_progress:
            try:
                result = self.on_progress(stage, progress, message, detail)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.warning(f"[progress callback] {e}")

    def _on_llm_call_internal(self, payload: dict):
        """Wrapper: increment counter + forward to user callback."""
        self._llm_call_counter += 1
        payload["call_idx"] = self._llm_call_counter
        if self.on_llm_call:
            try:
                result = self.on_llm_call(payload)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                logger.warning(f"[llm observer] {e}")

    def _install_llm_observer(self):
        """Cài observer cho call_llm — gọi trước khi pipeline chạy."""
        from core.llm_client import set_llm_observer
        set_llm_observer(self._on_llm_call_internal)

    def _uninstall_llm_observer(self):
        """Gỡ observer — gọi sau khi pipeline xong."""
        from core.llm_client import set_llm_observer
        set_llm_observer(None)

    def cancel(self):
        self._cancelled = True

    def _check_cancelled(self):
        if self._cancelled:
            raise asyncio.CancelledError("Pipeline cancelled by user")

    def _load_subtitles_as_entries(self) -> list[SrtEntry]:
        subs = self.db.query(Subtitle).filter(
            Subtitle.project_id == self.project_id
        ).order_by(Subtitle.index).all()
        return db_subtitles_to_srt_entries(subs)

    def _save_status(self, status: str, progress: float = 0.0,
                     error: Optional[str] = None):
        p = self.db.query(Project).filter(Project.id == self.project_id).first()
        if not p:
            return
        p.translate_status = status
        p.translate_progress = progress
        p.translate_error = error
        self.db.commit()

    # ─── Individual stages ──────────────────────────────────────────────────

    async def run_bible(self) -> V2Bible:
        """Stage 1 (1A + 1B + 1C + 1D)."""
        await self._emit("bible", 0, "Stage 1: Phân tích phim...")
        self._check_cancelled()
        self._save_status("running", 0.0)

        entries = self._load_subtitles_as_entries()
        if not entries:
            raise ValueError("Project không có subtitles để phân tích")

        await self._emit("bible_1a", 5, f"1A: Trích xuất nhân vật từ {len(entries)} dòng...")
        v2_bible = await run_stage1_bible(entries, self.config, self.tracker)
        self._check_cancelled()

        await self._emit("bible_save", 18, "Lưu Bible vào database...")
        save_bible_to_db(self.db, self.project_id, v2_bible, self.tracker)

        await self._emit("bible_done", 20,
                          f"Bible xong: {len(v2_bible.cast.characters)} nhân vật, "
                          f"{len(v2_bible.world.story_arcs)} arcs, "
                          f"{len(v2_bible.glossary.terms)} thuật ngữ",
                          {"cast_count": len(v2_bible.cast.characters),
                           "arc_count": len(v2_bible.world.story_arcs),
                           "glossary_count": len(v2_bible.glossary.terms),
                           "genre_pack_id": v2_bible.genre_pack_id})
        return v2_bible

    async def run_scenes(self, v2_bible: V2Bible) -> V2SceneMap:
        """Stage 2."""
        await self._emit("scenes", 20, "Stage 2: Chia phim thành phân cảnh...")
        self._check_cancelled()

        entries = self._load_subtitles_as_entries()
        v2_scene_map = await run_stage2_scenes(entries, v2_bible, self.config, self.tracker)
        self._check_cancelled()

        await self._emit("scenes_save", 38, "Lưu phân cảnh vào database...")
        save_scenes_to_db(self.db, self.project_id, v2_scene_map)

        await self._emit("scenes_done", 40,
                          f"Scenes xong: {len(v2_scene_map.scenes)} phân cảnh",
                          {"scene_count": len(v2_scene_map.scenes)})
        return v2_scene_map

    async def run_speaker(self, v2_bible: V2Bible,
                          v2_scene_map: V2SceneMap) -> dict[int, dict]:
        """Stage 3."""
        await self._emit("speaker", 40, "Stage 3: Gán nhân vật cho thoại...")
        self._check_cancelled()

        entries = self._load_subtitles_as_entries()
        speaker_map = await run_stage3_speaker(
            entries, v2_bible, v2_scene_map, self.config, self.tracker
        )
        self._check_cancelled()

        await self._emit("speaker_save", 58, "Lưu speaker assignments...")
        save_speakers_to_db(self.db, self.project_id, speaker_map)

        high = sum(1 for r in speaker_map.values() if r.get("confidence") == "high")
        mid = sum(1 for r in speaker_map.values() if r.get("confidence") == "mid")
        low = sum(1 for r in speaker_map.values() if r.get("confidence") == "low")
        await self._emit("speaker_done", 60,
                          f"Speaker xong: high={high}, mid={mid}, low={low}",
                          {"high": high, "mid": mid, "low": low})
        return speaker_map

    async def run_translate(self, v2_bible: V2Bible,
                            v2_scene_map: V2SceneMap,
                            speaker_map: dict[int, dict]) -> dict[int, dict]:
        """Stage 4 — core."""
        await self._emit("translate", 60, "Stage 4: Dịch theo phân cảnh...")
        self._check_cancelled()

        entries = self._load_subtitles_as_entries()
        genre_pack = None
        if v2_bible.genre_pack_id:
            genre_pack = load_genre_pack(v2_bible.genre_pack_id, self.config)

        translation_map = await run_stage4_translate(
            entries, v2_bible, v2_scene_map, speaker_map,
            self.config, self.tracker, genre_pack=genre_pack,
        )
        self._check_cancelled()

        await self._emit("translate_save", 78, "Lưu bản dịch...")
        save_translations_to_db(self.db, self.project_id, translation_map)

        await self._emit("translate_done", 80,
                          f"Dịch xong: {len(translation_map)}/{len(entries)} dòng",
                          {"translated_count": len(translation_map),
                           "total_lines": len(entries)})
        return translation_map

    async def run_polish(self, v2_bible: V2Bible) -> None:
        """Stage 5."""
        await self._emit("polish", 80, "Stage 5: Polish + QC...")
        self._check_cancelled()

        # Build SubtitleLine list từ DB (đã có translation)
        from models import SubtitleLine
        db_subs = self.db.query(Subtitle).filter(
            Subtitle.project_id == self.project_id
        ).order_by(Subtitle.index).all()

        lines = []
        for s in db_subs:
            lines.append(SubtitleLine(
                index=s.index,
                start_time_sec=s.start_time,
                end_time_sec=s.end_time,
                text_zh=s.original_text or "",
                text_vi=s.text or "",
                speaker_zh=s.speaker_zh,
                speaker_vi=(s.character.name if s.character else None),
                speaker_confidence=s.speaker_confidence or "low",
                emotion=s.emotion,
                intensity=s.intensity or 5,
                scene_index=(s.scene.scene_index if s.scene else None),
                is_hook=bool(s.is_hook),
                needs_review=bool(s.needs_review),
            ))

        lines, polish_report = await run_stage5_polish(
            lines, v2_bible, self.config, self.tracker
        )
        self._check_cancelled()

        await self._emit("polish_save", 95, "Lưu polish results...")
        save_polish_to_db(self.db, self.project_id, lines, polish_report)

        await self._emit("polish_done", 98,
                          f"Polish xong: {len(polish_report.issues)} issues, "
                          f"rating: {polish_report.overall_rating}",
                          {"issue_count": len(polish_report.issues),
                           "rating": polish_report.overall_rating,
                           "summary": polish_report.summary})

    # ─── Full pipeline ──────────────────────────────────────────────────────

    async def run_full(self):
        """Chạy 5 stage tuần tự."""
        start_time = time.time()
        self._install_llm_observer()
        try:
            self._save_status("running", 0.0)
            await self._emit("start", 0, "Bắt đầu pipeline 5 stage...")

            v2_bible = await self.run_bible()
            v2_scene_map = await self.run_scenes(v2_bible)
            speaker_map = await self.run_speaker(v2_bible, v2_scene_map)
            await self.run_translate(v2_bible, v2_scene_map, speaker_map)
            await self.run_polish(v2_bible)

            self._save_status("done", 100.0)
            duration = int(time.time() - start_time)
            await self._emit("done", 100,
                              f"✅ Hoàn tất! Tổng thời gian: {duration}s, "
                              f"chi phí: ${self.tracker.total_cost_usd:.4f}",
                              {"cost_usd": self.tracker.total_cost_usd,
                               "duration_sec": duration,
                               "summary": self.tracker.summary()})

        except asyncio.CancelledError:
            self._save_status("idle", 0.0, error="Cancelled by user")
            await self._emit("cancelled", 0, "Đã hủy")
            raise
        except Exception as e:
            logger.error(f"[Pipeline pid={self.project_id}] {e}", exc_info=True)
            self._save_status("error", 0.0, error=str(e))
            await self._emit("error", 0, f"Lỗi: {str(e)[:200]}",
                              {"error": str(e)})
            raise
        finally:
            self._uninstall_llm_observer()


# ─── Genre pack info helper ───────────────────────────────────────────────────

def get_available_genre_packs() -> list[dict]:
    """List genre packs để FE chọn."""
    cfg = default_config()
    result = []
    for pack_id in list_available_packs(cfg):
        pack = load_genre_pack(pack_id, cfg)
        if pack:
            result.append({
                "id": pack.id,
                "name_vi": pack.name_vi,
                "name_zh": pack.name_zh,
                "description": pack.description,
            })
    return result


def build_pipeline_config(req) -> PipelineConfig:
    """Build PipelineConfig từ request schema TranslateConfig."""
    cfg = default_config()
    cfg.api_key = req.api_key
    cfg.provider = req.provider
    cfg.models.heavy = req.model_heavy
    cfg.models.medium = req.model_medium
    cfg.models.light = req.model_light
    cfg.project_type = req.project_type
    cfg.apply_project_type()
    if req.cps_max is not None:
        cfg.cps.max = req.cps_max
    cfg.concurrency.speaker = req.concurrency
    cfg.concurrency.translate = req.concurrency
    cfg.genre_pack = req.genre_pack
    return cfg