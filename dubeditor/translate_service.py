"""
Bridge giữa SRT Translator v3 pipeline và DubEditor DB.

Trách nhiệm:
- Convert DB.Subtitle → SrtEntry (cho pipeline)
- Save kết quả Bible/Chunks/Speaker/Translation/Polish vào DB
- Checkpoint per-chunk
- Track LLM cost vào DB
- Progress callback (cho WebSocket)
"""
from __future__ import annotations
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional, Callable

from sqlalchemy.orm import Session

# Add srt_translator_v2 to sys.path
_TRANSLATOR_DIR = Path(__file__).parent.parent / "srt_translator_v2"
if str(_TRANSLATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATOR_DIR))

# Pipeline imports
from config import PipelineConfig, default_config
from core.llm_client import CostTracker
from core.pipeline import run_full_pipeline, PipelineCallbacks
from core.srt_parser import SrtEntry, calculate_cps
from models import (
    Bible as V3Bible,
    ChunkMap as V3ChunkMap,
    Chunk as V3Chunk,
    Scene as V3Scene,
    PolishReport,
    Character as V3Character,
)
from stages.stage0_normalize import run_stage0_normalize, Stage0Report
from stages.stage1_bible import run_stage1_bible
from stages.stage2_scenes import run_stage2_chunks
from stages.stage3_speaker import run_stage3_speaker
from stages.stage4_translate import run_stage4_translate
from stages.stage5_polish import run_stage5_polish

# DubEditor imports
from dubeditor.models import (
    Project, Subtitle, Character, Bible as DBBible,
    StoryArc, Scene as DBScene, Chunk as DBChunk, PolishIssue,
)

logger = logging.getLogger(__name__)


ProgressCallback = Callable[[str, float, str, Optional[dict]], None]


# ─────────────────────────────────────────────────────────────────
# CONVERTERS
# ─────────────────────────────────────────────────────────────────

def db_subtitles_to_srt_entries(subs: list[Subtitle]) -> list[SrtEntry]:
    """Convert DB.Subtitle → SrtEntry cho pipeline."""
    entries = []
    for sub in subs:
        # Dùng original_text (TQ) nếu có, fallback text
        text = sub.original_text or sub.text or ""
        entries.append(SrtEntry(
            index=sub.index,
            start_sec=sub.start_time,
            end_sec=sub.end_time,
            text=text,
        ))
    return entries


# ─────────────────────────────────────────────────────────────────
# SAVE BIBLE
# ─────────────────────────────────────────────────────────────────

def save_bible_to_db(db: Session, project_id: int, v3_bible: V3Bible,
                     tracker: Optional[CostTracker] = None) -> int:
    """Lưu Bible (3 phần) + sync Characters + StoryArcs vào DB."""
    # Deactivate old bibles
    db.query(DBBible).filter(
        DBBible.project_id == project_id,
        DBBible.is_active == True,
    ).update({"is_active": False})

    # Get next version
    last = db.query(DBBible).filter(
        DBBible.project_id == project_id
    ).order_by(DBBible.version.desc()).first()
    next_version = (last.version + 1) if last else 1

    # Cost stats
    bible_stats = tracker.by_stage if tracker else {}
    tokens_in = 0
    tokens_out = 0
    cost = 0.0
    for k in ("1a_cast", "1b_world", "1c_glossary"):
        if k in bible_stats:
            tokens_in += bible_stats[k]["tokens_in"]
            tokens_out += bible_stats[k]["tokens_out"]
            cost += bible_stats[k]["cost"]

    new_bible = DBBible(
        project_id=project_id,
        version=next_version,
        is_active=True,
        cast_json=v3_bible.cast.model_dump_json(),
        world_json=v3_bible.world.model_dump_json(),
        glossary_json=v3_bible.glossary.model_dump_json(),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        model_used=v3_bible.model_used,
    )
    db.add(new_bible)
    db.flush()

    # Sync Characters
    _sync_characters(db, project_id, v3_bible)

    # Sync StoryArcs
    _sync_story_arcs(db, project_id, v3_bible)

    db.commit()
    db.refresh(new_bible)
    logger.info(f"[save_bible] saved bible v{next_version} id={new_bible.id}")
    return new_bible.id


def _sync_characters(db: Session, project_id: int, v3_bible: V3Bible):
    """Sync Bible.cast → DB Characters."""
    existing = db.query(Character).filter(Character.project_id == project_id).all()
    by_name_zh = {c.name_zh: c for c in existing if c.name_zh}
    by_name_vi = {c.name: c for c in existing if c.name}

    for ch in v3_bible.cast.characters:
        existing_char = by_name_zh.get(ch.zh) or by_name_vi.get(ch.vi)
        if existing_char:
            # Update
            existing_char.name = ch.vi or existing_char.name
            existing_char.name_zh = ch.zh
            existing_char.role = ch.role
            existing_char.gender = ch.g
            existing_char.age_group = ch.age
            existing_char.personality = ch.char
            existing_char.aliases_vi = json.dumps(ch.alias, ensure_ascii=False)
            existing_char.relationships_json = json.dumps(ch.rel, ensure_ascii=False)
        else:
            new_char = Character(
                project_id=project_id,
                name=ch.vi or ch.zh,
                name_zh=ch.zh,
                role=ch.role,
                gender=ch.g,
                age_group=ch.age,
                personality=ch.char,
                aliases_vi=json.dumps(ch.alias, ensure_ascii=False),
                relationships_json=json.dumps(ch.rel, ensure_ascii=False),
            )
            db.add(new_char)


def _sync_story_arcs(db: Session, project_id: int, v3_bible: V3Bible):
    """Sync Bible.world.arcs → DB StoryArc."""
    # Xóa arcs cũ
    db.query(StoryArc).filter(StoryArc.project_id == project_id).delete()

    for arc in v3_bible.world.arcs:
        db_arc = StoryArc(
            project_id=project_id,
            arc_index=arc.index,
            title=arc.t,
            summary=arc.summary or "",
            start_line=arc.r[0],
            end_line=arc.r[1],
            emotional_tone=arc.tone,
        )
        db.add(db_arc)


def load_active_bible_from_db(db: Session, project_id: int) -> Optional[V3Bible]:
    """Load active Bible từ DB → V3Bible Pydantic."""
    row = db.query(DBBible).filter(
        DBBible.project_id == project_id,
        DBBible.is_active == True,
    ).first()
    if not row:
        return None

    try:
        cast_data = json.loads(row.cast_json or "{}")
        world_data = json.loads(row.world_json or "{}")
        glossary_data = json.loads(row.glossary_json or "{}")
        return V3Bible(
            project_id=project_id,
            cast=cast_data,
            world=world_data,
            glossary=glossary_data,
            version=row.version,
            model_used=row.model_used,
        )
    except Exception as e:
        logger.error(f"[load_active_bible] failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────
# SAVE CHUNKS + SCENES
# ─────────────────────────────────────────────────────────────────

def save_chunks_to_db(db: Session, project_id: int,
                      v3_chunk_map: V3ChunkMap) -> dict[tuple[int, int], int]:
    """Save chunks + scenes vào DB. Return map (start, end) → chunk_id."""
    # Xóa chunks + scenes cũ
    db.query(DBScene).filter(DBScene.project_id == project_id).delete()
    db.query(DBChunk).filter(DBChunk.project_id == project_id).delete()

    chunk_id_map = {}
    scene_index_counter = 0

    # Get story_arc_id map
    arc_id_by_index = {}
    for arc in db.query(StoryArc).filter(StoryArc.project_id == project_id).all():
        arc_id_by_index[arc.arc_index] = arc.id

    for c_idx, chunk in enumerate(v3_chunk_map.chunks):
        db_chunk = DBChunk(
            project_id=project_id,
            arc_index=chunk.arc_index,
            chunk_index=c_idx,
            title=chunk.t,
            start_line=chunk.r[0],
            end_line=chunk.r[1],
            status="pending",
        )
        db.add(db_chunk)
        db.flush()
        chunk_id_map[chunk.r] = db_chunk.id

        # Save scenes của chunk
        for sc in chunk.scenes:
            db_scene = DBScene(
                project_id=project_id,
                scene_index=scene_index_counter,
                start_line=sc.r[0],
                end_line=sc.r[1],
                location="",  # Bỏ field loc khỏi Scene model (Stage 2 không trả về nữa) — giữ DB column rỗng
                characters_present=json.dumps(sc.ch, ensure_ascii=False),
                emotion_primary=sc.e,
                story_arc_id=arc_id_by_index.get(chunk.arc_index),
                chunk_id=db_chunk.id,
                is_hook=sc.is_hook,
                is_emotion_peak=sc.is_emotion_peak,
            )
            db.add(db_scene)
            scene_index_counter += 1

        # Nếu chunk không có scenes → tạo 1 scene = chunk
        if not chunk.scenes:
            db_scene = DBScene(
                project_id=project_id,
                scene_index=scene_index_counter,
                start_line=chunk.r[0],
                end_line=chunk.r[1],
                location="",
                characters_present="[]",
                emotion_primary="neutral",
                story_arc_id=arc_id_by_index.get(chunk.arc_index),
                chunk_id=db_chunk.id,
            )
            db.add(db_scene)
            scene_index_counter += 1

    # Update Subtitle.scene_id + chunk_id
    db.flush()
    _update_subtitle_chunk_scene(db, project_id)

    db.commit()
    logger.info(f"[save_chunks] saved {len(v3_chunk_map.chunks)} chunks, "
                f"{scene_index_counter} scenes")
    return chunk_id_map


def _update_subtitle_chunk_scene(db: Session, project_id: int):
    """Cập nhật Subtitle.scene_id và chunk_id theo range."""
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).order_by(Subtitle.index).all()

    chunks = db.query(DBChunk).filter(
        DBChunk.project_id == project_id
    ).all()
    scenes = db.query(DBScene).filter(
        DBScene.project_id == project_id
    ).order_by(DBScene.start_line).all()

    for sub in subs:
        # Find chunk
        for ch in chunks:
            if ch.start_line <= sub.index <= ch.end_line:
                sub.chunk_id = ch.id
                break

        # Find scene
        for sc in scenes:
            if sc.start_line <= sub.index <= sc.end_line:
                sub.scene_id = sc.id
                break


def load_chunks_from_db(db: Session, project_id: int) -> V3ChunkMap:
    """Load chunks + scenes từ DB → V3ChunkMap. Cho resume stage.

    Trả về ChunkMap rỗng nếu chưa có (caller cần check).
    """
    db_chunks = db.query(DBChunk).filter(
        DBChunk.project_id == project_id
    ).order_by(DBChunk.chunk_index).all()

    if not db_chunks:
        return V3ChunkMap(chunks=[])

    # Pre-load scenes group by chunk_id
    db_scenes = db.query(DBScene).filter(
        DBScene.project_id == project_id
    ).order_by(DBScene.start_line).all()
    scenes_by_chunk: dict[int, list] = {}
    for sc in db_scenes:
        scenes_by_chunk.setdefault(sc.chunk_id, []).append(sc)

    chunks = []
    for db_ch in db_chunks:
        # Build scenes for this chunk
        v3_scenes = []
        for sc in scenes_by_chunk.get(db_ch.id, []):
            try:
                chars = json.loads(sc.characters_present or "[]")
            except json.JSONDecodeError:
                chars = []
            tag = None
            if sc.is_hook:
                tag = "HOOK"
            elif sc.is_emotion_peak:
                tag = "PEAK"
            v3_scenes.append(V3Scene(
                r=(sc.start_line, sc.end_line),
                ch=chars,
                e=sc.emotion_primary or "neutral",
                i=5,  # DB cũ không có intensity → fallback 5; lần chạy mới sẽ có
                tag=tag,
            ))

        chunks.append(V3Chunk(
            r=(db_ch.start_line, db_ch.end_line),
            t=db_ch.title or "",
            arc_index=db_ch.arc_index,
            scenes=v3_scenes,
        ))

    return V3ChunkMap(chunks=chunks)


def load_speaker_map_from_db(db: Session, project_id: int) -> dict[int, dict]:
    """Build speaker_map từ Subtitle.speaker_zh + speaker_confidence."""
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).all()

    speaker_map = {}
    for s in subs:
        if not s.speaker_zh:
            continue
        speaker_map[s.index] = {
            "speaker_zh": s.speaker_zh,
            "confidence": s.speaker_confidence or "l",
            "scene_index": None,
            "chunk_range": None,
            "arc_index": None,
        }
    return speaker_map


# ─────────────────────────────────────────────────────────────────
# SAVE SPEAKER + TRANSLATION (per-chunk checkpoint)
# ─────────────────────────────────────────────────────────────────

def save_speakers_to_db(db: Session, project_id: int,
                        speaker_results: dict[int, dict],
                        v3_bible: V3Bible) -> None:
    """Save speaker results vào Subtitle."""
    # Build name_zh → character_id map
    char_id_by_zh = {}
    for c in db.query(Character).filter(Character.project_id == project_id).all():
        if c.name_zh:
            char_id_by_zh[c.name_zh] = c.id

    # Build alias map từ Bible
    for ch in v3_bible.cast.characters:
        if ch.zh in char_id_by_zh:
            for alias in ch.alias:
                char_id_by_zh.setdefault(alias, char_id_by_zh[ch.zh])

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).all()
    sub_by_idx = {s.index: s for s in subs}

    for line_idx, info in speaker_results.items():
        sub = sub_by_idx.get(line_idx)
        if not sub:
            continue
        speaker_zh = info.get("speaker_zh")
        sub.speaker_zh = speaker_zh
        sub.speaker_confidence = info.get("confidence", "l")
        # Resolve character_id
        if speaker_zh and speaker_zh in char_id_by_zh:
            sub.character_id = char_id_by_zh[speaker_zh]

    db.commit()


def save_translations_to_db(db: Session, project_id: int,
                            translation_results: dict[int, dict],
                            v3_bible: V3Bible) -> None:
    """Save translation results (2 variants) vào Subtitle.
    
    text_v1 → ưu tiên, set vào Subtitle.text (active)
    text_v2 → save nullable
    """
    # Build name_zh → character map
    char_id_by_zh = {}
    char_vi_by_zh = {}
    for c in db.query(Character).filter(Character.project_id == project_id).all():
        if c.name_zh:
            char_id_by_zh[c.name_zh] = c.id
        if c.name_zh and c.name:
            char_vi_by_zh[c.name_zh] = c.name

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == project_id
    ).all()
    sub_by_idx = {s.index: s for s in subs}

    for line_idx, info in translation_results.items():
        sub = sub_by_idx.get(line_idx)
        if not sub:
            continue

        text_v1 = info.get("text_v1") or ""
        text_v2 = info.get("text_v2")
        is_noise = bool(info.get("is_noise", False))
        sub.text_v1 = text_v1
        sub.text_v2 = text_v2
        sub.variant_selected = 1
        sub.text = text_v1  # active
        sub.is_noise = is_noise

        # Compute CPS
        duration = max(0.01, sub.end_time - sub.start_time)
        sub.cps_value = calculate_cps(text_v1, duration) if text_v1 else None

        sub.emotion = info.get("emotion")
        sub.intensity = info.get("intensity", 5)

        # Update needs_review
        import re
        if is_noise:
            # Noise lines: không cần review, sẵn sàng skip khi export
            sub.needs_review = False
            sub.review_reason = "noise"
        elif not text_v1 or re.search(r'[\u4e00-\u9fff]', text_v1):
            sub.needs_review = True
            sub.review_reason = "Chưa dịch hoặc còn TQ"
        else:
            sub.needs_review = False
            sub.review_reason = ""

    db.commit()


def save_polish_to_db(db: Session, project_id: int,
                     report: PolishReport) -> None:
    """Save polish issues + clean up old issues."""
    db.query(PolishIssue).filter(
        PolishIssue.project_id == project_id,
        PolishIssue.resolved == False,
    ).delete()

    for issue in report.issues:
        # Find subtitle
        sub = db.query(Subtitle).filter(
            Subtitle.project_id == project_id,
            Subtitle.index == issue.line_index,
        ).first()
        db_issue = PolishIssue(
            project_id=project_id,
            subtitle_id=sub.id if sub else None,
            line_index=issue.line_index,
            issue_type=issue.issue_type,
            description=issue.reason,
            current_text=issue.current_text,
            suggested_text=issue.suggested_text,
            confidence="mid",
            evidence="",
            resolved=False,
        )
        db.add(db_issue)

    db.commit()


# ─────────────────────────────────────────────────────────────────
# CONFIG BUILDER
# ─────────────────────────────────────────────────────────────────

def build_pipeline_config(req) -> PipelineConfig:
    """Build PipelineConfig từ TranslateConfig request."""
    config = default_config()
    config.api_key = req.api_key
    config.provider = req.provider
    config.models.heavy = req.model_heavy
    config.models.medium = req.model_medium
    config.models.light = req.model_light

    # v3.3: thinking toggles per stage (chỉ apply cho Gemini 2.5+ / model có thinking)
    if hasattr(req, "heavy_thinking") and req.heavy_thinking is not None:
        config.models.heavy_thinking = bool(req.heavy_thinking)
    if hasattr(req, "medium_thinking") and req.medium_thinking is not None:
        config.models.medium_thinking = bool(req.medium_thinking)
    if hasattr(req, "light_thinking") and req.light_thinking is not None:
        config.models.light_thinking = bool(req.light_thinking)
    if hasattr(req, "translate_thinking") and req.translate_thinking is not None:
        config.models.translate_thinking = bool(req.translate_thinking)

    config.project_type = req.project_type
    config.apply_project_type()

    if req.cps_max is not None:
        config.cps.max = req.cps_max

    config.concurrency.translate = req.concurrency
    config.concurrency.speaker_arcs = req.concurrency
    config.concurrency.polish = req.concurrency

    # v3 fields
    if hasattr(req, "variant_mode") and req.variant_mode:
        config.variant.mode = req.variant_mode
    if hasattr(req, "chunk_overlap") and req.chunk_overlap is not None:
        config.chunk.overlap_lines = req.chunk_overlap
    if hasattr(req, "chunks_parallel"):
        config.chunk.parallel = bool(req.chunks_parallel)
    # speaker_parallel cũ → đã bỏ (Stage 3 v3.1 luôn chạy theo arc: arcs song song, chunks tuần tự)
    # speaker_arcs có thể nhận từ req.concurrency hoặc req nếu có field riêng:
    if hasattr(req, "speaker_arcs") and getattr(req, "speaker_arcs", None) is not None:
        config.concurrency.speaker_arcs = int(req.speaker_arcs)
    if hasattr(req, "speaker_context_window") and req.speaker_context_window is not None:
        config.speaker.context_window = int(req.speaker_context_window)
    if hasattr(req, "speaker_carry_over_lines") and getattr(req, "speaker_carry_over_lines", None) is not None:
        config.speaker.carry_over_lines = int(req.speaker_carry_over_lines)
    # v3.2: Stage 0 normalize
    if hasattr(req, "stage0_enabled"):
        config.stage0.enabled = bool(req.stage0_enabled)
    if hasattr(req, "stage0_model") and req.stage0_model:
        config.stage0.model = req.stage0_model
    if hasattr(req, "stage0_context_window") and req.stage0_context_window is not None:
        config.stage0.context_window = int(req.stage0_context_window)
    if hasattr(req, "cache_enabled"):
        config.cache.enabled = req.cache_enabled

    return config


# ─────────────────────────────────────────────────────────────────
# TRANSLATE RUNNER
# ─────────────────────────────────────────────────────────────────

class TranslateRunner:
    """Chạy pipeline v3 trên 1 project + tích hợp DB checkpoint."""

    def __init__(self, db: Session, project_id: int,
                 config: PipelineConfig,
                 on_progress: Optional[ProgressCallback] = None,
                 on_llm_call: Optional[Callable] = None):
        self.db = db
        self.project_id = project_id
        self.config = config
        self.on_progress = on_progress
        self.on_llm_call = on_llm_call
        self.tracker = CostTracker()
        self._cancelled = False
        self._llm_call_counter = 0
        # Tham chiếu pipeline objects
        self._bible: Optional[V3Bible] = None
        self._chunk_map: Optional[V3ChunkMap] = None
        self._speaker_map: dict = {}
        self._translation_map: dict = {}

    # ─── Helpers ────────────────────────────────────────────

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
        try:
            from core.llm_client import set_llm_observer
            set_llm_observer(self._on_llm_call_internal)
        except (ImportError, AttributeError):
            pass

    def _uninstall_llm_observer(self):
        try:
            from core.llm_client import set_llm_observer
            set_llm_observer(None)
        except (ImportError, AttributeError):
            pass

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

    # ─── Individual stages ──────────────────────────────────

    async def run_normalize(self) -> Stage0Report:
        """Stage 0 — Chuẩn hóa phụ đề (chạy trước Stage 1).

        Scan dòng khả nghi → gửi AI Flash → apply remove/clean → cập nhật DB.
        """
        await self._emit("normalize", 0, "Stage 0: Chuẩn hóa phụ đề...")
        self._check_cancelled()
        self._save_status("running", 0.0)

        # Skip nếu disabled
        if not self.config.stage0.enabled:
            logger.info("[Stage 0] Disabled by config — skip")
            await self._emit("normalize_done", 4, "Stage 0 disabled — skipped")
            return Stage0Report(total_lines=0)

        entries = self._load_subtitles_as_entries()
        if not entries:
            raise ValueError("Project không có subtitles")

        await self._emit("normalize_scan", 1, f"Scan {len(entries)} dòng...")

        # Callback checkpoint per cluster — update DB ngay
        async def on_cluster_done(update_map: dict):
            if not update_map:
                return
            try:
                self._save_normalize_updates(update_map)
            except Exception as e:
                logger.warning(f"[Stage 0] checkpoint save failed: {e}")

        entries, report = await run_stage0_normalize(
            entries, self.config, self.tracker,
            on_cluster_done=on_cluster_done,
        )
        self._check_cancelled()

        # Final save (full apply, idempotent)
        await self._emit("normalize_save", 4, "Lưu kết quả chuẩn hóa...")
        full_updates = {}
        for d in report.decisions:
            if d.action == "remove":
                full_updates[d.line_index] = {
                    "action": "remove",
                    "is_noise": True,
                    "new_text": "",
                    "reason": d.reason,
                }
            elif d.action == "clean":
                full_updates[d.line_index] = {
                    "action": "clean",
                    "is_noise": False,
                    "new_text": d.new_text or "",
                    "reason": d.reason,
                }
        self._save_normalize_updates(full_updates)

        await self._emit("normalize_done", 5, report.summary)
        return report

    def _save_normalize_updates(self, update_map: dict):
        """Save kết quả Stage 0 vào DB.

        update_map: {line_idx → {action, new_text, reason}}

        Logic:
        - "clean": ghi text mới vào original_text, giữ dòng
        - "remove": XÓA HẲN dòng khỏi DB (không giữ rỗng)
                    Sau khi xóa, reindex các dòng sau để liên tục.
        """
        if not update_map:
            return

        # Phân loại
        clean_updates = {idx: u for idx, u in update_map.items() if u.get("action") == "clean"}
        remove_indices = sorted(
            [idx for idx, u in update_map.items() if u.get("action") == "remove"]
        )

        # 1. Apply clean
        if clean_updates:
            subs = self.db.query(Subtitle).filter(
                Subtitle.project_id == self.project_id,
                Subtitle.index.in_(list(clean_updates.keys())),
            ).all()
            for sub in subs:
                u = clean_updates.get(sub.index)
                if not u:
                    continue
                # Lưu original_raw lần đầu apply
                if not sub.is_cleaned and not sub.original_raw:
                    sub.original_raw = sub.original_text
                sub.is_cleaned = True
                sub.clean_reason = u.get("reason") or ""
                sub.original_text = u.get("new_text") or ""
                # Clear cột `text` (bản dịch Việt) vì nó có thể chứa TQ legacy
                # và sẽ được Stage 4 ghi lại với bản dịch Việt thật sự.
                sub.text = ""
                sub.text_v1 = None
                sub.text_v2 = None
            self.db.commit()

        # 2. Apply remove: XÓA HẲN + REINDEX
        if remove_indices:
            # Trước khi xóa: nếu đã có chunks/scenes → reset (vì line index sẽ shift)
            from dubeditor.models import Scene as DBScene, Chunk as DBChunk, RemovedSubtitle
            self.db.query(DBScene).filter(DBScene.project_id == self.project_id).delete()
            self.db.query(DBChunk).filter(DBChunk.project_id == self.project_id).delete()

            # Lưu log RemovedSubtitle TRƯỚC khi xóa
            to_remove = self.db.query(Subtitle).filter(
                Subtitle.project_id == self.project_id,
                Subtitle.index.in_(remove_indices),
            ).all()
            for sub in to_remove:
                reason = (update_map.get(sub.index) or {}).get("reason") or ""
                self.db.add(RemovedSubtitle(
                    project_id=self.project_id,
                    original_index=sub.original_raw and sub.index or sub.index,
                    removed_after_index=sub.index,
                    start_time=sub.start_time,
                    end_time=sub.end_time,
                    original_text=sub.original_raw or sub.original_text or "",
                    clean_reason=reason,
                ))

            # Xóa các dòng cần xóa
            self.db.query(Subtitle).filter(
                Subtitle.project_id == self.project_id,
                Subtitle.index.in_(remove_indices),
            ).delete(synchronize_session=False)

            # Reindex các dòng còn lại liên tục 1, 2, 3...
            remaining = self.db.query(Subtitle).filter(
                Subtitle.project_id == self.project_id,
            ).order_by(Subtitle.index).all()
            for new_idx, sub in enumerate(remaining, start=1):
                if sub.index != new_idx:
                    sub.index = new_idx
            self.db.commit()

            # Cập nhật subtitle_count của project
            from dubeditor.models import Project
            project = self.db.query(Project).filter(Project.id == self.project_id).first()
            if project:
                project.subtitle_count = len(remaining)
                self.db.commit()

            logger.info(f"[Stage 0] Đã xóa {len(remove_indices)} dòng + reindex còn "
                        f"{len(remaining)} dòng")

    async def run_bible(self) -> V3Bible:
        await self._emit("bible", 0, "Stage 1: Phân tích phim...")
        self._check_cancelled()
        self._save_status("running", 0.0)

        entries = self._load_subtitles_as_entries()
        if not entries:
            raise ValueError("Project không có subtitles")

        await self._emit("bible_1a", 5, f"1A: Trích xuất nhân vật ({len(entries)} dòng)...")
        bible = await run_stage1_bible(entries, self.config, self.tracker)
        self._check_cancelled()

        await self._emit("bible_save", 18, "Lưu Bible...")
        save_bible_to_db(self.db, self.project_id, bible, self.tracker)
        self._bible = bible

        await self._emit("bible_done", 20,
                         f"Bible OK: {len(bible.cast.characters)} nhân vật, "
                         f"{len(bible.world.arcs)} arcs, "
                         f"{len(bible.glossary.terms)} terms")
        return bible

    async def run_chunks(self, bible: Optional[V3Bible] = None) -> V3ChunkMap:
        if not bible:
            bible = self._bible or load_active_bible_from_db(self.db, self.project_id)
        if not bible:
            raise ValueError("Cần Bible trước khi chia chunks")

        entries = self._load_subtitles_as_entries()
        await self._emit("chunks", 25, f"Stage 2: Chia chunks + scenes ({len(bible.world.arcs)} arcs)...")
        self._check_cancelled()

        chunk_map = await run_stage2_chunks(entries, bible, self.config, self.tracker)
        self._check_cancelled()

        await self._emit("chunks_save", 38, "Lưu chunks vào DB...")
        save_chunks_to_db(self.db, self.project_id, chunk_map)
        self._chunk_map = chunk_map

        await self._emit("chunks_done", 40,
                         f"Chunks OK: {len(chunk_map.chunks)} chunks")
        return chunk_map

    async def run_speaker(self, bible: Optional[V3Bible] = None,
                          chunk_map: Optional[V3ChunkMap] = None) -> dict:
        if not bible:
            bible = self._bible or load_active_bible_from_db(self.db, self.project_id)
        if not chunk_map:
            chunk_map = self._chunk_map or load_chunks_from_db(self.db, self.project_id)
        if not bible:
            raise ValueError("Chưa có Bible. Chạy Stage 1 trước.")
        if not chunk_map or not chunk_map.chunks:
            raise ValueError("Chưa có Chunks. Chạy Stage 2 trước.")
        self._chunk_map = chunk_map  # cache lại

        entries = self._load_subtitles_as_entries()
        await self._emit("speaker", 45,
                         f"Stage 3: Gán speaker ({len(chunk_map.chunks)} chunks)...")
        self._check_cancelled()

        async def on_chunk_done(chunk_result: dict):
            save_speakers_to_db(self.db, self.project_id, chunk_result, bible)

        speaker_map = await run_stage3_speaker(
            entries, bible, chunk_map, self.config, self.tracker,
            on_chunk_done=on_chunk_done,
        )
        self._speaker_map = speaker_map

        await self._emit("speaker_done", 55,
                         f"Speaker OK: {len(speaker_map)} dòng đã gán")
        return speaker_map

    async def run_translate(self,
                            bible: Optional[V3Bible] = None,
                            chunk_map: Optional[V3ChunkMap] = None,
                            speaker_map: Optional[dict] = None) -> dict:
        if not bible:
            bible = self._bible or load_active_bible_from_db(self.db, self.project_id)
        if not chunk_map:
            chunk_map = self._chunk_map or load_chunks_from_db(self.db, self.project_id)
        if not speaker_map:
            speaker_map = self._speaker_map or load_speaker_map_from_db(self.db, self.project_id)
        if not bible:
            raise ValueError("Chưa có Bible. Chạy Stage 1 trước.")
        if not chunk_map or not chunk_map.chunks:
            raise ValueError("Chưa có Chunks. Chạy Stage 2 trước.")
        self._chunk_map = chunk_map  # cache lại

        entries = self._load_subtitles_as_entries()
        await self._emit("translate", 60,
                         f"Stage 4: Dịch ({len(chunk_map.chunks)} chunks, "
                         f"variant={self.config.variant.mode})...")
        self._check_cancelled()

        async def on_chunk_done(chunk_result: dict):
            save_translations_to_db(self.db, self.project_id, chunk_result, bible)

        translation_map = await run_stage4_translate(
            entries, bible, chunk_map, speaker_map, self.config, self.tracker,
            on_chunk_done=on_chunk_done,
        )
        self._translation_map = translation_map

        translated = len(translation_map)
        variants = sum(1 for v in translation_map.values() if v.get("text_v2"))
        await self._emit("translate_done", 85,
                         f"Translate OK: {translated} dòng, {variants} variants")
        return translation_map

    async def run_polish(self) -> PolishReport:
        """Stage 5 — TẠM DISABLE.

        Trước đây: retry dòng còn TQ / rỗng.
        Hiện tại: skip hoàn toàn — Stage 4 đã đủ tốt với prompt mới.
        Nếu cần retry, dùng tính năng retranslate per-line từ UI.
        """
        await self._emit("polish", 95, "Stage 5: Disabled — skip")
        logger.info("[Stage 5] DISABLED — skip polish/retry")

        # Trả report rỗng để upstream không vỡ
        report = PolishReport(
            issues=[],
            retried_count=0,
            fixed_count=0,
            still_problematic=0,
            summary="Stage 5 disabled — không retry",
        )
        await self._emit("polish_done", 95, report.summary)
        return report

    async def run_polish_DEPRECATED(self) -> PolishReport:
        """[CŨ] Stage 5 retry — giữ lại làm reference, không gọi từ đâu cả."""
        await self._emit("polish", 90, "Stage 5: Retry dòng còn TQ / rỗng...")
        self._check_cancelled()

        bible = self._bible or load_active_bible_from_db(self.db, self.project_id)
        if not bible:
            raise ValueError("Thiếu Bible cho polish")

        # Build SubtitleLine list từ DB
        from models import SubtitleLine
        subs = self.db.query(Subtitle).filter(
            Subtitle.project_id == self.project_id
        ).order_by(Subtitle.index).all()

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

        lines, report = await run_stage5_polish(lines, bible, self.config, self.tracker)

        # Save retry results back to DB
        sub_by_idx = {s.index: s for s in subs}
        for line in lines:
            sub = sub_by_idx.get(line.index)
            if not sub:
                continue
            sub.text_v1 = line.text_v1
            sub.text_v2 = line.text_v2
            sub.text = line.text_active
            sub.cps_value = line.cps_value
            sub.needs_review = line.needs_review
            sub.review_reason = line.review_reason
        self.db.commit()

        save_polish_to_db(self.db, self.project_id, report)

        await self._emit("polish_done", 95, report.summary)
        return report

    # ─── Full pipeline ──────────────────────────────────────

    async def run_full(self):
        """Chạy đủ pipeline (Stage 0-4). Stage 5 hiện đang disabled."""
        self._install_llm_observer()
        try:
            self._save_status("running", 0.0)

            # Stage 0 — chỉ chạy nếu enabled (mặc định True)
            if self.config.stage0.enabled:
                await self.run_normalize()
                self._check_cancelled()

            await self.run_bible()
            self._check_cancelled()

            await self.run_chunks()
            self._check_cancelled()

            await self.run_speaker()
            self._check_cancelled()

            await self.run_translate()
            self._check_cancelled()

            # Stage 5 disabled — bỏ qua
            # await self.run_polish()

            self._save_status("done", 100.0)
            await self._emit("done", 100,
                             f"Hoàn tất! ${self.tracker.total_cost_usd:.4f}")
        except asyncio.CancelledError:
            self._save_status("cancelled", 0.0, "Cancelled by user")
            raise
        except Exception as e:
            logger.exception(f"[TranslateRunner] failed: {e}")
            self._save_status("error", 0.0, str(e))
            await self._emit("error", 0, f"Lỗi: {e}")
            raise
        finally:
            self._uninstall_llm_observer()
        return self.tracker

    # ─── Stage runner (cho UI gọi 1 stage) ─────────────────

    async def run_stage(self, stage: str):
        """Chạy 1 stage cụ thể (resume from middle)."""
        self._install_llm_observer()
        try:
            if stage == "normalize":
                return await self.run_normalize()
            elif stage == "bible":
                return await self.run_bible()
            elif stage in ("chunks", "scenes"):
                return await self.run_chunks()
            elif stage == "speaker":
                return await self.run_speaker()
            elif stage == "translate":
                return await self.run_translate()
            elif stage == "polish":
                return await self.run_polish()
            else:
                raise ValueError(f"Unknown stage: {stage}")
        finally:
            self._uninstall_llm_observer()