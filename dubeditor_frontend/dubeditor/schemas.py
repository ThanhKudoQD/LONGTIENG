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

class CharacterCreate(CharacterBase):
    pass

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
    character_id: Optional[int] = None
    audio_offset: float = 0.0

class SubtitleCreate(SubtitleBase):
    pass

class SubtitleUpdate(BaseModel):
    start_time:   Optional[float] = None
    end_time:     Optional[float] = None
    text:         Optional[str]   = None
    character_id: Optional[int]   = None
    audio_offset: Optional[float] = None
    tts_done:     Optional[bool]  = None
    wav_duration: Optional[float] = None

class SubtitleOut(SubtitleBase):
    id:         int
    project_id: int
    audio_path:   Optional[str]   = None
    tts_done:     bool           = False
    wav_duration: Optional[float] = None
    character:  Optional[CharacterOut] = None
    class Config:
        from_attributes = True

class ProjectBase(BaseModel):
    name: str

class ProjectCreate(ProjectBase):
    pass

class ProjectOut(ProjectBase):
    id:             int
    video_path:     Optional[str]      = None
    video_name:     Optional[str]      = None
    duration:       float              = 0.0
    created_at:     Optional[datetime] = None
    subtitle_count: int                = 0
    tts_done_count: int                = 0
    class Config:
        from_attributes = True

class TTSRequest(BaseModel):
    subtitle_id: int

class BulkTTSRequest(BaseModel):
    subtitle_ids: list[int]

class BulkAssignRequest(BaseModel):
    subtitle_ids: list[int]
    character_id: int
