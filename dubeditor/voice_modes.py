"""
Voice mode resolver — map emotion → 3 mode buckets.

3 mode buckets (rút từ 5):
  - normal  (BT)    : tất cả emotion thường, kể cả căng thẳng nhẹ
  - sad     (Buồn)  : đau khổ tuyệt vọng, buồn muốn khóc, hối hận sâu sắc
  - angry   (Giận)  : cực kỳ tức giận, căm phẫn, quát mắng dữ dội

Logic strict: chỉ map sang sad/angry khi cảm xúc CỰC MẠNH (intensity ≥ 8).
Cảm xúc nhẹ/vừa → normal hết.

Toggle OFF (Project.use_emotion_voice=False) → luôn dùng "normal"
Toggle ON  → resolve theo emotion+intensity của subtitle
"""
from __future__ import annotations
import json
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# 3 MODES
# ─────────────────────────────────────────────────────────────────

MODE_LABELS = {
    "normal": "Bình thường",
    "sad":    "Buồn",
    "angry":  "Tức giận",
}

MODE_ORDER = ["normal", "sad", "angry"]

# Màu hiển thị FE (cho consistency, FE có thể đọc)
MODE_COLORS = {
    "normal": "#6B7280",   # xám
    "sad":    "#2563EB",   # xanh dương
    "angry":  "#DC2626",   # đỏ
}


# ─────────────────────────────────────────────────────────────────
# EMOTION (14) → MODE (3) MAPPING — strict logic
# ─────────────────────────────────────────────────────────────────

# Threshold: chỉ map sang sad/angry khi intensity cực mạnh.
# Tất cả còn lại (kể cả căng nhẹ, lạnh lùng, mỉa mai) → normal.
SAD_INTENSITY_THRESHOLD   = 8
ANGRY_INTENSITY_THRESHOLD = 8

# Emotion thuộc nhóm "có khả năng" map sang sad nếu intensity cao
SAD_EMOTIONS = {"sad", "regretful", "fearful"}

# Emotion thuộc nhóm "có khả năng" map sang angry nếu intensity cao
ANGRY_EMOTIONS = {"angry", "threatening"}


def emotion_to_mode(emotion: Optional[str], intensity: Optional[int] = 5) -> str:
    """Map 14 emotion code → 3 mode bucket.

    Logic strict:
      - sad/regretful/fearful + intensity ≥ 8  → 'sad'  (đau khổ tuyệt vọng)
      - angry/threatening    + intensity ≥ 8  → 'angry' (cực kỳ giận)
      - Tất cả còn lại                         → 'normal'

    Examples:
      emotion_to_mode('sad', 5)     → 'normal'   (buồn nhẹ → BT)
      emotion_to_mode('sad', 8)     → 'sad'      (buồn rất mạnh)
      emotion_to_mode('angry', 9)   → 'angry'    (giận dữ dội)
      emotion_to_mode('angry', 6)   → 'normal'   (giận vừa → BT)
      emotion_to_mode('tense', 9)   → 'normal'   (căng thẳng cao nhưng không phải sad/angry)
      emotion_to_mode('shocked', 9) → 'normal'   (sốc → BT)
      emotion_to_mode('happy', 9)   → 'normal'   (vui → BT)
      emotion_to_mode(None, 5)      → 'normal'
    """
    e = (emotion or "").lower().strip()
    if not e:
        return "normal"
    i = intensity if intensity is not None else 5

    if e in SAD_EMOTIONS and i >= SAD_INTENSITY_THRESHOLD:
        return "sad"
    if e in ANGRY_EMOTIONS and i >= ANGRY_INTENSITY_THRESHOLD:
        return "angry"
    return "normal"


# ─────────────────────────────────────────────────────────────────
# VOICE MODES PARSER (Role.voice_modes JSON)
# ─────────────────────────────────────────────────────────────────

def parse_voice_modes(raw) -> dict:
    """Parse JSON string từ Role.voice_modes → dict.

    Format: {
      "normal": {"audio": "/uploads/...", "text": "...", "duration": 3.5},
      "sad":    {...},
      "angry":  {...},
    }
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
    return json.dumps(modes or {}, ensure_ascii=False)


# ─────────────────────────────────────────────────────────────────
# REF RESOLVER — logic chính cho TTS pipeline
# ─────────────────────────────────────────────────────────────────

def resolve_ref_for_emotion(
    role,
    emotion: Optional[str] = None,
    intensity: int = 5,
    *,
    use_emotion_voice: bool = False,
    force_mode: Optional[str] = None,
) -> tuple[Optional[str], Optional[str], str]:
    """Resolve audio path + transcript cho TTS dựa trên mode.

    Args:
        role: Role object có voice_modes + audio + reference_audio_text
        emotion: emotion code của subtitle (14 enum)
        intensity: 1-10
        use_emotion_voice: flag từ Project.use_emotion_voice
            True  → dùng mode theo emotion (qua emotion_to_mode)
            False → LUÔN dùng mode "normal" (toggle off = bình thường hết)
        force_mode: nếu set → override emotion auto. VD: 'sad', 'angry'

    Logic:
      1. Toggle OFF → mode = "normal"
      2. Toggle ON:
         a. force_mode set → dùng force_mode
         b. Không → mode = emotion_to_mode(emotion, intensity)
      3. Tìm voice_modes[mode] → có thì dùng
      4. Không có → fallback voice_modes["normal"]
      5. Vẫn không có → fallback role.audio (legacy)

    Returns:
        (audio_path, transcript, mode_used)
        mode_used: 'normal' / 'sad' / 'angry' / 'legacy' / 'missing'
                   kèm chú thích nếu là forced/fallback
    """
    modes = parse_voice_modes(getattr(role, "voice_modes", None))

    # Determine target mode
    if not use_emotion_voice:
        target = "normal"
        source = "off"
    elif force_mode and force_mode in MODE_LABELS:
        target = force_mode
        source = "forced"
    else:
        target = emotion_to_mode(emotion, intensity)
        source = "auto"

    # Lookup ref
    ref = modes.get(target)
    used = f"{target} ({source})"

    if not ref or not ref.get("audio"):
        # Fallback normal nếu target khác
        if target != "normal":
            ref = modes.get("normal")
            used = f"normal (fallback from {target})"

    if not ref or not ref.get("audio"):
        # Last resort: legacy audio
        if role.audio:
            return (role.audio, role.reference_audio_text or "", "legacy")
        return (None, None, "missing")

    return (ref.get("audio"), ref.get("text", "") or "", used)