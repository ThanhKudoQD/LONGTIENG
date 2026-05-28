"""
SQLAlchemy models cho Simple Translator.

4 bảng mới, tất cả gắn với Project:
  - SimpleBiblePart       (parts của Bible — single mode N=1, multi N≥2)
  - SimpleBibleMerge      (merge response cho multi mode — 1 row/project)
  - SimpleBatch           (batches dịch — ~100 dòng/batch)
  - SimpleReviewGroup     (groups repair — gom các errors gần nhau)
  - SimpleIssue           (lịch sử errors + attempts)

Cột bổ sung trên Subtitle (đã định nghĩa thẳng vào dubeditor/models.py):
  - simple_speaker_zh    (str, nullable)    Speaker từ pipeline mới
  - simple_text_vi       (text, nullable)   Bản dịch từ pipeline mới
  - simple_status        (str, default 'pending')   pending|translated|has_error|fixed
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, ForeignKey,
    DateTime, Text, Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from dubeditor.database import Base


# ─── Bible parts ─────────────────────────────────────────────────────────────

class SimpleBiblePart(Base):
    """1 part của Bible. Single mode → có 1 row; Multi mode → N rows."""
    __tablename__ = "simple_bible_parts"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    # 0-based index trong các parts của project. Single mode luôn = 0.
    part_index  = Column(Integer, nullable=False)
    # Range subtitle.index (1-based, inclusive).
    start_line  = Column(Integer, nullable=False)
    end_line    = Column(Integer, nullable=False)
    # Token ước tính của prompt (để FE hiển thị).
    est_tokens  = Column(Integer, default=0)
    # Prompt text (build sẵn từ template + SRT).
    prompt      = Column(Text, default="")
    # Response JSON từ LLM hoặc user paste. Nullable khi chưa chạy.
    response    = Column(Text, nullable=True)
    # idle|running|done|error
    status      = Column(String, default='idle', index=True)
    # Số nhân vật parse được từ response.c (dùng cho UI badge).
    characters_count = Column(Integer, default=0)
    # Error msg nếu status=error.
    error_msg   = Column(Text, nullable=True)
    # Cost tracking
    tokens_in   = Column(Integer, default=0)
    tokens_out  = Column(Integer, default=0)
    cost_usd    = Column(Float, default=0.0)
    model_used  = Column(String, nullable=True)
    # Timestamps
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    saved_at    = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_simple_bible_parts_proj_idx', 'project_id', 'part_index'),
    )


class SimpleBibleMerge(Base):
    """1 row/project (chỉ tồn tại khi mode=multi). Lưu merge response."""
    __tablename__ = "simple_bible_merges"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          unique=True, index=True, nullable=False)
    prompt      = Column(Text, default="")
    response    = Column(Text, nullable=True)
    status      = Column(String, default='idle')   # idle|running|done|error
    error_msg   = Column(Text, nullable=True)
    # Master Bible JSON sau khi parse response (= response nếu single mode).
    # Đây là Bible cuối cùng dùng cho pipeline (cache ở đây để khỏi parse mỗi lần).
    master_bible_json = Column(Text, nullable=True)
    master_characters_count = Column(Integer, default=0)
    master_glossary_count   = Column(Integer, default=0)
    # Cost
    tokens_in   = Column(Integer, default=0)
    tokens_out  = Column(Integer, default=0)
    cost_usd    = Column(Float, default=0.0)
    model_used  = Column(String, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    saved_at    = Column(DateTime(timezone=True), nullable=True)


# ─── Translate batches ───────────────────────────────────────────────────────

class SimpleBatch(Base):
    """1 batch dịch. Mặc định ~100 dòng, cắt tại gap ≥3s."""
    __tablename__ = "simple_batches"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    batch_index = Column(Integer, nullable=False)
    start_line  = Column(Integer, nullable=False)   # subtitle.index
    end_line    = Column(Integer, nullable=False)
    line_count  = Column(Integer, default=0)
    # Số nhân vật xuất hiện trong batch (detect bằng regex từ Bible).
    characters_in_batch = Column(Integer, default=0)
    # Tokens
    est_tokens_cached   = Column(Integer, default=0)  # phần cached prefix
    est_tokens_variable = Column(Integer, default=0)  # phần variable
    prompt      = Column(Text, default="")
    response    = Column(Text, nullable=True)
    status      = Column(String, default='idle', index=True)
    error_msg   = Column(Text, nullable=True)
    # Stats sau khi parse response
    unknown_ratio_percent = Column(Float, default=0.0)  # % dòng có speaker=UNKNOWN
    # Cost
    tokens_in   = Column(Integer, default=0)
    tokens_out  = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    cost_usd    = Column(Float, default=0.0)
    model_used  = Column(String, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    saved_at    = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_simple_batches_proj_idx', 'project_id', 'batch_index'),
    )


# ─── Review / Repair groups ──────────────────────────────────────────────────

class SimpleReviewGroup(Base):
    """1 group repair: gom các errors gần nhau (≤max_distance dòng)."""
    __tablename__ = "simple_review_groups"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    group_index = Column(Integer, nullable=False)
    sub_mode    = Column(String, default='repair')   # repair|qa
    # Range trong subtitle.index
    range_start = Column(Integer, nullable=False)
    range_end   = Column(Integer, nullable=False)
    # Context window sizes (adaptive theo loại lỗi đa số trong group)
    context_size_before = Column(Integer, default=5)
    context_size_after  = Column(Integer, default=5)
    # IDs của các SimpleIssue thuộc group này — JSON array of ints
    issue_ids_json = Column(Text, default="[]")
    prompt      = Column(Text, default="")
    response    = Column(Text, nullable=True)
    status      = Column(String, default='idle', index=True)
    error_msg   = Column(Text, nullable=True)
    est_tokens  = Column(Integer, default=0)
    # Cost
    tokens_in   = Column(Integer, default=0)
    tokens_out  = Column(Integer, default=0)
    cost_usd    = Column(Float, default=0.0)
    model_used  = Column(String, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at  = Column(DateTime(timezone=True), onupdate=func.now())
    saved_at    = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_simple_review_groups_proj_idx', 'project_id', 'group_index'),
    )


# ─── Issues (lịch sử lỗi) ────────────────────────────────────────────────────

class SimpleReviewSuggestion(Base):
    """1 đề xuất sửa từ AI review cho 1 sub. User apply từng cái hoặc tất cả."""
    __tablename__ = "simple_review_suggestions"

    id           = Column(Integer, primary_key=True, index=True)
    project_id   = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    group_index  = Column(Integer, nullable=False, index=True)
    subtitle_index = Column(Integer, nullable=False, index=True)
    zh           = Column(Text, default="")        # tiếng Trung gốc
    # Trước (hiện tại trong DB)
    vi_old       = Column(Text, default="")
    speaker_old  = Column(String, default="")
    # AI đề xuất
    vi_new       = Column(Text, default="")
    speaker_new  = Column(String, default="")
    reason       = Column(Text, default="")        # giải thích vì sao sửa
    # Loại thay đổi: text | speaker | both
    change_type  = Column(String, default="text")
    status       = Column(String, default="pending", index=True)  # pending|applied|dismissed
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('ix_simple_review_sugg_proj', 'project_id', 'status'),
    )


class SimpleIssue(Base):
    """1 dòng phụ đề có lỗi. Lưu cả lịch sử các lần fix (attempts)."""
    __tablename__ = "simple_issues"

    id          = Column(Integer, primary_key=True, index=True)
    project_id  = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    subtitle_id = Column(Integer, ForeignKey("subtitles.id", ondelete="CASCADE"),
                          index=True, nullable=False)
    subtitle_index = Column(Integer, nullable=False)
    batch_index = Column(Integer, default=0)
    # JSON array of error type strings
    error_types_json = Column(Text, default="[]")
    severity    = Column(String, default='error')   # critical|error|warning
    # Snapshot tại thời điểm detect
    zh                = Column(Text, default="")
    text_before       = Column(Text, nullable=True)   # bản dịch trước fix
    speaker_before    = Column(String, nullable=True)
    # Sau lần fix cuối (= bản đang dùng nếu status=fixed)
    text_after        = Column(Text, nullable=True)
    speaker_after     = Column(String, nullable=True)
    cps_value         = Column(Float, nullable=True)
    # JSON array các attempts: [{attempt, text, speaker, cps_value, passed, timestamp}, ...]
    attempts_json     = Column(Text, default="[]")
    fix_attempt       = Column(Integer, default=0)    # số lần đã thử
    status            = Column(String, default='pending', index=True)
    # pending|fixed|still_broken|manual_resolved
    needs_human_review = Column(Boolean, default=False)
    # Cost tổng cộng cho các lần fix issue này
    cost_usd_total    = Column(Float, default=0.0)
    # Timestamps
    detected_at       = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at       = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index('ix_simple_issues_proj_status', 'project_id', 'status'),
        Index('ix_simple_issues_proj_subid', 'project_id', 'subtitle_id'),
    )
