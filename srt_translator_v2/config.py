"""
Cấu hình toàn cục cho pipeline v3.

Thay đổi so với v2:
- Bỏ Genre Pack (gộp vào Glossary của Bible)
- Thêm ChunkConfig (size chunk + overlap)
- Thêm VariantConfig (2 bản dịch)
- Thêm CacheConfig được dùng thực sự (cached_prefix)
- combine_b2_b3 cho phim ngắn

CPS cho lồng tiếng:
- TTS VoxCPM có thể chỉnh speed → CPS cao hơn subtitle thường được
- Câu KHÔNG được < 1s (TTS lỗi giọng)
- Câu rút phải ≥ 4-5 âm tiết
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional


# ─────────────────────────────────────────────────────────────────
# CPS & DURATION (cho lồng tiếng)
# ─────────────────────────────────────────────────────────────────

@dataclass
class CPSConfig:
    """Characters per second cho TTS lồng tiếng."""
    target: float = 17.0           # Mức lý tưởng
    max: float = 22.0              # Ngưỡng tối đa OK
    condense_threshold: float = 22.0  # Vượt mức này mới rút (Bước 5 retry)
    emergency_max: float = 28.0    # Sau retry vẫn vượt → flag review
    min_duration: float = 1.0      # KHÔNG tạo câu dịch cho dòng < 1s
    min_syllables: int = 4         # Câu rút phải ≥ 4 âm tiết


@dataclass
class DurationConfig:
    """Match độ dài câu Việt với câu Trung."""
    match_source: bool = True
    tolerance_pct: float = 40.0    # ±40%
    zh_to_vi_ratio: float = 3.0


# ─────────────────────────────────────────────────────────────────
# MODEL SELECTION
# ─────────────────────────────────────────────────────────────────

ModelTier = Literal["heavy", "medium", "light"]

@dataclass
class ModelConfig:
    """Phân tầng model + toggle thinking cho từng stage.

    v3.5: Thêm fields per-stage để frontend chọn model độc lập từng stage.
    Backward compat: nếu field per-stage rỗng → fallback về heavy/medium/light cũ.

    Mỗi stage có 1 cặp (model, thinking):
      thinking=False (mặc định): tắt thinking → nhanh + rẻ, hợp task JSON đơn giản
      thinking=True            : bật thinking dynamic → chậm + tốn hơn nhưng chất lượng cao

    Default: chỉ Stage 4 Translate bật thinking (đây là task khó nhất).
    Các stage còn lại tắt vì chỉ là extract/parse JSON.
    """
    # ── Legacy tier (vẫn giữ để run.py CLI + backward compat) ──────────
    heavy: str = "gemini-2.5-pro"
    heavy_thinking: bool = True

    medium: str = "gemini-2.5-flash"
    medium_thinking: bool = False

    light: str = "gemini-2.5-flash"
    light_thinking: bool = False

    translate_thinking: bool = True

    # ── v3.5: Per-stage model — frontend ConfigPanel set ──────────────
    # Nếu rỗng ("") → resolve về tier tương ứng bên trên (heavy/medium/light)
    # Helpers `get_model_for(stage)` + `get_thinking_for(stage)` bên dưới
    # sẽ tự fallback nên các stage runner không cần biết về fields này.
    model_stage0:       str = ""   # Chuẩn hóa phụ đề          (fallback: light)
    model_stage1:       str = ""   # Bible LEGACY combined     (fallback: heavy) — vẫn giữ cho backward compat
    model_stage1a:      str = ""   # Bible 1A LEGACY (cast+glossary gộp) (fallback: stage1 → heavy)
    # v3.14: TÁCH stage1a thành 2 sub-stage để gán model riêng:
    # - 1A.1 Cast: cần model heavy (Hán Việt chuẩn, output dài, risk loop)
    # - 1A.2 Glossary: model nhẹ OK (output ngắn, ít risk)
    model_stage1a_cast:     str = ""   # 1A.1 Cast    (fallback: stage1a → stage1 → heavy)
    model_stage1a_glossary: str = ""   # 1A.2 Glossary (fallback: stage1a → stage1 → heavy)
    model_stage1b:      str = ""   # Bible 1B World + Arcs     (fallback: stage1 → heavy)
    model_stage2:       str = ""   # Chunks + Scenes           (fallback: medium)
    model_stage3:       str = ""   # Speaker                   (fallback: medium)
    model_stage4:       str = ""   # Translate (task chính)    (fallback: heavy)
    model_stage5:       str = ""   # Retry dòng thiếu          (fallback: light)
    model_retranslate:  str = ""   # Retranslate trong editor  (fallback: heavy)

    # Thinking per-stage — None = dùng default tier
    thinking_stage0:       Optional[bool] = None
    thinking_stage1:       Optional[bool] = None
    thinking_stage1a:      Optional[bool] = None
    # v3.14: TÁCH stage1a thinking riêng cho cast/glossary
    thinking_stage1a_cast:     Optional[bool] = None
    thinking_stage1a_glossary: Optional[bool] = None
    thinking_stage1b:      Optional[bool] = None
    thinking_stage2:       Optional[bool] = None
    thinking_stage3:       Optional[bool] = None
    thinking_stage4:       Optional[bool] = None
    thinking_stage5:       Optional[bool] = None
    thinking_retranslate:  Optional[bool] = None

    # ── Resolvers ─────────────────────────────────────────────────────
    def get_model_for(self, stage: str) -> str:
        """Trả model cho stage: 'stage0'..'stage5'|'stage1a'|'stage1a_cast'|'stage1a_glossary'|'stage1b'|'retranslate'.

        Per-stage field rỗng → fallback tier mặc định.
        Stage1a_cast/glossary rỗng → fallback về stage1a → stage1 → heavy.
        Stage1a/1b rỗng → fallback về stage1 (legacy) → fallback heavy.
        """
        # v3.14: stage1a_cast / stage1a_glossary → stage1a → stage1 → heavy
        if stage == "stage1a_cast":
            v = self.model_stage1a_cast
            if v and v.strip():
                return v.strip()
            stage = "stage1a"  # fallback chain
        elif stage == "stage1a_glossary":
            v = self.model_stage1a_glossary
            if v and v.strip():
                return v.strip()
            stage = "stage1a"  # fallback chain

        # 1a/1b: nếu có giá trị riêng dùng nó, nếu không fallback về stage1
        if stage == "stage1a":
            v = self.model_stage1a
            if v and v.strip():
                return v.strip()
            stage = "stage1"  # fallback chain
        elif stage == "stage1b":
            v = self.model_stage1b
            if v and v.strip():
                return v.strip()
            stage = "stage1"  # fallback chain

        per_stage = {
            "stage0":      (self.model_stage0,      self.light),
            "stage1":      (self.model_stage1,      self.heavy),
            "stage2":      (self.model_stage2,      self.medium),
            "stage3":      (self.model_stage3,      self.medium),
            "stage4":      (self.model_stage4,      self.heavy),
            "stage5":      (self.model_stage5,      self.light),
            "retranslate": (self.model_retranslate, self.heavy),
        }
        if stage not in per_stage:
            return self.heavy  # safety
        v, fallback = per_stage[stage]
        return v.strip() if v and v.strip() else fallback

    def get_thinking_for(self, stage: str) -> bool:
        """Trả thinking flag cho stage. None → fallback tier mặc định.

        Stage1a_cast/glossary None → fallback về stage1a → stage1 → heavy_thinking.
        Stage1a/1b None → fallback về stage1 → fallback heavy_thinking.
        """
        # v3.14: stage1a_cast / stage1a_glossary fallback chain
        if stage == "stage1a_cast":
            if self.thinking_stage1a_cast is not None:
                return bool(self.thinking_stage1a_cast)
            stage = "stage1a"
        elif stage == "stage1a_glossary":
            if self.thinking_stage1a_glossary is not None:
                return bool(self.thinking_stage1a_glossary)
            stage = "stage1a"

        if stage == "stage1a":
            if self.thinking_stage1a is not None:
                return bool(self.thinking_stage1a)
            stage = "stage1"
        elif stage == "stage1b":
            if self.thinking_stage1b is not None:
                return bool(self.thinking_stage1b)
            stage = "stage1"

        per_stage = {
            "stage0":      (self.thinking_stage0,      self.light_thinking),
            "stage1":      (self.thinking_stage1,      self.heavy_thinking),
            "stage2":      (self.thinking_stage2,      self.medium_thinking),
            "stage3":      (self.thinking_stage3,      self.medium_thinking),
            "stage4":      (self.thinking_stage4,      self.translate_thinking),
            "stage5":      (self.thinking_stage5,      self.light_thinking),
            "retranslate": (self.thinking_retranslate, self.translate_thinking),
        }
        if stage not in per_stage:
            return self.translate_thinking
        v, fallback = per_stage[stage]
        return bool(fallback) if v is None else bool(v)


# ─────────────────────────────────────────────────────────────────
# CACHING (cached_prefix dùng cho Bước 4)
# ─────────────────────────────────────────────────────────────────

@dataclass
class CacheConfig:
    """Prompt caching cho Bước 4 Translate."""
    enabled: bool = True
    min_tokens_to_cache: int = 1024   # Phần cached_prefix phải > 1K mới đáng cache
    ttl_seconds: int = 3600           # 1 giờ cho Gemini explicit cache


# ─────────────────────────────────────────────────────────────────
# CHUNK STRATEGY (mới v3)
# ─────────────────────────────────────────────────────────────────

@dataclass
class ChunkConfig:
    """Cấu hình chia chunks ở Bước 2."""
    target_lines: int = 300                   # Target ~250-400 dòng/chunk
    min_lines: int = 100                      # Chunk ≤ này thì không chia scenes
    max_lines: int = 500                      # Chunk vượt này → AI buộc chia nhỏ
    overlap_lines: int = 30                   # Sliding window overlap cho Bước 4
    max_chunks_per_arc: int = 8               # Max chunks/arc
    max_arcs: int = 8                         # Hard cap số arcs (Stage 1B) — tránh AI tạo quá nhiều arc nhỏ
    parallel: bool = False                    # True = chạy song song (nhanh, tốn token)
                                              # False = tuần tự (chậm hơn ~30%, cache hit Bible giảm 50-90% input cost)


@dataclass
class SpeakerConfig:
    """Cấu hình Bước 3 gán speaker."""
    context_window: int = 20                  # Số dòng context trước/sau chunk (read-only)
    carry_over_lines: int = 15                # Số dòng cuối chunk trước (đã gán speaker) gửi kèm chunk hiện tại
                                              # (chỉ hiệu quả khi chunks trong arc chạy tuần tự)


@dataclass
class Stage0Config:
    """Cấu hình Bước 0 chuẩn hóa phụ đề."""
    enabled: bool = True                      # Bật/tắt Stage 0
    model: Optional[str] = None               # None = dùng models.light
    context_window: int = 2                   # ±N dòng context quanh mỗi dòng nghi ngờ


# ─────────────────────────────────────────────────────────────────
# COMPACT MODE (phim ngắn)
# ─────────────────────────────────────────────────────────────────

@dataclass
class CompactModeConfig:
    """Mode cho phim ngắn — gộp một số bước để tiết kiệm calls."""
    enabled: bool = False                       # Auto-bật theo size
    auto_threshold_subs: int = 500              # < threshold → bật compact
    combine_b2_b3: bool = False                 # Gộp Bước 2+3 vào 1 call/arc


# ─────────────────────────────────────────────────────────────────
# VARIANT (2 bản dịch — mới v3)
# ─────────────────────────────────────────────────────────────────

@dataclass
class VariantConfig:
    """Cấu hình 2 bản dịch (v1 sát nghĩa, v2 thoát ý)."""
    mode: Literal["off", "important_only", "always"] = "important_only"
    # off: chỉ 1 bản (text_v1)
    # important_only: dòng quan trọng có 2 bản, dòng thường chỉ 1 bản
    # always: tất cả dòng có 2 bản (tốn token nhất)

    # Điều kiện coi dòng "quan trọng" (cho mode important_only)
    min_chars: int = 5                          # Bỏ dòng quá ngắn
    important_emotions: list[str] = field(default_factory=lambda: [
        "intimate", "angry", "shocked", "determined", "sad", "fearful"
    ])
    important_intensity_min: int = 7            # Intensity ≥ 7 coi quan trọng
    important_scenes: list[str] = field(default_factory=lambda: [
        "HOOK", "PEAK"
    ])


# ─────────────────────────────────────────────────────────────────
# CONCURRENCY
# ─────────────────────────────────────────────────────────────────

@dataclass
class ConcurrencyConfig:
    """Số call API song song tối đa."""
    bible: int = 3                  # Bible 3 sub-calls song song
    chunks: int = 5                 # Bước 2: 5 arcs song song
    speaker_arcs: int = 5           # Bước 3: số ARC chạy song song (chunks trong arc tuần tự để hit cache + carry over speaker)
    translate: int = 5              # Bước 4: 5 chunks song song
    polish: int = 5                 # Bước 5: retry
    retry_max: int = 3
    retry_backoff_sec: float = 2.0


# ─────────────────────────────────────────────────────────────────
# QUALITY GATES
# ─────────────────────────────────────────────────────────────────

@dataclass
class QualityConfig:
    """Ngưỡng chất lượng."""
    speaker_min_confidence: Literal["h", "m", "l"] = "m"
    emotion_peaks_review: bool = True


# ─────────────────────────────────────────────────────────────────
# PROJECT TYPE PRESETS
# ─────────────────────────────────────────────────────────────────

PROJECT_TYPES = {
    "short_drama": {
        "description": "Short drama TQ — gộp tập 2-4 phút thành 1 file",
        "cps_max": 22.0,
        "cps_condense_threshold": 22.0,
        "expected_chunks_per_arc": 3,
        "tts_friendly": True,
        "hook_enhancement": True,
    },
    "drama_series": {
        "description": "Drama truyền hình 40-45 phút/tập",
        "cps_max": 20.0,
        "cps_condense_threshold": 22.0,
        "expected_chunks_per_arc": 4,
        "tts_friendly": True,
        "hook_enhancement": False,
    },
    "movie": {
        "description": "Phim điện ảnh 90-120 phút",
        "cps_max": 20.0,
        "cps_condense_threshold": 22.0,
        "expected_chunks_per_arc": 3,
        "tts_friendly": False,
        "hook_enhancement": False,
    },
}


# ─────────────────────────────────────────────────────────────────
# MASTER CONFIG
# ─────────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """Cấu hình tổng cho 1 lần chạy pipeline v3."""
    project_type: str = "short_drama"
    target_language: str = "vi"
    source_language: str = "zh"

    cps: CPSConfig = field(default_factory=CPSConfig)
    duration: DurationConfig = field(default_factory=DurationConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    chunk: ChunkConfig = field(default_factory=ChunkConfig)
    speaker: SpeakerConfig = field(default_factory=SpeakerConfig)
    stage0: Stage0Config = field(default_factory=Stage0Config)
    compact: CompactModeConfig = field(default_factory=CompactModeConfig)
    variant: VariantConfig = field(default_factory=VariantConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)

    provider: Literal["gemini", "openai", "deepseek"] = "gemini"
    api_key: str = ""   # Legacy — dùng khi 3 key dưới rỗng (fallback)

    # v3.12: Per-provider keys — cho phép mix provider giữa các stage trong cùng 1 pipeline
    api_key_gemini:   str = ""
    api_key_openai:   str = ""
    api_key_deepseek: str = ""

    def get_api_key_for(self, model: str) -> str:
        """Pick đúng key theo provider detect từ model name.

        Fallback chain:
          model là gemini → api_key_gemini → api_key (nếu provider mặc định = gemini)
          model là openai → api_key_openai → api_key (nếu provider mặc định = openai)
          model là deepseek → api_key_deepseek → api_key (nếu provider mặc định = deepseek)
        """
        m = (model or "").strip().lower()
        if m.startswith("gemini"):
            return self.api_key_gemini or (self.api_key if self.provider == "gemini" else "")
        if m.startswith("deepseek"):
            return self.api_key_deepseek or (self.api_key if self.provider == "deepseek" else "")
        # GPT / o1 / o3 / chatgpt → openai
        return self.api_key_openai or (self.api_key if self.provider == "openai" else "")

    # Paths
    prompts_dir: Path = field(default_factory=lambda: Path(__file__).parent / "prompts" / "v3")

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
        """Tự động chỉnh chunk + compact mode theo số subs.

        - < 500 subs: bật compact (gộp B2+B3), chunk nhỏ
        - 500-1500: standard, chunk vừa
        - 1500-3000: chunk lớn hơn
        - > 3000: chunk lớn, concurrency cao hơn
        """
        if total_subs < self.compact.auto_threshold_subs:
            # Phim ngắn — bật compact
            self.compact.enabled = True
            self.compact.combine_b2_b3 = True
            self.chunk.target_lines = min(250, total_subs)
            self.chunk.overlap_lines = 20
        elif total_subs < 1500:
            self.compact.enabled = False
            self.chunk.target_lines = 250
            self.chunk.overlap_lines = 30
        elif total_subs < 3000:
            self.compact.enabled = False
            self.chunk.target_lines = 300
            self.chunk.overlap_lines = 40
        else:
            # Phim dài
            self.compact.enabled = False
            self.chunk.target_lines = 400
            self.chunk.overlap_lines = 50
            # Tăng concurrency để chạy nhanh hơn
            self.concurrency.translate = 7
            self.concurrency.speaker_arcs = 7
        return self


# ─────────────────────────────────────────────────────────────────
# DEFAULT INSTANCE
# ─────────────────────────────────────────────────────────────────

def default_config() -> PipelineConfig:
    """Cấu hình mặc định cho short drama."""
    cfg = PipelineConfig()
    cfg.apply_project_type()
    return cfg
