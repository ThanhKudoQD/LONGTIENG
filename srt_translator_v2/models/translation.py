"""
Translation models — v3.

Thay đổi so với v2:
- Mỗi dòng có 2 bản dịch: text_v1 (sát nghĩa) + text_v2 (thoát ý)
- text_v2 có thể null nếu AI không tạo variant (dòng quá ngắn / không quan trọng)
- variant_selected: 1 hoặc 2 (user chọn bản nào dùng cho TTS/export)
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field
from .scene import normalize_emotion


# ─────────────────────────────────────────────────────────────────
# SUBTITLE LINE (1 dòng phụ đề đã xử lý)
# ─────────────────────────────────────────────────────────────────

class SubtitleLine(BaseModel):
    """1 dòng phụ đề trong pipeline (in-memory)."""
    index: int                                # line_index
    start_time_sec: float = 0.0
    end_time_sec: float = 0.0
    text_zh: str = ""                         # Gốc tiếng Trung

    # Translation — 2 bản
    text_v1: Optional[str] = None             # Sát nghĩa
    text_v2: Optional[str] = None             # Thoát ý (nullable)
    variant_selected: int = 1                 # 1 hoặc 2

    # Speaker
    speaker_zh: Optional[str] = None
    speaker_vi: Optional[str] = None
    speaker_confidence: str = "low"           # h/m/l (high/mid/low)
    speaker_reason: str = ""

    # Emotion
    emotion: Optional[str] = None
    intensity: int = 5

    # Reference
    chunk_index: Optional[int] = None
    scene_index: Optional[int] = None
    arc_index: Optional[int] = None

    # Flags
    is_hook: bool = False
    is_emotion_peak: bool = False
    needs_review: bool = False
    review_reason: str = ""

    # CPS (computed sau translate)
    cps_value: Optional[float] = None

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time_sec - self.start_time_sec)

    @property
    def text_active(self) -> str:
        """Bản dịch đang dùng (theo variant_selected)."""
        if self.variant_selected == 2 and self.text_v2:
            return self.text_v2
        return self.text_v1 or ""

    @property
    def has_chinese(self) -> bool:
        """Còn ký tự tiếng Trung trong bản dịch active không."""
        import re
        text = self.text_active
        if not text:
            return False
        return bool(re.search(r'[\u4e00-\u9fff]', text))


# ─────────────────────────────────────────────────────────────────
# TRANSLATION RESULT (kết quả cuối)
# ─────────────────────────────────────────────────────────────────

class TranslationResult(BaseModel):
    """Kết quả pipeline."""
    lines: list[SubtitleLine] = Field(default_factory=list)
    total_lines: int = 0
    translated_count: int = 0                 # Số dòng có text_v1
    variants_count: int = 0                   # Số dòng có cả text_v2
    avg_cps: float = 0.0
    lines_needing_review: int = 0


# ─────────────────────────────────────────────────────────────────
# REVIEW ISSUE
# ─────────────────────────────────────────────────────────────────

class ReviewIssue(BaseModel):
    """1 issue cần user review (chỉ dùng cho Bước 5 retry)."""
    line_index: int
    issue_type: str = "untranslated"          # untranslated/empty/chinese_remains
    current_text: str = ""
    suggested_text: Optional[str] = None
    reason: str = ""


class PolishReport(BaseModel):
    """Kết quả Bước 5 (chỉ retry-based)."""
    issues: list[ReviewIssue] = Field(default_factory=list)
    retried_count: int = 0                    # Số dòng đã retry
    fixed_count: int = 0                      # Số dòng retry thành công
    still_problematic: int = 0                # Vẫn còn vấn đề sau retry
    summary: str = ""
