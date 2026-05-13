"""
Pydantic models cho Translation — output dịch.
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator

from models.scene import EmotionTag, normalize_emotion


ConfidenceLevel = Literal["high", "mid", "low"]


# Confidence: LLM hay trả "medium" thay vì "mid"
_CONFIDENCE_MAP = {
    "high": "high", "h": "high", "cao": "high",
    "mid": "mid", "medium": "mid", "med": "mid", "m": "mid", "trung bình": "mid",
    "low": "low", "l": "low", "thấp": "low",
    "unknown": "low", "none": "low", "?": "low", "": "low",
}


def normalize_confidence(v) -> str:
    if v is None:
        return "low"
    v = str(v).strip().lower()
    return _CONFIDENCE_MAP.get(v, "low")


class SubtitleLine(BaseModel):
    """1 dòng SRT đã xử lý."""
    index: int = Field(description="STT trong SRT, 1-based")

    # Timing
    start_time_sec: float
    end_time_sec: float

    # Văn bản
    text_zh: str = Field(description="Văn bản tiếng Trung gốc")
    text_vi: str = Field(default="", description="Bản dịch tiếng Việt")
    text_vi_draft: Optional[str] = Field(default=None, description="Bản nháp trước polish")

    # Speaker
    speaker_zh: Optional[str] = Field(default=None, description="Tên Trung của speaker, hoặc '?'")
    speaker_vi: Optional[str] = Field(default=None, description="Tên Việt của speaker")
    speaker_confidence: ConfidenceLevel = "low"
    speaker_reason: str = Field(default="", description="Lý do gán speaker (debug)")

    # Cảm xúc
    emotion: Optional[EmotionTag] = None
    intensity: int = Field(default=5, ge=1, le=10, description="Cường độ cảm xúc 1-10")

    # Liên kết scene
    scene_index: Optional[int] = None

    # CPS
    cps_value: Optional[float] = None
    needs_condense: bool = False
    condensed_from: Optional[str] = Field(default=None, description="Bản trước khi rút gọn")

    # Flags
    is_hook: bool = False
    needs_review: bool = False
    review_reason: str = ""

    @field_validator("emotion", mode="before")
    @classmethod
    def _norm_emotion(cls, v):
        # Cho phép None (chưa gán)
        if v is None or v == "":
            return None
        return normalize_emotion(v)

    @field_validator("speaker_confidence", mode="before")
    @classmethod
    def _norm_conf(cls, v):
        return normalize_confidence(v)

    @field_validator("intensity", mode="before")
    @classmethod
    def _clamp_intensity(cls, v):
        if v is None:
            return 5
        try:
            i = int(float(v))   # LLM hay trả "7" hoặc 7.0
        except (TypeError, ValueError):
            return 5
        return max(1, min(10, i))


class TranslationResult(BaseModel):
    """Kết quả cuối của 1 phim."""
    lines: list[SubtitleLine] = Field(default_factory=list)
    total_lines: int = 0
    avg_cps: float = 0.0
    lines_needing_review: int = 0

    def to_srt(self) -> str:
        """Render thành SRT chuẩn."""
        from core.srt_parser import format_time
        blocks = []
        for line in self.lines:
            blocks.append(
                f"{line.index}\n"
                f"{format_time(line.start_time_sec)} --> {format_time(line.end_time_sec)}\n"
                f"{line.text_vi}\n"
            )
        return "\n".join(blocks)


# ─────────────────────────────────────────────────────────────────
# Review issues (Polish output)
# ─────────────────────────────────────────────────────────────────

IssueType = Literal[
    "speaker",        # speaker gán sai
    "pronoun",        # xưng hô không đúng
    "consistency",    # không nhất quán xuyên phim
    "glossary",       # tên/thuật ngữ sai so với Bible
    "intensity",      # cường độ cảm xúc sai
    "literal",        # dịch literal
    "tts_unfriendly", # khó phát âm cho TTS
    "cps",            # vẫn vượt CPS sau condense
    "other",
]


class ReviewIssue(BaseModel):
    line_index: int
    issue_type: IssueType
    description: str
    current_text: str
    suggested_text: Optional[str] = None
    confidence: ConfidenceLevel = "mid"
    evidence: str = ""


class PolishReport(BaseModel):
    issues: list[ReviewIssue] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict, description="Đếm theo issue_type")
    overall_rating: Literal["excellent", "good", "needs_minor_fix", "needs_major_fix"] = "good"