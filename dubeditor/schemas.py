from pydantic import BaseModel
from typing import Optional
from datetime import datetime

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

class CharacterOut(CharacterBase):
    id:         int
    project_id: int
    class Config:
        from_attributes = True

class SubtitleBase(BaseModel):
    index:        int
    start_time:   float
    end_time:     float
    text:         str = ""
    original_text: Optional[str] = None
    character_id: Optional[int] = None
    audio_offset: float = 0.0

class SubtitleCreate(SubtitleBase): pass

class SubtitleUpdate(BaseModel):
    start_time:    Optional[float] = None
    end_time:      Optional[float] = None
    text:          Optional[str]   = None
    original_text: Optional[str]   = None
    character_id:  Optional[int]   = None
    audio_offset:  Optional[float] = None
    tts_done:      Optional[bool]  = None
    wav_duration:  Optional[float] = None
    tts_speed:     Optional[float] = None

class SubtitleOut(SubtitleBase):
    id:            int
    project_id:    int
    audio_path:    Optional[str]   = None
    tts_done:      bool            = False
    wav_duration:  Optional[float] = None
    tts_speed:     Optional[float] = None
    character:     Optional[CharacterOut] = None
    class Config:
        from_attributes = True

class ProjectBase(BaseModel):
    name: str

class ProjectCreate(ProjectBase): pass

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
    has_bible:          bool               = False
    class Config:
        from_attributes = True

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

# ─── Translate schemas ────────────────────────────────────────────────────────

class TranslateAnalyzeRequest(BaseModel):
    api_key:     str
    model:       str = "gemini-2.5-flash"
    source_lang: str = "zh"

class TranslateRunRequest(BaseModel):
    api_key:     str
    model:       str  = "gemini-2.5-flash"
    concurrency: int  = 3
    enable_qc:   bool = False

class TranslateRunChunksRequest(BaseModel):
    """Dịch lại chỉ một số chunk cụ thể (theo chunk_index trong scene_map)."""
    api_key:        str
    model:          str       = "gemini-2.5-flash"
    concurrency:    int       = 3
    chunk_indices:  list[int] = []   # nếu rỗng → không làm gì

class RetranslateRequest(BaseModel):
    subtitle_id:   int
    original_text: str
    current_text:  str
    variants:      int = 2
    api_key:       str = ""
    model:         str = "gemini-2.5-flash"