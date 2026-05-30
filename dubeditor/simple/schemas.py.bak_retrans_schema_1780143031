"""
Pydantic schemas cho Simple Translator API.

Convention naming:
  *In   — request body (FE → BE)
  *Out  — response body (BE → FE)

Schemas match 1-1 với types.ts ở FE để tránh sai lệch.
"""
from typing import Optional, Literal, Any
from datetime import datetime
from pydantic import BaseModel, Field

# ─── Common ──────────────────────────────────────────────────────────────────

RunStatus = Literal['idle', 'running', 'done', 'error']
BibleMode = Literal['single', 'multi']
ConcurrencyMode = Literal['normal', 'turbo']
ErrorType = Literal[
    'json_parse', 'missing_id', 'extra_id', 'invalid_speaker',
    'chinese_remained', 'cps_exceeded', 'empty', 'unnatural_pronoun',
]
ErrorSeverity = Literal['critical', 'error', 'warning']
ReviewSubMode = Literal['repair', 'qa']
IssueStatus = Literal['pending', 'fixed', 'still_broken', 'manual_resolved']


# ─── BIBLE ───────────────────────────────────────────────────────────────────

class BiblePartOut(BaseModel):
    """1 part của Bible — tương ứng SimpleBiblePart."""
    index: int                 # part_index
    total: int                 # tổng số parts của project
    start_line: int
    end_line: int
    est_tokens: int
    prompt: str
    response: Optional[str] = None
    status: RunStatus
    saved_at: Optional[datetime] = None
    characters_count: Optional[int] = None
    error_msg: Optional[str] = None


class BibleMergeOut(BaseModel):
    prompt: str
    response: Optional[str] = None
    status: RunStatus
    saved_at: Optional[datetime] = None
    error_msg: Optional[str] = None


class BibleStateOut(BaseModel):
    """Trạng thái toàn bộ Bible — endpoint GET /simple/bible."""
    mode: BibleMode
    parts: list[BiblePartOut]
    merge: Optional[BibleMergeOut] = None    # null nếu mode=single
    master_bible_json: Optional[Any] = None  # parsed JSON object
    master_characters_count: int = 0
    master_glossary_count: int = 0


class BibleModeIn(BaseModel):
    """POST /simple/bible/mode — đổi single/multi.

    Khi đổi mode, BE sẽ:
      - Xóa parts cũ (cascade delete) + reset merge
      - Tạo parts mới theo mode:
          single → 1 part chứa toàn bộ SRT
          multi  → N parts ~1000 dòng, cắt tại gap ≥ 3s
      - Trả về BibleStateOut mới
    """
    mode: BibleMode
    # Optional: số parts cho multi mode. Null = auto tính từ len(SRT) / 1000.
    multi_parts_count: Optional[int] = None


class SaveResponseIn(BaseModel):
    """Body cho mọi endpoint /save (manual paste).

    Dùng cho:
      POST /simple/bible/{idx}/save
      POST /simple/bible/merge/save
      POST /simple/batches/{idx}/save
      POST /simple/review/{idx}/save
    """
    response: str


# ─── TRANSLATE BATCH ─────────────────────────────────────────────────────────

class BatchOut(BaseModel):
    index: int
    total: int
    start_line: int
    end_line: int
    line_count: int
    characters_in_batch: int
    est_tokens_cached: int
    est_tokens_variable: int
    prompt: str
    response: Optional[str] = None
    status: RunStatus
    saved_at: Optional[datetime] = None
    error_msg: Optional[str] = None
    unknown_ratio: Optional[float] = None    # 0-100


class TranslateConfigOut(BaseModel):
    batch_size_target: int
    batch_size_max: int
    gap_threshold_seconds: float
    concurrency_mode: ConcurrencyMode
    turbo_concurrency: int
    previous_context_lines: int


class TranslateStateOut(BaseModel):
    config: TranslateConfigOut
    batches: list[BatchOut]
    active_batch_index: int
    total_translated: int
    total_pending: int
    cost_so_far_usd: float


class BatchConfigIn(BaseModel):
    """POST /simple/batches/config — đổi cấu hình + rebuild batches."""
    batch_size_target: Optional[int] = None
    batch_size_max: Optional[int] = None
    gap_threshold_seconds: Optional[float] = None
    concurrency_mode: Optional[ConcurrencyMode] = None
    turbo_concurrency: Optional[int] = None
    previous_context_lines: Optional[int] = None
    rebuild: bool = False   # nếu True và batches đã có data, sẽ xóa + tạo lại


class RunFromIn(BaseModel):
    """POST /simple/batches/run-from/{idx}."""
    only_idle: bool = True  # chỉ chạy các batch status=idle (không re-run done)


# ─── FILTER (Bước III) ───────────────────────────────────────────────────────

class FilterStatsOut(BaseModel):
    json_parse: int = 0
    missing_id: int = 0
    extra_id: int = 0
    invalid_speaker: int = 0
    chinese_remained: int = 0
    cps_exceeded: int = 0
    empty: int = 0
    unknown_ratio_percent: float = 0.0
    total_errors: int = 0
    auto_fixed: int = 0
    last_scan_at: Optional[datetime] = None


class SubtitleErrorOut(BaseModel):
    """1 lỗi phát hiện ở Bước III. Tương ứng SimpleIssue (status=pending)."""
    id: int
    subtitle_index: int
    batch_index: int
    error_types: list[ErrorType]
    severity: ErrorSeverity
    zh: str
    current_speaker: Optional[str] = None
    current_vi: Optional[str] = None
    cps_value: Optional[float] = None
    auto_fixable: bool = False
    needs_ai: bool = True
    detected_at: datetime


class FilterScanOut(BaseModel):
    """Response của POST /simple/filter/scan."""
    stats: FilterStatsOut
    errors: list[SubtitleErrorOut]
    auto_fixed_count: int = 0


# ─── REVIEW (Bước IV) ────────────────────────────────────────────────────────

class ContextLineOut(BaseModel):
    id: int           # subtitle.index
    speaker: str
    vi: str


class ReviewGroupOut(BaseModel):
    index: int
    total: int
    range_start: int
    range_end: int
    errors: list[SubtitleErrorOut]
    context_before: list[ContextLineOut]
    context_after: list[ContextLineOut]
    context_size_before: int
    context_size_after: int
    prompt: str
    response: Optional[str] = None
    status: RunStatus
    saved_at: Optional[datetime] = None
    est_tokens: int


class ReviewStateOut(BaseModel):
    sub_mode: ReviewSubMode
    groups: list[ReviewGroupOut]
    max_retries: int


class ReviewSubModeIn(BaseModel):
    sub_mode: ReviewSubMode


# ─── ISSUES (Tab V) ──────────────────────────────────────────────────────────

class IssueAttemptOut(BaseModel):
    attempt: int
    text: str
    speaker: str
    cps_value: Optional[float] = None
    passed: bool
    timestamp: datetime


class SubtitleIssueOut(BaseModel):
    id: int
    subtitle_id: int
    subtitle_index: int
    error_types: list[ErrorType]
    severity: ErrorSeverity
    zh: str
    text_before: Optional[str] = None
    speaker_before: Optional[str] = None
    text_after: Optional[str] = None
    speaker_after: Optional[str] = None
    attempts: list[IssueAttemptOut]
    fix_attempt: int
    status: IssueStatus
    needs_human_review: bool
    batch_index: int
    detected_at: datetime
    resolved_at: Optional[datetime] = None


class IssuesStatsOut(BaseModel):
    total: int = 0
    pending: int = 0
    fixed: int = 0
    still_broken: int = 0
    manual_resolved: int = 0
    total_cost_usd: float = 0.0


class IssuesListOut(BaseModel):
    """Response GET /simple/issues."""
    stats: IssuesStatsOut
    issues: list[SubtitleIssueOut]


class ManualEditIn(BaseModel):
    """POST /simple/issues/{id}/manual-edit."""
    text: str
    speaker: Optional[str] = None


# ─── CONFIG (mỗi project có 1 config riêng) ──────────────────────────────────

class TaskModelConfig(BaseModel):
    provider: Literal['gemini', 'openai', 'deepseek']
    model: str
    thinking: bool = False


class ProviderApiKeys(BaseModel):
    gemini: str = ""
    openai: str = ""
    deepseek: str = ""


class SimpleConfigSchema(BaseModel):
    """Config cho 1 project. Lưu trong AppSetting (key='simple_config:{pid}')
    hoặc trong LocalStorage FE (hiện tại FE đang dùng localStorage)."""
    api_keys: ProviderApiKeys
    tasks: dict[Literal['bible', 'translate', 'qa'], TaskModelConfig]
    batch_size_target: int = 100
    batch_size_max: int = 120
    gap_threshold_seconds: float = 3.0
    previous_context_lines: int = 15
    concurrency_mode: ConcurrencyMode = 'normal'
    turbo_concurrency: int = 5
    cps_max: float = 22.0
    cps_max_chars_fallback: int = 50
    unknown_ratio_warn_percent: float = 15.0
    group_max_distance_lines: int = 50
    group_max_errors: int = 30
    prompt_max_groups: int = 3
    max_retries: int = 2
    context_speaker_errors: int = 8
    context_chinese_leak: int = 3
    context_cps_exceeded: int = 3
    context_empty: int = 5
    context_default: int = 5
    # ─── AI Review (Bước IV) ─────────────────────────────────────────────
    review_batch_size: int = 80          # số sub mỗi review batch
    review_context_lines: int = 8        # context trước/sau cho prompt review


# ─── Generic response ────────────────────────────────────────────────────────

class OkOut(BaseModel):
    ok: bool = True
    message: Optional[str] = None
