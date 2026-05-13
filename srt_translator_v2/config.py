"""
Cấu hình toàn cục cho pipeline.

Đặt mặc định cho Short Drama (TTS-ready):
- CPS tối đa 15 (Netflix là 17, nhưng short drama xem trên điện thoại nên chặt hơn)
- Câu dịch độ dài tương đương câu gốc (±20%) — để TTS đồng bộ
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


# ─────────────────────────────────────────────────────────────────
# CPS & DURATION
# ─────────────────────────────────────────────────────────────────

@dataclass
class CPSConfig:
    """Characters per second — kiểm soát tốc độ đọc phụ đề.

    Lưu ý: hệ thống này dịch cho TTS LỒNG TIẾNG, không phải subtitle để đọc.
    → CPS cho phép cao hơn chuẩn subtitle (Netflix ~17). TTS có thể chỉnh speed.
    """
    target: float = 17.0           # Mức lý tưởng (tự nhiên cho TTS)
    max: float = 22.0              # Ngưỡng "trên ngưỡng" — vẫn OK
    condense_threshold: float = 22.0  # Chỉ rút gọn khi VƯỢT mức này
    emergency_max: float = 28.0    # Sau rút gọn vẫn không đạt → flag review


@dataclass
class DurationConfig:
    """Đồng bộ độ dài câu Việt với câu Trung để TTS phát đúng nhịp.

    Tỉ lệ char ZH → char VI: ~2.5-3.5 (1 char ZH ≈ 1 syllable, mất nhiều
    thời gian phát âm; 1 char VI là 1 chữ cái Latin, nhanh hơn nhiều).
    """
    match_source: bool = True
    tolerance_pct: float = 40.0    # ±40% — rộng rãi cho dịch tròn ý
    zh_to_vi_ratio: float = 3.0    # Mặc định 3 char VI / 1 char ZH


# ─────────────────────────────────────────────────────────────────
# MODEL SELECTION
# ─────────────────────────────────────────────────────────────────

ModelTier = Literal["heavy", "medium", "light"]

@dataclass
class ModelConfig:
    """Phân tầng model theo độ phức tạp công việc."""
    heavy: str = "gemini-2.5-pro"      # Bible, Translate (cần đọc dài + sáng tạo)
    medium: str = "gemini-2.5-flash"   # Speaker, Scene detect, Consistency
    light: str = "gemini-2.5-flash"    # CPS condense (đơn giản)


# ─────────────────────────────────────────────────────────────────
# CACHING
# ─────────────────────────────────────────────────────────────────

@dataclass
class CacheConfig:
    """Prompt caching để tiết kiệm token."""
    enabled: bool = True
    min_tokens_to_cache: int = 1024  # Phần Bible phải > 1K token mới đáng cache
    ttl_seconds: int = 3600          # 1 giờ — Gemini explicit cache


# ─────────────────────────────────────────────────────────────────
# BATCH STRATEGY (v3 — giảm LLM calls)
# ─────────────────────────────────────────────────────────────────

@dataclass
class BatchConfig:
    """Cấu hình batch để gộp calls, giảm overhead.

    Mỗi stage có 1 "lines per call" target. Pipeline sẽ gộp các unit nhỏ
    (scene, hoặc chunk) cho đến khi đạt target hoặc tới boundary tự nhiên.
    """
    # Speaker: gom N dòng liên tiếp vào 1 call (bỏ scene boundary)
    # Càng to càng tiết kiệm, nhưng prompt to → LLM dễ nhầm. ~80-100 là sweet spot.
    speaker_lines_per_call: int = 80

    # Translate: gom scenes thành arc-batches. Mỗi call ~N dòng MAX.
    # Vẫn giữ scene info trong prompt (LLM track pronoun/emotion theo scene).
    translate_lines_per_call: int = 60

    # Polish: gom chunks lớn hơn (CPS check + glossary check)
    polish_lines_per_call: int = 80


@dataclass
class CompactModeConfig:
    """Mode compact cho phim ngắn (<200 subs).

    Khi bật:
      - Scene detect: ép max 5 scenes
      - Speaker + Translate: thường 1 call duy nhất
      - Polish: gộp 3 sub-stage thành 1 call/sub-stage
    """
    enabled: bool = False                   # Auto-bật theo size
    auto_threshold_subs: int = 200          # < threshold → bật compact
    max_scenes: int = 5                     # Ép tối đa 5 scenes


@dataclass
class ConcurrencyConfig:
    """Số call API song song tối đa cho mỗi stage."""
    speaker: int = 5      # Stage 3
    translate: int = 5    # Stage 4
    polish: int = 3       # Stage 5
    retry_max: int = 3
    retry_backoff_sec: float = 2.0


# ─────────────────────────────────────────────────────────────────
# QUALITY GATES
# ─────────────────────────────────────────────────────────────────

@dataclass
class QualityConfig:
    """Ngưỡng chất lượng để flag review."""
    speaker_min_confidence: Literal["high", "mid", "low"] = "mid"
    emotion_peaks_review: bool = True   # Cảnh emotion peak luôn review
    back_translation: bool = False      # Bật cho Phase 2


# ─────────────────────────────────────────────────────────────────
# PROJECT TYPE PRESETS
# ─────────────────────────────────────────────────────────────────

PROJECT_TYPES = {
    "short_drama": {
        "description": "Short drama TQ gộp 60 tập × 2 phút thành 1 file",
        # CPS cao hơn bình thường: TTS dub không phải subtitle đọc.
        # Người xem nghe lồng tiếng, không phải đọc — CPS lên 22-25 OK.
        # Chỉ rút gọn khi THỰC SỰ quá dài (CPS > 22).
        "cps_max": 22.0,
        "cps_condense_threshold": 22.0,  # Stage 5A chỉ rút khi vượt mức này
        "scene_avg_lines": 8,
        "expected_scenes": 200,
        "tts_friendly": True,
        "hook_enhancement": True,
    },
    "drama_series": {
        "description": "Drama truyền hình 40-45 phút/tập",
        "cps_max": 20.0,
        "cps_condense_threshold": 22.0,
        "scene_avg_lines": 30,
        "expected_scenes": 20,
        "tts_friendly": True,
        "hook_enhancement": False,
    },
    "movie": {
        "description": "Phim điện ảnh 90-120 phút",
        "cps_max": 20.0,
        "cps_condense_threshold": 22.0,
        "scene_avg_lines": 25,
        "expected_scenes": 50,
        "tts_friendly": False,
        "hook_enhancement": False,
    },
}


# ─────────────────────────────────────────────────────────────────
# MASTER CONFIG
# ─────────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """Cấu hình tổng cho 1 lần chạy pipeline."""
    project_type: str = "short_drama"
    target_language: str = "vi"
    source_language: str = "zh"

    cps: CPSConfig = field(default_factory=CPSConfig)
    duration: DurationConfig = field(default_factory=DurationConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)
    compact: CompactModeConfig = field(default_factory=CompactModeConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)

    provider: Literal["gemini", "openai", "deepseek"] = "gemini"
    api_key: str = ""

    # Genre — None = auto detect, hoặc chỉ định pack ID
    genre_pack: str | None = None

    # Paths
    prompts_dir: Path = field(default_factory=lambda: Path(__file__).parent / "prompts" / "v2")
    genre_packs_dir: Path = field(default_factory=lambda: Path(__file__).parent / "genre_packs")

    def apply_project_type(self):
        """Áp preset cho project_type đã chọn."""
        if self.project_type in PROJECT_TYPES:
            preset = PROJECT_TYPES[self.project_type]
            self.cps.max = preset["cps_max"]
            self.cps.condense_threshold = preset.get(
                "cps_condense_threshold", preset["cps_max"]
            )
        return self

    def auto_tune_for_size(self, total_subs: int):
        """Tự động chỉnh batch size + compact mode theo số subs.

        Nguyên tắc:
          - < 200 subs: compact mode — ít scenes, gom call tối đa nhưng < 50 lines/call
          - 200-800: medium batches (40-50 lines/call)
          - 800-2000: standard (50-70 lines/call) — như default
          - > 2000: large batches (70-90 lines/call) — phim dài 4h+

        Mục đích: số calls không scale tuyến tính theo size.
        Giữ batch ≤ 50 dòng để response JSON không bị truncate.
        """
        if total_subs < self.compact.auto_threshold_subs:
            # Compact mode cho phim ngắn / test
            self.compact.enabled = True
            # Giới hạn ≤ 40 dòng/call để response không truncate
            self.batch.speaker_lines_per_call = min(40, total_subs)
            self.batch.translate_lines_per_call = min(40, total_subs)
            self.batch.polish_lines_per_call = min(50, total_subs)
        elif total_subs < 800:
            self.compact.enabled = False
            self.batch.speaker_lines_per_call = 50
            self.batch.translate_lines_per_call = 40
            self.batch.polish_lines_per_call = 60
        elif total_subs < 2000:
            self.compact.enabled = False
            self.batch.speaker_lines_per_call = 60
            self.batch.translate_lines_per_call = 50
            self.batch.polish_lines_per_call = 80
        else:
            # Phim 4h+
            self.compact.enabled = False
            self.batch.speaker_lines_per_call = 80
            self.batch.translate_lines_per_call = 60
            self.batch.polish_lines_per_call = 100
        return self


# ─────────────────────────────────────────────────────────────────
# DEFAULT INSTANCE
# ─────────────────────────────────────────────────────────────────

def default_config() -> PipelineConfig:
    """Cấu hình mặc định cho short drama."""
    cfg = PipelineConfig()
    cfg.apply_project_type()
    return cfg