"""
Pydantic schemas cho DubEditor v2.

Schema cũ giữ tương thích ngược, schema mới thêm cho translate v2.
"""
from pydantic import BaseModel, Field, model_validator
from typing import Optional, Literal
from datetime import datetime


# ─── Character ────────────────────────────────────────────────────────────────

class CharacterBase(BaseModel):
    name:             str
    description:      str = ""
    color:            str = "#378ADD"
    avatar:           str = ""
    voxcpm_role_id:   Optional[str] = None
    voxcpm_actor_name: str = ""
    voxcpm_role_name:  str = ""
    audio:             Optional[str] = None
    shortcut_key:      Optional[str] = None
    tts_speed:         float = 1.0

class CharacterCreate(CharacterBase): pass

class CharacterUpdate(BaseModel):
    name:              Optional[str] = None
    description:       Optional[str] = None
    color:             Optional[str] = None
    avatar:            Optional[str] = None
    voxcpm_role_id:    Optional[str] = None
    voxcpm_actor_name: Optional[str] = None
    voxcpm_role_name:  Optional[str] = None
    audio:             Optional[str] = None
    shortcut_key:      Optional[str] = None
    tts_speed:         Optional[float] = None
    # v2 fields có thể edit
    name_zh:           Optional[str] = None
    role:              Optional[str] = None
    gender:            Optional[str] = None
    personality:       Optional[str] = None
    speaking_style:    Optional[str] = None

class CharacterOut(CharacterBase):
    id:               int
    project_id:       int
    # v2 fields
    name_zh:          Optional[str] = None
    aliases_zh:       Optional[str] = None       # JSON string
    aliases_vi:       Optional[str] = None
    role:             str = "phu"
    gender:           str = "?"
    age_group:        Optional[str] = None
    social_status:    Optional[str] = None
    personality:      str = ""
    speaking_style:   str = ""
    self_address:     Optional[str] = None       # JSON
    addresses:        Optional[str] = None       # JSON
    relationships_json: Optional[str] = None
    notes:            str = ""
    class Config:
        from_attributes = True


# ─── Subtitle ─────────────────────────────────────────────────────────────────

class SubtitleBase(BaseModel):
    index:         int
    start_time:    float
    end_time:      float
    text:          str = ""
    original_text: Optional[str] = None
    character_id:  Optional[int] = None
    audio_offset:  float = 0.0

class SubtitleCreate(SubtitleBase): pass

class SubtitleUpdate(BaseModel):
    start_time:    Optional[float] = None
    end_time:      Optional[float] = None
    text:          Optional[str]   = None
    original_text: Optional[str]   = None
    character_id:  Optional[int]   = None
    scene_id:      Optional[int]   = None
    audio_offset:  Optional[float] = None
    tts_done:      Optional[bool]  = None
    wav_duration:  Optional[float] = None
    tts_speed:     Optional[float] = None
    # v2 fields editable
    speaker_zh:           Optional[str]   = None
    speaker_confidence:   Optional[str]   = None
    emotion:              Optional[str]   = None
    intensity:            Optional[int]   = None
    needs_review:         Optional[bool]  = None
    # v3: per-line voice mode override (null = auto theo emotion)
    tts_voice_mode:       Optional[str]   = None
    # v3: 2 variants — user có thể edit từng bản và chọn bản dùng
    text_v1:              Optional[str]   = None
    text_v2:              Optional[str]   = None
    variant_selected:     Optional[int]   = None  # 1 hoặc 2

class SubtitleOut(SubtitleBase):
    id:            int
    project_id:    int
    scene_id:      Optional[int] = None
    audio_path:    Optional[str] = None
    tts_done:      bool          = False
    wav_duration:  Optional[float] = None
    tts_speed:     Optional[float] = None
    character:     Optional[CharacterOut] = None
    # v2 fields
    speaker_zh:         Optional[str] = None
    speaker_confidence: str           = "low"
    speaker_reason:     str           = ""
    emotion:            Optional[str] = None
    intensity:          int           = 5
    cps_value:          Optional[float] = None
    needs_review:       bool          = False
    review_reason:      str           = ""
    text_draft:         Optional[str] = None
    is_hook:            bool          = False
    translation_version: int          = 1
    # v3: per-line voice mode override (user set manually)
    tts_voice_mode:     Optional[str] = None
    # v3: mode đã dùng khi tạo audio hiện tại (read-only)
    audio_voice_mode:   Optional[str] = None
    # v3 computed: mode được resolve từ (emotion, intensity, tts_voice_mode)
    # — hiển thị làm badge trên FE. Backend tính sẵn để FE consistent.
    voice_mode:         str           = "normal"
    # v3: 2 variants
    text_v1:            Optional[str] = None
    text_v2:            Optional[str] = None
    variant_selected:   int           = 1
    chunk_id:           Optional[int] = None
    # v3.1: noise filter
    is_noise:           bool          = False
    # v3.2: Stage 0 normalize
    is_cleaned:         bool          = False
    original_raw:       Optional[str] = None
    clean_reason:       Optional[str] = None

    @model_validator(mode="after")
    def _compute_voice_mode(self):
        from dubeditor.voice_modes import emotion_to_mode
        if self.tts_voice_mode and self.tts_voice_mode in ("normal", "sad", "angry"):
            self.voice_mode = self.tts_voice_mode
        else:
            self.voice_mode = emotion_to_mode(self.emotion, self.intensity)
        return self

    class Config:
        from_attributes = True


# ─── Project ──────────────────────────────────────────────────────────────────

class ProjectBase(BaseModel):
    name: str

class ProjectCreate(ProjectBase):
    project_type: str = "short_drama"

class ProjectOut(ProjectBase):
    id:                 int
    video_path:         Optional[str]      = None
    video_name:         Optional[str]      = None
    duration:           float              = 0.0
    created_at:         Optional[datetime] = None
    subtitle_count:     int                = 0
    tts_done_count:     int                = 0
    current_chapter_id: Optional[int]      = None
    source_lang:        str                = 'vi'
    # v2 fields
    project_type:       str                = 'short_drama'
    genre_pack:         Optional[str]      = None
    translate_status:   str                = 'idle'
    translate_progress: float              = 0.0
    translate_error:    Optional[str]      = None
    has_bible:          bool               = False
    scene_count:        int                = 0
    # v3: TTS toggle
    use_emotion_voice:  bool               = False
    tts_voice_mode:     Optional[str]      = None
    class Config:
        from_attributes = True


# ─── Chapter (giữ nguyên) ──────────────────────────────────────────────────────

class ChapterBase(BaseModel):
    name:            str = "Đoạn"
    start_sub_index: int
    end_sub_index:   int
    status:          str = "pending"
    collapsed:       int = 0
    sort_order:      int = 0

class ChapterCreate(ChapterBase): pass

class ChapterUpdate(BaseModel):
    name:            Optional[str] = None
    start_sub_index: Optional[int] = None
    end_sub_index:   Optional[int] = None
    status:          Optional[str] = None
    collapsed:       Optional[int] = None
    sort_order:      Optional[int] = None

class ChapterOut(ChapterBase):
    id:         int
    project_id: int
    source:     Optional[str] = "user"        # "user" | "auto_from_arc"
    arc_index:  Optional[int] = None          # Chỉ có nếu source="auto_from_arc"
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class AutoSplitRequest(BaseModel):
    size: int = 300

class SetCurrentChapterRequest(BaseModel):
    chapter_id: Optional[int] = None


# ─── TTS (giữ nguyên) ──────────────────────────────────────────────────────────

class TTSRequest(BaseModel):
    subtitle_id: int
    # v3: force voice mode chỉ cho lần TTS này
    force_voice_mode: Optional[str] = None

class BulkTTSRequest(BaseModel):
    subtitle_ids: list[int]
    # v3: force voice mode cho cả bulk
    force_voice_mode: Optional[str] = None

class BulkAssignRequest(BaseModel):
    subtitle_ids: list[int]
    character_id: int

class BulkSetSpeedRequest(BaseModel):
    subtitle_ids: list[int]
    tts_speed:    Optional[float] = None

class CharacterSetSpeedRequest(BaseModel):
    tts_speed:     float
    apply_to_subs: bool = True

class TTSEnqueueRequest(BaseModel):
    subtitle_ids: list[int]
    priority:     str = "normal"
    # v3: force voice mode cho lần TTS này (không lưu vào sub).
    # Values: 'normal' | 'sad' | 'angry' | None
    # Khi set: tự động bật use_emotion_voice tạm cho TTS này
    force_voice_mode: Optional[str] = None


# ─── Translate v2 schemas ─────────────────────────────────────────────────────

class TranslateConfig(BaseModel):
    """Cấu hình 1 lần chạy pipeline."""
    api_key:       str = ""    # Legacy single key (fallback nếu 3 key dưới rỗng)
    provider:      Literal["gemini", "openai", "deepseek"] = "gemini"
    # v3.12: Per-provider keys — cho phép mix model 3 provider trong cùng pipeline
    api_key_gemini:   str = ""
    api_key_openai:   str = ""
    api_key_deepseek: str = ""
    # ── Legacy tier (vẫn nhận để backward compat — frontend cũ vẫn dùng) ──
    model_heavy:   str = "gemini-2.5-pro"      # Bible, Translate
    model_medium:  str = "gemini-2.5-flash"    # Scene, Speaker
    model_light:   str = "gemini-2.5-flash"    # Retry
    # v3.3: thinking toggles per stage (chỉ Gemini 2.5+ / OpenAI o-series)
    # None = giữ default config (heavy/translate = bật, medium/light = tắt)
    # True/False = override
    heavy_thinking:     Optional[bool] = None   # Stage 1A Cast+Glossary
    medium_thinking:    Optional[bool] = None   # Stage 1B World, Stage 2, Stage 3
    light_thinking:     Optional[bool] = None   # Stage 0, Stage 5
    translate_thinking: Optional[bool] = None   # Stage 4 Translate (task chính)

    # ── v3.5: Per-stage model + thinking ────────────────────────────────
    # Frontend ConfigPanel mới gửi các field này, mỗi stage 1 model độc lập.
    # Empty string / None → fallback về tier cũ (heavy/medium/light) tương ứng.
    model_stage0:       Optional[str] = None    # Stage 0 Chuẩn hóa
    model_stage1:       Optional[str] = None    # Stage 1 LEGACY combined (vẫn giữ backward compat)
    model_stage1a:      Optional[str] = None    # Stage 1A Cast + Glossary (v3 split)
    model_stage1b:      Optional[str] = None    # Stage 1B World + Arcs (v3 split)
    model_stage2:       Optional[str] = None    # Stage 2 Chunks + Scenes
    model_stage3:       Optional[str] = None    # Stage 3 Speaker
    model_stage4:       Optional[str] = None    # Stage 4 Translate ⭐
    model_stage5:       Optional[str] = None    # Stage 5 Retry
    model_retranslate:  Optional[str] = None    # Retranslate trong editor

    thinking_stage0:       Optional[bool] = None
    thinking_stage1:       Optional[bool] = None
    thinking_stage1a:      Optional[bool] = None
    thinking_stage1b:      Optional[bool] = None
    thinking_stage2:       Optional[bool] = None
    thinking_stage3:       Optional[bool] = None
    thinking_stage4:       Optional[bool] = None
    thinking_stage5:       Optional[bool] = None
    thinking_retranslate:  Optional[bool] = None

    project_type:  str = "short_drama"
    cps_max:       Optional[float] = None      # None = dùng preset của project_type
    concurrency:   int = 5
    source_lang:   str = "zh"
    # v3: variant 2 bản dịch
    variant_mode:  Literal["off", "important_only", "always"] = "important_only"
    # v3: chunk overlap (sliding window)
    chunk_overlap: int = 30
    # v3: cached prefix
    cache_enabled: bool = True
    # v3: Bước 2 chạy song song hay tuần tự
    # False = tuần tự (mặc định) — chậm hơn 30% nhưng cache hit Bible giảm 50-90% cost
    # True  = song song — nhanh hơn nhưng tốn input token (không cache giữa arcs)
    chunks_parallel: bool = False
    # v3: Bước 3 speaker
    speaker_parallel: bool = True              # True=song song (nhanh), False=tuần tự (cache Bible)
    speaker_context_window: int = 20           # Số dòng context trước/sau chunk (read-only)
    # v3.2: Stage 0 — chuẩn hóa phụ đề
    stage0_enabled: bool = True                # Bật/tắt Stage 0 normalize
    stage0_model: Optional[str] = None         # (legacy) Model cho Stage 0 — nhường chỗ cho model_stage0
    stage0_context_window: int = 10            # Số dòng context xung quanh cluster (mỗi bên)


class TranslateStartRequest(TranslateConfig):
    """Khởi chạy full pipeline 5 stage."""
    pass


class TranslateStageRequest(TranslateConfig):
    """Chạy chỉ 1 stage cụ thể (debug)."""
    stage: Literal[
        "normalize",
        "bible",
        "bible_1a",
        "bible_1b",
        "scenes",
        "chunks",
        "speaker",
        "translate",
        "polish",
    ]


class RetranslateRequest(BaseModel):
    """Dịch lại 1 dòng cụ thể, trả 2 bản v1+v2. (Legacy — vẫn giữ.)"""
    subtitle_id:   int
    hint:          str = ""
    api_key:       str
    provider:      Literal["gemini", "openai", "deepseek"] = "gemini"
    model:         str = "gemini-2.5-flash"
    # v3: luôn trả 2 bản (frontend hiển thị cả 2 cho user chọn)
    return_variants: bool = True
    # v3.3: toggle thinking (None=default model / False=tắt nhanh+rẻ / True=bật chất lượng)
    thinking:      Optional[bool] = False
    # v3.5: số dòng context trước/sau gửi cho AI (default 2, cap 5)
    context_window: int = 2


# ─── v3.6: Retranslate BATCH — dịch lại 1-5 dòng cùng lúc ────────────────────
class RetranslateBatchRequest(BaseModel):
    """Dịch lại nhiều dòng cùng lúc (1-5).

    Dùng khi cụm sub liền mạch — VD cụm 3 sub cùng 1 câu TQ bị cắt nhỏ,
    sửa 1 dòng đơn lẻ thường ra rác nghĩa nên cho user chọn cả cụm.
    """
    subtitle_ids:  list[int]                     # 1-5 dòng — frontend cap
    hint:          str = ""
    api_key:       str
    provider:      Literal["gemini", "openai", "deepseek"] = "gemini"
    model:         str = "gemini-2.5-flash"
    thinking:      Optional[bool] = False
    # Số dòng context trước/sau (1-5, default 2). Tổng = N+context*2.
    context_window: int = 2


class RetranslateBatchLineOut(BaseModel):
    """1 dòng trong response của batch retranslate."""
    line_index:    int      # subtitle.index (không phải subtitle.id)
    subtitle_id:   int
    text_v1:       str
    text_v2:       Optional[str] = None
    emotion:       Optional[str] = None
    intensity:     Optional[int] = None
    current_text_v1: Optional[str] = None
    current_text_v2: Optional[str] = None


class RetranslateBatchResponse(BaseModel):
    ok:            bool
    lines:         list[RetranslateBatchLineOut]
    tokens_in:     int = 0
    tokens_out:    int = 0


class SelectVariantRequest(BaseModel):
    """User chọn bản nào dùng (1 hoặc 2)."""
    subtitle_id:    int
    variant:        Literal[1, 2]


# ─── v3.13: Retranslate 1 CHUNK ──────────────────────────────────────────────

class RetranslateChunkRequest(TranslateConfig):
    """Dịch lại 1 chunk cụ thể.

    Kế thừa TranslateConfig để dùng lại logic build_pipeline_config + per-stage
    model/thinking + variant_mode.

    mode:
      - 'all':           dịch lại TOÀN BỘ dòng trong chunk (ghi đè text_v1/v2 mọi dòng)
      - 'errors_only':   chỉ ghi đè những dòng có needs_review=True, text_v1 rỗng,
                         còn ký tự TQ, hoặc bắt đầu bằng '[CHƯA DỊCH'.
                         AI vẫn nhận FULL chunk để có context, nhưng chỉ những dòng
                         lỗi mới được save vào DB.
    """
    chunk_id:       int
    mode:           Literal["all", "errors_only"] = "all"


class RetranslateChunkResponse(BaseModel):
    """Kết quả dịch lại 1 chunk."""
    ok:                  bool
    chunk_id:            int
    mode:                str
    lines_in_chunk:      int          # tổng số dòng trong chunk
    lines_targeted:      int          # số dòng dự định ghi đè (theo mode)
    lines_updated:       int          # số dòng AI trả về và đã save DB
    lines_v2:            int          # số dòng có text_v2
    lines_still_error:   int          # sau retry, còn bao nhiêu dòng lỗi
    cost_usd:            float = 0.0
    tokens_in:           int = 0
    tokens_out:          int = 0
    cached_tokens:       int = 0
    duration_ms:         int = 0
    error:               Optional[str] = None


class BibleOut(BaseModel):
    """Bible content cho FE."""
    id:               int
    version:          int
    is_active:        bool
    cast:             dict
    world:            dict
    glossary:         dict
    genre_pack_id:    Optional[str] = None  # deprecated v3
    tokens_in:        int = 0
    tokens_out:       int = 0
    cost_usd:         float = 0.0
    created_at:       Optional[datetime] = None


class SceneOut(BaseModel):
    id:                 int
    project_id:         int
    scene_index:        int
    start_line:         int
    end_line:           int
    start_time_sec:     float = 0.0
    end_time_sec:       float = 0.0
    location:           str = ""
    time_of_day:        Optional[str] = None
    characters_present: list[str] = Field(default_factory=list)
    emotion_primary:    str = "neutral"
    emotion_arc:        str = ""
    summary:            str = ""
    purpose:            str = ""
    story_arc_id:       Optional[int] = None
    chunk_id:           Optional[int] = None  # v3
    is_hook:            bool = False
    is_emotion_peak:    bool = False
    status:             str = "pending"
    error_message:      Optional[str] = None
    line_count:         int = 0


class ChunkOut(BaseModel):
    """Chunk v3 — chương trong arc."""
    id:             int
    project_id:     int
    arc_index:      int
    chunk_index:    int
    title:          str = ""
    start_line:     int
    end_line:       int
    status:         str = "pending"
    line_count:     int = 0
    scene_count:    int = 0
    arc_title:      Optional[str] = None
    arc_tone:       Optional[str] = None
    # v3.13: Retranslate per chunk
    error_message:      Optional[str] = None  # Lỗi gần nhất khi dịch chunk này
    lines_with_errors:  int = 0               # Số dòng cần dịch lại (needs_review / rỗng / còn TQ)


class StoryArcOut(BaseModel):
    id:              int
    arc_index:       int
    title:           str = ""
    summary:         str = ""
    start_line:      int = 1
    end_line:        int = 1
    emotional_tone:  str = ""
    key_events:      list[str] = Field(default_factory=list)
    scene_count:     int = 0


class PolishIssueOut(BaseModel):
    id:             int
    line_index:     int
    subtitle_id:    Optional[int] = None
    issue_type:     str
    description:    str
    current_text:   str
    suggested_text: Optional[str] = None
    confidence:     str
    evidence:       str = ""
    resolved:       bool = False
    class Config:
        from_attributes = True


class TranslateStatusOut(BaseModel):
    project_id:       int
    status:           str
    current_stage:    Optional[str] = None
    progress:         float = 0.0
    has_bible:        bool = False
    # v3: cast + world tracking riêng để FE biết 1A xong nhưng 1B chưa
    has_cast:         bool = False       # Bible có ≥1 nhân vật → coi là 1A xong
    has_world:        bool = False       # Bible có ≥1 arc → coi là 1B xong
    cast_count:       int = 0            # số nhân vật trong Bible
    world_arcs_count: int = 0            # số arcs trong Bible.world
    chunk_count:      int = 0       # v3
    scene_count:      int = 0
    speaker_assigned_count: int = 0
    translated_count: int = 0
    variants_count:   int = 0       # v3: dòng có text_v2
    review_count:     int = 0
    avg_cps:          float = 0.0
    cost_usd:         float = 0.0
    tokens_in:        int = 0
    tokens_out:       int = 0
    error_message:    Optional[str] = None
    # v3.2: Stage 0 normalize stats
    cleaned_count:    int = 0       # dòng đã được Stage 0 sửa (is_cleaned=True)
    removed_count:    int = 0       # dòng đã bị Stage 0 đánh dấu noise
    # v3: marker Stage 0 đã chạy (dù có thể không sửa/xóa gì)
    stage0_ran:       bool = False
    # v3: resume — next_stage là stage chưa xong, can_resume = đang dở dang
    next_stage:       Optional[str] = None
    can_resume:       bool = False


class CleanedSubtitleOut(BaseModel):
    """1 dòng đã được Stage 0 xử lý."""
    id:           int
    index:        int
    start_time:   float
    end_time:     float
    original_raw: Optional[str] = None    # text gốc trước khi clean
    current_text: str                      # text hiện tại (sau clean) — rỗng nếu removed
    is_noise:     bool                     # True = bị remove
    clean_reason: Optional[str] = None     # AI giải thích lý do
    action:       str                      # "remove" | "clean" (derived)

    model_config = {"from_attributes": True}


class SuspiciousLineOut(BaseModel):
    """1 dòng nghi ngờ từ scan heuristic (chưa qua AI)."""
    index:        int
    text:         str
    reasons:      list[str]


class ScanResultOut(BaseModel):
    """Kết quả scan heuristic — preview trước khi gửi AI."""
    total_lines:       int
    suspicious_count:  int
    cluster_count:     int
    suspicious_lines:  list[SuspiciousLineOut]


class Stage0RunResultOut(BaseModel):
    """Kết quả chạy Stage 0 (scan + AI analyze + apply)."""
    total_lines:       int
    suspicious_count:  int
    cluster_count:     int
    removed_count:     int
    cleaned_count:     int
    kept_count:        int
    cost_usd:          float
    tokens_in:         int
    tokens_out:        int