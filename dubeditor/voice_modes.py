"""
Voice mode resolver — map emotion → mode bucket → reference audio.

5 mode buckets:
  - normal    (BT)    : neutral, cold, shocked nhẹ
  - happy     (Vui)   : happy, humorous
  - sad       (Buồn)  : sad, regretful, fearful nặng
  - angry     (Giận)  : angry, threatening, tense, sarcastic, determined, shocked mạnh
  - intimate  (Thân)  : intimate, fearful nhẹ
"""
from __future__ import annotations
import json
from typing import Optional


# Tên hiển thị tiếng Việt
MODE_LABELS = {
    "normal":   "Bình thường",
    "happy":    "Vui vẻ",
    "sad":      "Buồn",
    "angry":    "Tức giận",
    "intimate": "Nhẹ nhàng / Thân mật",
}

# Thứ tự render trong UI
MODE_ORDER = ["normal", "happy", "sad", "angry", "intimate"]


# ─────────────────────────────────────────────────────────────────
# EMOTION → BUCKET MAPPING
# ─────────────────────────────────────────────────────────────────
# Map 14 emotion code chuẩn → 5 mode bucket.
# Một số emotion phụ thuộc intensity → resolve riêng (xem resolve_mode_bucket)

_BASE_BUCKET: dict[str, str] = {
    # Direct mapping
    "neutral":     "normal",
    "cold":        "normal",     # lạnh nhưng vẫn neutral về tone

    "happy":       "happy",
    "humorous":    "happy",

    "sad":         "sad",
    "regretful":   "sad",
    "fearful":     "sad",        # sợ → buồn (default)

    "angry":       "angry",
    "threatening": "angry",
    "tense":       "angry",
    "sarcastic":   "angry",
    "determined":  "angry",

    "intimate":    "intimate",

    # Phụ thuộc intensity — set ở resolve_mode_bucket
    "shocked":     "normal",     # default; nếu intensity ≥ 8 → angry
}


def resolve_mode_bucket(emotion: Optional[str], intensity: int = 5) -> str:
    """Resolve emotion + intensity → mode bucket.

    Logic đặc biệt:
      - shocked intensity ≥ 8 → angry (giận quát)
      - fearful intensity ≤ 4 → intimate (sợ rụt rè, không khóc)
      - default → từ _BASE_BUCKET
    """
    e = (emotion or "").lower().strip()
    if not e:
        return "normal"
    i = intensity or 5

    # Edge cases theo intensity
    if e == "shocked" and i >= 8:
        return "angry"
    if e == "fearful" and i <= 4:
        return "intimate"

    return _BASE_BUCKET.get(e, "normal")


# ─────────────────────────────────────────────────────────────────
# VOICE MODES PARSER (lưu trong Role.voice_modes JSON)
# ─────────────────────────────────────────────────────────────────

def parse_voice_modes(raw: Optional[str]) -> dict:
    """Parse JSON string từ Role.voice_modes → dict.

    Format: {
      "normal":   {"audio": "/uploads/...", "text": "...", "duration": 3.5},
      "happy":    {...},
      ...
    }

    Trả {} nếu raw rỗng/invalid.
    """
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def dump_voice_modes(modes: dict) -> str:
    """dict → JSON string để lưu DB."""
    return json.dumps(modes or {}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────
# REF RESOLVER (logic chính cho TTS pipeline)
# ─────────────────────────────────────────────────────────────────

def resolve_ref_for_emotion(
    role,
    emotion: Optional[str] = None,
    intensity: int = 5,
    *,
    use_emotion_voice: bool = False,
    force_mode: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], str]:
    """Resolve audio path + transcript cho TTS dựa trên emotion.

    Args:
        role: Role object có voice_modes + audio + reference_audio_text
        emotion: emotion code của subtitle
        intensity: 1-10
        use_emotion_voice: flag từ Project.use_emotion_voice
            True → resolve theo voice_modes
            False → dùng role.audio (legacy)
        force_mode: nếu set → bỏ qua emotion+intensity, dùng thẳng mode này.
            Values: 'normal' | 'happy' | 'sad' | 'angry' | 'intimate' | None

    Logic khi use_emotion_voice=True:
      1. Nếu force_mode → bucket = force_mode (override)
      2. Nếu không → bucket = resolve_mode_bucket(emotion, intensity)
      3. Tìm voice_modes[bucket] → có thì dùng
      4. Không có → fallback voice_modes["normal"]
      5. Vẫn không có → fallback role.audio (legacy)

    Returns:
        (audio_path, transcript, mode_used)
        mode_used: "normal" / "happy" / ... / "legacy" / "missing"
    """
    # Toggle off → legacy mode
    if not use_emotion_voice:
        return (role.audio or None, role.reference_audio_text or None, "legacy")

    modes = parse_voice_modes(getattr(role, "voice_modes", None))

    # Determine bucket: force_mode override hoặc auto resolve
    if force_mode and force_mode in MODE_LABELS:
        bucket = force_mode
        bucket_source = "forced"
    else:
        bucket = resolve_mode_bucket(emotion, intensity)
        bucket_source = "auto"

    # Tìm ref theo bucket
    ref = modes.get(bucket)
    used = f"{bucket} ({bucket_source})"
    if not ref or not ref.get("audio"):
        # Fallback normal
        ref = modes.get("normal")
        used = f"normal (fallback from {bucket})"

    if not ref or not ref.get("audio"):
        # Last resort: legacy audio
        if role.audio:
            return (role.audio, role.reference_audio_text or "", "legacy (fallback)")
        return (None, None, "missing")

    return (ref.get("audio"), ref.get("text", "") or "", used)