"""
Pydantic schemas cho DubEditor v2.

Schema cũ giữ tương thích ngược, schema mới thêm cho translate v2.
"""
from pydantic import BaseModel, Field
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
    # v3: per-line voice mode override
    tts_voice_mode:     Optional[str] = None
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

class BulkTTSRequest(BaseModel):
    subtitle_ids: list[int]

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


# ─── Translate v2 schemas ─────────────────────────────────────────────────────

class TranslateConfig(BaseModel):
    """Cấu hình 1 lần chạy pipeline."""
    api_key:       str
    provider:      Literal["gemini", "openai", "deepseek"] = "gemini"
    model_heavy:   str = "gemini-2.5-pro"      # Bible, Translate
    model_medium:  str = "gemini-2.5-flash"    # Scene, Speaker, Polish
    model_light:   str = "gemini-2.5-flash"    # CPS condense
    project_type:  str = "short_drama"
    genre_pack:    Optional[str] = None        # None = auto detect
    cps_max:       Optional[float] = None      # None = dùng preset của project_type
    concurrency:   int = 5
    source_lang:   str = "zh"


class TranslateStartRequest(TranslateConfig):
    """Khởi chạy full pipeline 5 stage."""
    pass


class TranslateStageRequest(TranslateConfig):
    """Chạy chỉ 1 stage cụ thể (debug)."""
    stage: Literal["bible", "scenes", "speaker", "translate", "polish"]


class RetranslateRequest(BaseModel):
    """Dịch lại 1 dòng cụ thể."""
    subtitle_id:   int
    hint:          str = ""
    api_key:       str
    provider:      Literal["gemini", "openai", "deepseek"] = "gemini"
    model:         str = "gemini-2.5-flash"
    variants:      int = 1


class BibleOut(BaseModel):
    """Bible content cho FE."""
    id:               int
    version:          int
    is_active:        bool
    cast:             dict
    world:            dict
    glossary:         dict
    genre_pack_id:    Optional[str] = None
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
    is_hook:            bool = False
    is_emotion_peak:    bool = False
    status:             str = "pending"
    error_message:      Optional[str] = None
    line_count:         int = 0


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
    scene_count:      int = 0
    speaker_assigned_count: int = 0
    translated_count: int = 0
    review_count:     int = 0
    avg_cps:          float = 0.0
    cost_usd:         float = 0.0
    tokens_in:        int = 0
    tokens_out:       int = 0
    error_message:    Optional[str] = None


class GenrePackInfo(BaseModel):
    id:          str
    name_vi:     str
    name_zh:     str
    description: str