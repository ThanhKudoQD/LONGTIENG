from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from dubeditor.database import Base

# ─── DubEditor Models ─────────────────────────────────────────────────────────

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
    # ── Translate v2 fields ──────────────────────────────────────────────────
    source_lang        = Column(String, default='vi')          # 'zh' | 'vi'
    project_type       = Column(String, default='short_drama') # 'short_drama'|'drama_series'|'movie'
    genre_pack         = Column(String, nullable=True)         # ID của genre pack
    translate_status   = Column(String, default='idle')        # idle|stage0|stage1|stage2|stage3|stage4|stage5|done|error
    translate_progress = Column(Float, default=0.0)            # 0-100
    translate_error    = Column(Text, nullable=True)
    # ── TTS settings (per-project) ───────────────────────────────────────────
    # Khi True: TTS dùng Role.voice_modes resolve theo Subtitle.emotion
    # Khi False: TTS dùng Role.audio + Role.reference_audio_text mặc định
    use_emotion_voice  = Column(Boolean, default=False)
    # Global override mode khi use_emotion_voice=True. Null = auto theo emotion.
    # Subtitle.tts_voice_mode (nếu set) sẽ override field này per-line.
    tts_voice_mode     = Column(String, nullable=True)
    # ── Relationships ────────────────────────────────────────────────────────
    subtitles  = relationship("Subtitle",  back_populates="project", cascade="all, delete")
    characters = relationship("Character", back_populates="project", cascade="all, delete")
    chapters   = relationship("Chapter",   back_populates="project", cascade="all, delete", order_by="Chapter.sort_order")
    bibles     = relationship("Bible",     back_populates="project", cascade="all, delete")
    scenes     = relationship("Scene",     back_populates="project", cascade="all, delete", order_by="Scene.scene_index")
    story_arcs = relationship("StoryArc",  back_populates="project", cascade="all, delete", order_by="StoryArc.arc_index")
    chunks     = relationship("Chunk",     back_populates="project", cascade="all, delete", order_by="Chunk.chunk_index")

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
    # ── v2 fields (từ Bible.cast) ────────────────────────────────────────────
    name_zh           = Column(String, nullable=True)        # Tên Trung gốc
    aliases_zh        = Column(Text, nullable=True)          # JSON array
    aliases_vi        = Column(Text, nullable=True)          # JSON array
    role              = Column(String, default='phu')        # nam_chinh|nu_chinh|...
    gender            = Column(String, default='?')          # nam|nu|?
    age_group         = Column(String, nullable=True)
    social_status     = Column(String, nullable=True)
    personality       = Column(Text, default="")
    speaking_style    = Column(Text, default="")
    self_address      = Column(Text, nullable=True)          # JSON Pronouns
    addresses         = Column(Text, nullable=True)          # JSON dict
    relationships_json= Column(Text, nullable=True)          # JSON dict (avoid Python keyword)
    notes             = Column(Text, default="")
    # ── Relationships ────────────────────────────────────────────────────────
    project   = relationship("Project",  back_populates="characters")
    subtitles = relationship("Subtitle", back_populates="character")

class Subtitle(Base):
    __tablename__ = "subtitles"
    id            = Column(Integer, primary_key=True, index=True)
    project_id    = Column(Integer, ForeignKey("projects.id"), nullable=False)
    character_id  = Column(Integer, ForeignKey("characters.id"), nullable=True)
    scene_id      = Column(Integer, ForeignKey("scenes.id"), nullable=True)
    index         = Column(Integer, nullable=False)
    start_time    = Column(Float, nullable=False)
    end_time      = Column(Float, nullable=False)
    text          = Column(Text, default="")             # Bản dịch tiếng Việt
    original_text = Column(Text, nullable=True)          # Văn bản gốc tiếng Trung (= text_zh)
    audio_path    = Column(String, nullable=True)
    audio_offset  = Column(Float, default=0.0)
    tts_done      = Column(Boolean, default=False)
    wav_duration  = Column(Float, nullable=True)
    tts_speed     = Column(Float, nullable=True)
    # v3: mode đã dùng khi tạo audio (track cho UI hiển thị icon)
    # Values: 'normal' | 'sad' | 'angry' | None
    audio_voice_mode = Column(String, nullable=True)
    # ── v2 fields ────────────────────────────────────────────────────────────
    speaker_zh           = Column(String, nullable=True)      # Tên Trung của speaker (raw)
    speaker_confidence   = Column(String, default='low')      # high|mid|low
    speaker_reason       = Column(Text, default="")           # Lý do gán speaker (debug)
    emotion              = Column(String, nullable=True)      # neutral|angry|sad|...
    intensity            = Column(Integer, default=5)         # 1-10
    cps_value            = Column(Float, nullable=True)       # Characters per second
    needs_review         = Column(Boolean, default=False)
    review_reason        = Column(Text, default="")
    text_draft           = Column(Text, nullable=True)        # Bản nháp trước polish
    is_hook              = Column(Boolean, default=False)
    translation_version  = Column(Integer, default=1)
    # ── v3: 2 bản dịch (variant) ─────────────────────────────────────────────
    # text_v1 = sát nghĩa (mặc định, dùng cho subtitle)
    # text_v2 = thoát ý (cho lồng tiếng tự nhiên, nullable)
    # variant_selected: 1 hoặc 2 — user chọn bản nào dùng cho TTS/export
    # Field `text` luôn = text_v1 hoặc text_v2 theo variant_selected
    text_v1              = Column(Text, nullable=True)
    text_v2              = Column(Text, nullable=True)
    variant_selected     = Column(Integer, default=1)
    # ── v3: noise filter ─────────────────────────────────────────────────────
    # True nếu dòng là marker phụ đề ([音乐], (笑), *sigh*...) hoặc filler rỗng nghĩa
    # FE có thể ẩn các dòng này khi export SRT / TTS
    is_noise             = Column(Boolean, default=False)
    # ── v3.2: Stage 0 normalize (Bước 0 — Chuẩn hóa phụ đề) ─────────────────
    # is_cleaned: True nếu AI đã sửa text gốc ở Stage 0
    # original_raw: text gốc trước khi Stage 0 sửa (giữ để recover)
    # clean_reason: lý do AI sửa/xóa (vd "watermark 腾讯视频", "tab thừa")
    is_cleaned           = Column(Boolean, default=False)
    original_raw         = Column(Text, nullable=True)
    clean_reason         = Column(Text, nullable=True)
    # ── v3: Reference chunk (để FE group) ────────────────────────────────────
    chunk_id             = Column(Integer, ForeignKey("chunks.id"), nullable=True, index=True)
    # ── v3: TTS per-line override ────────────────────────────────────────────
    # Override voice mode khi TTS dòng này. Null = auto theo emotion.
    # Values: 'normal' | 'happy' | 'sad' | 'angry' | 'intimate' | null
    tts_voice_mode       = Column(String, nullable=True)
    # ── Relationships ────────────────────────────────────────────────────────
    project   = relationship("Project",   back_populates="subtitles")
    character = relationship("Character", back_populates="subtitles")
    scene     = relationship("Scene",     back_populates="subtitles")

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
    source          = Column(String, default="user")   # "user" (user tạo) | "auto_from_arc" (sync từ pipeline StoryArc)
    arc_index       = Column(Integer, nullable=True)   # Nếu source="auto_from_arc": index arc tương ứng (để re-sync)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    project = relationship("Project", back_populates="chapters")


# ── v3.2: Log dòng đã bị Stage 0 xóa (để hiển thị tab Chuẩn hóa) ──────────────
class RemovedSubtitle(Base):
    """Log dòng đã bị Stage 0 xóa khỏi DB.

    Sau khi Stage 0 quyết định "remove" 1 dòng, ta lưu thông tin gốc ở đây
    để user có thể xem lại và hoàn tác (re-insert vào subtitles + reindex).
    """
    __tablename__ = "removed_subtitles"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    # Index gốc tại thời điểm xóa (trong dải 1..N của lần upload đầu)
    original_index  = Column(Integer, nullable=False)
    # Index hiện tại trong DB sau khi đã reindex (có thể null nếu xóa nhiều lần)
    removed_after_index = Column(Integer, nullable=True)
    start_time      = Column(Float, nullable=False)
    end_time        = Column(Float, nullable=False)
    original_text   = Column(Text, default="")
    clean_reason    = Column(Text, default="")
    removed_at      = Column(DateTime(timezone=True), server_default=func.now())


class Bible(Base):
    """Bible v2 — hồ sơ phim đầy đủ.

    Mỗi project có thể có nhiều version Bible (giữ lịch sử).
    Active = version có is_active=True. Stage 1 luôn tạo version mới.
    """
    __tablename__ = "bibles"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    version         = Column(Integer, default=1)
    is_active       = Column(Boolean, default=True)
    # ── Bible content (3 phần) ───────────────────────────────────────────────
    cast_json       = Column(Text, default="{}")        # Bible.cast (Pydantic)
    world_json      = Column(Text, default="{}")        # Bible.world (genre + arcs)
    glossary_json   = Column(Text, default="{}")        # Bible.glossary
    genre_pack_id   = Column(String, nullable=True)     # ID pack đã match
    # ── Cost tracking ────────────────────────────────────────────────────────
    tokens_in       = Column(Integer, default=0)
    tokens_out      = Column(Integer, default=0)
    cost_usd        = Column(Float, default=0.0)
    model_used      = Column(String, nullable=True)
    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    # ── Relationships ────────────────────────────────────────────────────────
    project = relationship("Project", back_populates="bibles")


class StoryArc(Base):
    """Story arc — 1 đoạn cốt truyện lớn (3-6 arc/phim)."""
    __tablename__ = "story_arcs"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    arc_index       = Column(Integer, nullable=False)
    title           = Column(String, default="")
    summary         = Column(Text, default="")
    start_line      = Column(Integer, default=1)
    end_line        = Column(Integer, default=1)
    emotional_tone  = Column(String, default="")
    key_events      = Column(Text, default="[]")        # JSON array
    # ── Relationships ────────────────────────────────────────────────────────
    project = relationship("Project", back_populates="story_arcs")
    scenes  = relationship("Scene", back_populates="story_arc")


class Chunk(Base):
    """Chunk v3 — chương trong arc.

    Cấu trúc 3 tầng: Arc → Chunk → Scene
    Mỗi arc có 3-8 chunks. Mỗi chunk ~250-400 dòng.
    Chunk ≤ 100 dòng KHÔNG chia scenes (chunk = scene duy nhất).
    """
    __tablename__ = "chunks"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    arc_index       = Column(Integer, nullable=False)         # Thuộc arc nào
    chunk_index     = Column(Integer, nullable=False)         # Index trong project (0-based)
    title           = Column(String, default="")
    start_line      = Column(Integer, nullable=False)
    end_line        = Column(Integer, nullable=False)
    # Status pipeline
    status          = Column(String, default="pending")       # pending|speaker|translated|done|error
    error_message   = Column(Text, nullable=True)
    # Timestamps
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), onupdate=func.now())
    # Relationships
    project = relationship("Project", back_populates="chunks")
    scenes  = relationship("Scene", back_populates="chunk", order_by="Scene.scene_index")


class Scene(Base):
    """Phân cảnh kịch — đơn vị xử lý của pipeline v2.

    1 phim short drama có ~150-250 scenes. Mỗi scene = 1 địa điểm + 1 thời gian
    + 1 nhóm nhân vật + 1 mục đích kịch.
    """
    __tablename__ = "scenes"
    id                  = Column(Integer, primary_key=True, index=True)
    project_id          = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    scene_index         = Column(Integer, nullable=False)
    # ── Ranh giới ────────────────────────────────────────────────────────────
    start_line          = Column(Integer, nullable=False)
    end_line            = Column(Integer, nullable=False)
    start_time_sec      = Column(Float, default=0.0)
    end_time_sec        = Column(Float, default=0.0)
    # ── Bối cảnh ─────────────────────────────────────────────────────────────
    location            = Column(String, default="")
    time_of_day         = Column(String, nullable=True)
    characters_present  = Column(Text, default="[]")    # JSON array tên Trung
    # ── Cảm xúc ──────────────────────────────────────────────────────────────
    emotion_primary     = Column(String, default="neutral")
    emotion_arc         = Column(String, default="")
    # ── Nội dung ─────────────────────────────────────────────────────────────
    summary             = Column(Text, default="")
    purpose             = Column(Text, default="")
    # ── Liên kết ─────────────────────────────────────────────────────────────
    story_arc_id        = Column(Integer, ForeignKey("story_arcs.id"), nullable=True)
    chunk_id            = Column(Integer, ForeignKey("chunks.id"), nullable=True, index=True)
    # ── Flags ────────────────────────────────────────────────────────────────
    is_hook             = Column(Boolean, default=False)
    is_emotion_peak     = Column(Boolean, default=False)
    # ── Status trong pipeline ────────────────────────────────────────────────
    status              = Column(String, default="pending")  # pending|speaker|translated|polished|error
    error_message       = Column(Text, nullable=True)
    # ── Cost tracking (per scene) ────────────────────────────────────────────
    tokens_in           = Column(Integer, default=0)
    tokens_out          = Column(Integer, default=0)
    cost_usd            = Column(Float, default=0.0)
    timing_ms           = Column(Integer, default=0)
    # ── Timestamps ───────────────────────────────────────────────────────────
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())
    # ── Relationships ────────────────────────────────────────────────────────
    project   = relationship("Project", back_populates="scenes")
    story_arc = relationship("StoryArc", back_populates="scenes")
    chunk     = relationship("Chunk", back_populates="scenes")
    subtitles = relationship("Subtitle", back_populates="scene")


class PolishIssue(Base):
    """Issue được phát hiện ở Stage 5 polish — để FE hiển thị review queue."""
    __tablename__ = "polish_issues"
    id              = Column(Integer, primary_key=True, index=True)
    project_id      = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    subtitle_id     = Column(Integer, ForeignKey("subtitles.id"), nullable=True, index=True)
    line_index      = Column(Integer, nullable=False)
    issue_type      = Column(String, default="other")   # speaker|pronoun|consistency|glossary|cps|...
    description     = Column(Text, default="")
    current_text    = Column(Text, default="")
    suggested_text  = Column(Text, nullable=True)
    confidence      = Column(String, default="mid")     # high|mid|low
    evidence        = Column(Text, default="")
    resolved        = Column(Boolean, default=False)    # User đã xử lý chưa
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

# ─── VoiceCast Models ─────────────────────────────────────────────────────────

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
    roles      = relationship("Role", back_populates="actor", cascade="all, delete", order_by="Role.sort_order")

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
    # ── Multi-mode voice refs (v3) ───────────────────────────────────────────
    # Schema:
    # {
    #   "normal":   {"audio": "/uploads/...", "text": "...", "duration": 3.5},
    #   "happy":    {"audio": "/uploads/...", "text": "...", "duration": 4.2},
    #   "sad":      {"audio": "/uploads/...", "text": "...", "duration": 3.8},
    #   "angry":    {"audio": "/uploads/...", "text": "...", "duration": 2.1},
    #   "intimate": {"audio": "/uploads/...", "text": "...", "duration": 4.5},
    # }
    # "normal" bắt buộc (default fallback). 4 mode khác optional.
    # Toggle bật/tắt nằm ở Project.use_emotion_voice (global per-project).
    voice_modes          = Column(Text, nullable=True)         # JSON
    actor  = relationship("Actor", back_populates="roles")
    images = relationship("RoleImage", back_populates="role", cascade="all, delete", order_by="RoleImage.sort_order")

class RoleImage(Base):
    __tablename__ = "role_images"
    id         = Column(Integer, primary_key=True, autoincrement=True)
    role_id    = Column(String, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False)
    url        = Column(String, nullable=False)
    sort_order = Column(Integer, default=0)
    role       = relationship("Role", back_populates="images")