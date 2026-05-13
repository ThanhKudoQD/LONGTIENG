"""
Pydantic models cho Scene — phân cảnh kịch.

Khác với "shot" (cảnh quay), "scene" ở đây là đơn vị kịch bản:
1 địa điểm + 1 mốc thời gian + 1 nhóm nhân vật + 1 mục đích kịch.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


EmotionTag = Literal[
    "neutral",       # bình thường
    "happy",         # vui
    "sad",           # buồn
    "angry",         # giận
    "cold",          # lạnh nhạt
    "tense",         # căng thẳng
    "intimate",      # thân mật
    "fearful",       # sợ hãi
    "sarcastic",     # mỉa mai
    "shocked",       # sốc
    "determined",    # quyết tâm
    "regretful",     # hối hận
    "humorous",      # hài hước
    "threatening",   # đe dọa
]


# Map các biến thể LLM hay trả → emotion chuẩn.
# Bao gồm: synonyms tiếng Anh, gerund forms, lower/upper case, tiếng Việt.
_EMOTION_MAP = {
    # Chuẩn (case-insensitive)
    "neutral": "neutral", "happy": "happy", "sad": "sad", "angry": "angry",
    "cold": "cold", "tense": "tense", "intimate": "intimate", "fearful": "fearful",
    "sarcastic": "sarcastic", "shocked": "shocked", "determined": "determined",
    "regretful": "regretful", "humorous": "humorous", "threatening": "threatening",

    # Synonyms / variations tiếng Anh
    "calm": "neutral", "normal": "neutral", "casual": "neutral", "matter-of-fact": "neutral",
    "joyful": "happy", "cheerful": "happy", "excited": "happy", "delighted": "happy",
    "amused": "happy", "satisfied": "happy", "pleased": "happy", "content": "happy",
    "sorrowful": "sad", "depressed": "sad", "melancholy": "sad", "down": "sad",
    "heartbroken": "sad", "disappointed": "sad", "tearful": "sad", "grief": "sad",
    "mad": "angry", "furious": "angry", "irritated": "angry", "annoyed": "angry",
    "frustrated": "angry", "rage": "angry", "outraged": "angry", "indignant": "angry",
    "distant": "cold", "aloof": "cold", "detached": "cold", "indifferent": "cold",
    "icy": "cold", "stern": "cold",
    "anxious": "tense", "nervous": "tense", "stressed": "tense", "uneasy": "tense",
    "worried": "tense", "apprehensive": "tense",
    "loving": "intimate", "affectionate": "intimate", "tender": "intimate",
    "romantic": "intimate", "passionate": "intimate", "warm": "intimate",
    "afraid": "fearful", "scared": "fearful", "frightened": "fearful", "terrified": "fearful",
    "panic": "fearful", "panicked": "fearful",
    "mocking": "sarcastic", "ironic": "sarcastic", "snarky": "sarcastic", "scornful": "sarcastic",
    "contemptuous": "sarcastic", "derisive": "sarcastic",
    "surprised": "shocked", "astonished": "shocked", "stunned": "shocked",
    "amazed": "shocked", "shock": "shocked",
    "resolute": "determined", "firm": "determined", "decisive": "determined",
    "confident": "determined", "assertive": "determined",
    "remorseful": "regretful", "apologetic": "regretful", "guilty": "regretful",
    "ashamed": "regretful", "rueful": "regretful",
    "funny": "humorous", "playful": "humorous", "teasing": "humorous", "witty": "humorous",
    "menacing": "threatening", "intimidating": "threatening", "ominous": "threatening",
    "warning": "threatening", "hostile": "threatening",

    # Map "không nằm trong enum" → emotion gần nhất theo nghĩa
    "innocent": "neutral",       # vô tư / ngây thơ → tone bình thường
    "confused": "tense",         # bối rối → căng thẳng
    "shy": "intimate",           # ngại → thân mật nhẹ
    "embarrassed": "intimate",   # ngượng → thân mật
    "hopeful": "happy",
    "hopeless": "sad",
    "lonely": "sad",
    "bored": "neutral",
    "curious": "neutral",
    "thoughtful": "neutral",
    "pensive": "neutral",
    "skeptical": "sarcastic",
    "suspicious": "tense",
    "jealous": "angry",
    "envious": "angry",
    "proud": "determined",
    "arrogant": "cold",
    "humble": "neutral",
    "grateful": "happy",
    "disgusted": "sarcastic",
    "tired": "neutral",
    "exhausted": "sad",
    "energetic": "happy",
    "longing": "intimate",
    "nostalgic": "regretful",
    "bitter": "regretful",
    "vengeful": "threatening",

    # Tiếng Việt — phòng trường hợp LLM trả tiếng Việt
    "bình thường": "neutral", "vui": "happy", "buồn": "sad", "giận": "angry",
    "lạnh nhạt": "cold", "căng thẳng": "tense", "thân mật": "intimate",
    "sợ": "fearful", "sợ hãi": "fearful", "mỉa mai": "sarcastic",
    "sốc": "shocked", "quyết tâm": "determined", "hối hận": "regretful",
    "hài hước": "humorous", "đe dọa": "threatening",
}


def normalize_emotion(v) -> Optional[str]:
    """Chuẩn hóa giá trị emotion từ LLM về enum chuẩn.

    Trả về None nếu input rỗng/None.
    Trả về 'neutral' nếu không match được tag nào (fallback an toàn).
    """
    if v is None:
        return None
    v = str(v).strip().lower()
    if not v:
        return None
    # Bỏ ký tự dư (vd: "angry!" → "angry")
    v_clean = v.rstrip(".,!?:;").strip()
    return _EMOTION_MAP.get(v_clean, "neutral")


class Scene(BaseModel):
    """1 phân cảnh kịch."""
    index: int = Field(description="Thứ tự trong phim, 0-based")

    # Ranh giới
    start_line: int = Field(description="Index dòng SRT bắt đầu (1-based)")
    end_line: int = Field(description="Index dòng SRT kết thúc (inclusive)")
    start_time_sec: float = Field(description="Thời gian bắt đầu")
    end_time_sec: float = Field(description="Thời gian kết thúc")

    # Bối cảnh
    location: str = Field(default="", description="vd: 'bệnh viện, đêm'")
    time_of_day: Optional[str] = Field(default=None, description="vd: 'đêm', 'sáng sớm'")

    # Nhân vật trong cảnh (zh names, để match Bible.cast)
    characters_present: list[str] = Field(
        default_factory=list,
        description="List tên Trung của nhân vật xuất hiện. Có thể có 'phụ_1', '?' cho chưa rõ"
    )

    # Cảm xúc
    emotion_primary: EmotionTag = "neutral"
    emotion_arc: str = Field(
        default="",
        description="Cảm xúc tiến triển trong cảnh, vd: 'bình thường → căng → bùng nổ'"
    )

    # Nội dung
    summary: str = Field(description="Tóm tắt 1 câu cảnh xảy ra cái gì")
    purpose: str = Field(
        default="",
        description="Mục đích kịch, vd: 'thiết lập xung đột giữa A và B'"
    )

    # Liên kết arc
    story_arc_index: Optional[int] = Field(default=None, description="Thuộc arc số mấy")

    # Flags
    is_hook: bool = Field(default=False, description="Cảnh cliffhanger / hook quan trọng")
    is_emotion_peak: bool = Field(default=False, description="Cảnh đỉnh cảm xúc — cần review tay")

    # Status (sau khi xử lý)
    speaker_done: bool = False
    translation_done: bool = False
    polish_done: bool = False

    @field_validator("emotion_primary", mode="before")
    @classmethod
    def _norm_emotion(cls, v):
        norm = normalize_emotion(v)
        return norm if norm else "neutral"


class SceneMap(BaseModel):
    """Tập hợp toàn bộ scene của 1 phim."""
    scenes: list[Scene] = Field(default_factory=list)
    total_lines: int = 0
    total_duration_sec: float = 0.0

    def get_scene_for_line(self, line_index: int) -> Optional[Scene]:
        """Tìm scene chứa 1 dòng SRT cụ thể."""
        for s in self.scenes:
            if s.start_line <= line_index <= s.end_line:
                return s
        return None