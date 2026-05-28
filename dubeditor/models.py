"""
dubeditor/models.py (v4 — Simple Translator pipeline)

⚠️ THAY ĐỔI SO VỚI v3:
  - BỎ models: Bible, StoryArc, Chunk, Scene, PolishIssue
  - BỎ cột trên Subtitle: speaker_zh, speaker_confidence, speaker_reason,
                          text_v1, text_v2, variant_selected,
                          text_draft, is_cleaned, original_raw, clean_reason,
                          chunk_id, scene_id
  - BỎ relationship Project.bibles, .scenes, .story_arcs, .chunks
  - THÊM cột trên Subtitle: simple_speaker_zh, simple_text_vi, simple_status
  - GIỮ NGUYÊN: Character, Chapter, RemovedSubtitle, Admin, Actor, Role, RoleImage,
                LLMCall, PipelineEvent, ModelPreset, AppSetting
  - GIỮ NGUYÊN Project fields về TTS, lang, project_type (translate_status có thể
    không còn dùng nhưng giữ cho backward compat)

Bảng mới của Simple pipeline nằm ở dubeditor/simple/models.py (5 bảng):
  - SimpleBiblePart, SimpleBibleMerge, SimpleBatch, SimpleReviewGroup, SimpleIssue
"""
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from dubeditor.database import Base


# ─── Project ─────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"
    id                 = Column(Integer, primary_key=True, index=True)
    name               = Column(String, nullable=False)
    video_path         = Column(String, nullable=True)
    video_name         = Column(String, nullable=True)
    duration           = Column(Float, default=0.0)
    created_at         = Column(DateTime(timezone=True), server_default=func.now())
    updated_at         = Column(DateTime(timezone=True), onupdate=func.now())
    current_chapter_id = Column(Integer, nullable=True)
    # ── Lang / type (giữ để backward compat) ────────────────────────────────
    source_lang        = Column(String, default='vi')
    project_type       = Column(String, default='short_drama')
    genre_pack         = Column(String, nullable=True)
    # translate_status: giữ field nhưng giờ Simple pipeline có state riêng trong simple_batches
    translate_status   = Column(String, default='idle')
    translate_progress = Column(Float, default=0.0)
    translate_error    = Column(Text, nullable=True)
    # ── TTS settings ────────────────────────────────────────────────────────
    use_emotion_voice  = Column(Boolean, default=False)
    tts_voice_mode     = Column(String, nullable=True)
    # ── Editor resume state ────────────────────────────────────────────────
    last_filter_chapter_ids = Column(Text, nullable=True)
    last_subtitle_index     = Column(Integer, nullable=True)
    # ── Relationships ───────────────────────────────────────────────────────
    subtitles  = relationship("Subtitle",  back_populates="project", cascade="all, delete")
    characters = relationship("Character", back_populates="project", cascade="all, delete")
    chapters   = relationship("Chapter",   back_populates="project", cascade="all, delete",
                              order_by="Chapter.sort_order")


# ─── Character ───────────────────────────────────────────────────────────────

class Character(Base):
    __tablename__ = "characters"
    id                = Column(Integer, primary_key=True, index=True)
    project_id        = Column(Integer, ForeignKey("projects.id"), nullable=False)
    name              = Column(String, nullable=False)
    description       = Column(String, default="")
    color             = Column(String, default="#378ADD")
    avatar            = Column(String, default="")
    voxcpm_role_id    = Column(String, nullable=True)
    voxcpm_actor_name = Column(String, default="")
    voxcpm_role_name  = Column(String, default="")
    audio             = Column(String, nullable=True)
    shortcut_key      = Column(String, nullable=True)
    tts_speed         = Column(Float, default=1.0)
    # ── v2 fields ──────────────────────────────────────────────────────────
    name_zh           = Column(String, nullable=True)
    aliases_zh        = Column(Text, nullable=True)
    aliases_vi        = Column(Text, nullable=True)
    role              = Column(String, default='phu')
    gender            = Column(String, default='?')
    age_group         = Column(String, nullable=True)
    social_status     = Column(String, nullable=True)
    personality       = Column(Text, default="")
    speaking_style    = Column(Text, default="")
    self_address      = Column(Text, nullable=True)
    addresses         = Column(Text, nullable=True)
    relationships_json= Column(Text, nullable=True)
    notes             = Column(Text, default="")
    # ── Relationships ───────────────────────────────────────────────────────
    project   = relationship("Project",  back_populates="characters")
    subtitles = relationship("Subtitle", back_populates="character")


# ─── Subtitle ────────────────────────────────────────────────────────────────

class Subtitle(Base):
    __tablename__ = "subtitles"
    id            = Column(Integer, primary_key=True, index=True)
    project_id    = Column(Integer, ForeignKey("projects.id"), nullable=False)
    character_id  = Column(Integer, ForeignKey("characters.id"), nullable=True)
    index         = Column(Integer, nullable=False)
    start_time    = Column(Float, nullable=False)
    end_time      = Column(Float, nullable=False)
    text          = Column(Text, default="")             # Bản dịch chính (legacy; có thể đồng bộ với simple_text_vi)
    original_text = Column(Text, nullable=True)          # Text gốc tiếng Trung
    audio_path    = Column(String, nullable=True)
    audio_offset  = Column(Float, default=0.0)
    tts_done      = Column(Boolean, default=False)
    wav_duration  = Column(Float, nullable=True)
    tts_speed     = Column(Float, nullable=True)
    audio_voice_mode = Column(String, nullable=True)
    # ── Field còn lại sau khi bỏ pipeline cũ ──────────────────────────────
    emotion       = Column(String, nullable=True)
    intensity     = Column(Integer, default=5)
    cps_value     = Column(Float, nullable=True)
    needs_review  = Column(Boolean, default=False)
    review_reason = Column(Text, default="")
    is_hook       = Column(Boolean, default=False)
    translation_version  = Column(Integer, default=1)
    is_noise      = Column(Boolean, default=False)
    tts_voice_mode = Column(String, nullable=True)
    # ── Simple pipeline v4 fields ────────────────────────────────────────
    # Speaker từ pipeline mới (tên Trung gốc hoặc special: UNKNOWN/CROWD/NARRATOR/OFF_SCREEN/PHONE)
    simple_speaker_zh = Column(String, nullable=True)
    # Bản dịch Việt từ pipeline mới
    simple_text_vi    = Column(Text, nullable=True)
    # Trạng thái pipeline: pending | translated | has_error | fixed
    simple_status     = Column(String, default='pending', index=True)
    # ── Relationships ───────────────────────────────────────────────────────
    project   = relationship("Project",   back_populates="subtitles")
    character = relationship("Character", back_populates="subtitles")
    __table_args__ = (
        Index('ix_subtitles_project_index', 'project_id', 'index'),
    )


# ─── Chapter ─────────────────────────────────────────────────────────────────

class Chapter(Base):
    __tablename__ = "chapters"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    name            = Column(String, nullable=False, default="Đoạn")
    start_sub_index = Column(Integer, nullable=False)
    end_sub_index   = Column(Integer, nullable=False)
    status          = Column(String, default="pending")
    collapsed       = Column(Integer, default=0)
    sort_order      = Column(Integer, default=0)
    source          = Column(String, default="user")
    arc_index       = Column(Integer, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="chapters")


# ─── RemovedSubtitle (giữ — dùng cho feature undo của Editor) ───────────────

class RemovedSubtitle(Base):
    __tablename__ = "removed_subtitles"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    original_index  = Column(Integer, nullable=False)
    removed_after_index = Column(Integer, nullable=True)
    start_time      = Column(Float, nullable=False)
    end_time        = Column(Float, nullable=False)
    original_text   = Column(Text, default="")
    clean_reason    = Column(Text, default="")
    removed_at      = Column(DateTime(timezone=True), server_default=func.now())


# ─── VoiceCast Models (giữ nguyên) ───────────────────────────────────────────

class Admin(Base):
    __tablename__ = "admins"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    username   = Column(String, unique=True, nullable=False)
    password   = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class Actor(Base):
    __tablename__ = "actors"
    id         = Column(String, primary_key=True)
    name       = Column(String, nullable=False)
    gender     = Column(String, nullable=False, default="nam")
    birth_year = Column(Integer, nullable=True)
    avatar     = Column(String, default="")
    bio        = Column(String, default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    roles      = relationship("Role", back_populates="actor", cascade="all, delete",
                              order_by="Role.sort_order")


class Role(Base):
    __tablename__ = "roles"
    id                   = Column(String, primary_key=True)
    actor_id             = Column(String, ForeignKey("actors.id", ondelete="CASCADE"), nullable=False)
    character_name       = Column(String, nullable=False)
    show_name            = Column(String, default="")
    type                 = Column(String, default="chinh")
    genre                = Column(String, default="hien-dai")
    description          = Column(String, default="")
    audio                = Column(String, default="")
    reference_audio_text = Column(String, default="")
    lora_path            = Column(String, default="")
    sort_order           = Column(Integer, default=0)
    created_at           = Column(DateTime, server_default=func.now())
    voice_modes          = Column(Text, nullable=True)
    actor  = relationship("Actor", back_populates="roles")
    images = relationship("RoleImage", back_populates="role", cascade="all, delete",
                          order_by="RoleImage.sort_order")


class RoleImage(Base):
    __tablename__ = "role_images"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    role_id    = Column(String, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    url        = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    role       = relationship("Role", back_populates="images")


# ─── Log persistence (giữ — dùng cho debug pipeline mới) ────────────────────

class LLMCall(Base):
    __tablename__ = "llm_calls"
    id            = Column(Integer, primary_key=True, autoincrement=True)
    project_id    = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                            index=True, nullable=False)
    created_at    = Column(Float, index=True)
    stage_tag     = Column(String, nullable=True)
    provider      = Column(String, nullable=True)
    model         = Column(String, nullable=True)
    attempt       = Column(Integer, default=1)
    tokens_in     = Column(Integer, default=0)
    tokens_out    = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    timing_ms     = Column(Integer, default=0)
    temperature   = Column(Float, default=0.0)
    json_mode     = Column(Boolean, default=False)
    thinking      = Column(Text, nullable=True)
    finish_reason = Column(String, nullable=True)
    error         = Column(Text, nullable=True)
    prompt_full   = Column(Text, nullable=True)
    response_full = Column(Text, nullable=True)


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    created_at  = Column(Float, index=True)
    stage       = Column(String, nullable=True)
    progress    = Column(Float, default=0.0)
    message     = Column(String, nullable=True)
    detail_json = Column(Text, nullable=True)


# ─── Settings (giữ — Simple pipeline cũng dùng AppSetting) ──────────────────

class ModelPreset(Base):
    """Preset cấu hình model (LEGACY từ pipeline v3, có thể bỏ sau).

    Simple pipeline KHÔNG dùng preset này — tự config qua endpoint /simple/config/.
    Giữ class để không break dữ liệu cũ + router presets.py.
    """
    __tablename__ = "model_presets"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String, nullable=False, unique=True)
    description = Column(String, nullable=True)
    model_stage0      = Column(String, nullable=True)
    model_stage1      = Column(String, nullable=True)
    model_stage2      = Column(String, nullable=True)
    model_stage3      = Column(String, nullable=True)
    model_stage4      = Column(String, nullable=True)
    model_stage5      = Column(String, nullable=True)
    model_retranslate = Column(String, nullable=True)
    is_default        = Column(Boolean, default=False)
    created_at        = Column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """Key-value store. Simple pipeline dùng key `simple_config:{project_id}`."""
    __tablename__ = "app_settings"
    key   = Column(String, primary_key=True)
    value = Column(Text, nullable=True)


# ─── Import simple models để Base.metadata biết ─────────────────────────────
# (Phải import sau khi class Project được khai báo vì có FK references)
from dubeditor.simple import models as _simple_models  # noqa: E402, F401
