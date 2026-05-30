"""
Pydantic schemas cho Export Video config.
Match 1-1 với types.ts ở FE.
"""
from typing import Literal, Optional, List, Union
from pydantic import BaseModel, Field


# ─── Cắt ──────────────────────────────────────────────────────────────────────

class VideoClip(BaseModel):
    id: str
    source_start: float
    source_end: float
    label: Optional[str] = None


# ─── Phụ đề ───────────────────────────────────────────────────────────────────

class SubtitleStyle(BaseModel):
    enabled: bool = True
    font_family: str = 'Be Vietnam Pro'
    font_size: int = 32
    color: str = '#FFFFFF'
    outline_enabled: bool = True
    outline_color: str = '#000000'
    outline_width: float = 2.0
    position: Literal['top', 'middle', 'bottom'] = 'bottom'
    y_offset: int = 0
    bold: bool = True
    italic: bool = False
    background_enabled: bool = False
    background_color: str = '#000000'
    background_opacity: float = 0.5
    shadow_enabled: bool = False
    shadow_color: str = '#000000'
    shadow_blur: float = 4.0


# ─── Padding ──────────────────────────────────────────────────────────────────

class PaddingSide(BaseModel):
    enabled: bool = False
    height_px: int = 100
    color: str = '#000000'


class PaddingConfig(BaseModel):
    top:    PaddingSide = PaddingSide()
    bottom: PaddingSide = PaddingSide()


# ─── Watermark ────────────────────────────────────────────────────────────────

WatermarkPosition = Literal[
    'top_left', 'top_right', 'top_center',
    'bottom_left', 'bottom_right', 'bottom_center',
    'center',
]


class WatermarkText(BaseModel):
    id: str
    type: Literal['text'] = 'text'
    text: str
    font_family: str = 'Be Vietnam Pro'
    font_size: int = 24
    color: str = '#FFFFFF'
    opacity: float = 0.8
    position: WatermarkPosition = 'top_right'
    x_offset: int = 20
    y_offset: int = 20
    start_time: float = 0.0
    duration: Optional[float] = None  # None = suốt video


class WatermarkImage(BaseModel):
    id: str
    type: Literal['image'] = 'image'
    image_path: str  # relative path under uploads/ (BE-resolved)
    image_url: Optional[str] = None
    width_px: int = 120
    opacity: float = 0.8
    position: WatermarkPosition = 'bottom_right'
    x_offset: int = 20
    y_offset: int = 20
    start_time: float = 0.0
    duration: Optional[float] = None


Watermark = Union[WatermarkText, WatermarkImage]


# ─── Audio ────────────────────────────────────────────────────────────────────

class AudioTrack(BaseModel):
    id: str
    name: str
    file_path: str            # relative path (vd uploads/abc.mp3) — BE resolve absolute
    file_url: Optional[str] = None
    start_time: float = 0.0   # OUTPUT timeline time
    end_time: float = 60.0
    duration_orig: float = 60.0
    volume: float = 0.3
    fade_in: float = 1.0
    fade_out: float = 2.0
    loop: bool = False


class AudioConfig(BaseModel):
    voice_volume: float = 1.0
    voice_enabled: bool = True
    ducking_enabled: bool = False
    ducking_amount: float = 0.5
    tracks: List[AudioTrack] = Field(default_factory=list)


# ─── Output ───────────────────────────────────────────────────────────────────

OutputResolution = Literal['720p', '1080p', '1440p', '4k', 'custom']
OutputFormat     = Literal['mp4', 'mov', 'webm']
VideoCodec       = Literal['h264', 'h265', 'vp9']
AspectRatio      = Literal['16:9', '9:16', '4:3', '1:1', 'source', 'custom']
FitMode          = Literal['letterbox', 'crop', 'pad_color']


class OutputConfig(BaseModel):
    format: OutputFormat = 'mp4'
    resolution: OutputResolution = '1080p'
    custom_width: Optional[int] = None
    custom_height: Optional[int] = None
    fps: int = 30
    video_codec: VideoCodec = 'h264'
    video_bitrate: str = '5M'
    audio_bitrate: str = '192k'
    preset: Literal['ultrafast', 'fast', 'medium', 'slow'] = 'medium'
    aspect_ratio: AspectRatio = 'source'
    custom_aspect_w: Optional[int] = None
    custom_aspect_h: Optional[int] = None
    fit_mode: FitMode = 'letterbox'
    use_gpu: bool = True   # v4.0: dùng NVENC nếu có (auto fallback CPU nếu không)


# ─── Tổng hợp ─────────────────────────────────────────────────────────────────

class ExportConfig(BaseModel):
    clips: List[VideoClip] = Field(default_factory=list)
    subtitle_style: SubtitleStyle = SubtitleStyle()
    padding: PaddingConfig = PaddingConfig()
    watermarks: List[Watermark] = Field(default_factory=list)
    audio: AudioConfig = AudioConfig()
    output: OutputConfig = OutputConfig()


# ─── Response models ──────────────────────────────────────────────────────────

class ExportJobOut(BaseModel):
    id: int
    project_id: int
    status: str
    progress: float
    config: ExportConfig
    output_url: Optional[str] = None
    output_size: int = 0
    error_msg: Optional[str] = None
    eta_sec: float = 0.0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    class Config:
        from_attributes = True


class ExportPresetOut(BaseModel):
    id: int
    name: str
    config: dict             # partial config — không validate strict
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class CreatePresetIn(BaseModel):
    name: str
    config: dict


class RunExportIn(BaseModel):
    config: ExportConfig
