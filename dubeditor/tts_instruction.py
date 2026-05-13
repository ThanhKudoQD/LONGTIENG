"""
TTS instruction builder cho VoxCPM 2.

VoxCPM cho phép prefix `(...)` trước text để control giọng:
- Voice Design mode (không reference audio): (young woman, gentle and sweet voice)
- Controllable Cloning mode (có reference_wav_path): (slightly faster, cheerful tone)
- Hi-Fi mode (prompt_wav_path + prompt_text): instruction BỊ IGNORE

Doc: https://voxcpm.readthedocs.io/en/latest/usage.html

Logic build (3 lớp):
  1. CHARACTER voice descriptor (từ Bible): gender + age_group → "young woman" / "mature male voice" ...
  2. EMOTION + INTENSITY modifier: "intensely cold distant tone"
  3. Ghép thành: "(<voice>, <intensity adverb> <emotion tone>)"

Ví dụ output:
  Khương Khuynh Tâm (nữ 22t) + emotion=sad + intensity=8
    → "(young woman, strongly soft melancholy tone)"

  Hoắc tổng (nam 35t) + emotion=cold + intensity=9
    → "(mature male voice, intensely cold distant tone)"

  Bạn thân nữ + emotion=tense + intensity=6
    → "(young woman, tense anxious tone)"
"""
from __future__ import annotations
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# EMOTION → TONE DESCRIPTOR
# ─────────────────────────────────────────────────────────────────
# Map 14 emotion code chuẩn của pipeline v2 → mô tả tone tiếng Anh
# cho VoxCPM (model hiểu EN/ZH tốt nhất, không hỗ trợ VI).

EMOTION_TONE: dict[str, str] = {
    # 9 emotion đang có trong DB
    "neutral":     "natural conversational tone",
    "happy":       "cheerful upbeat tone",
    "sad":         "soft melancholy tone",
    "angry":       "sharp angry tone",
    "cold":        "cold distant tone",
    "tense":       "tense anxious tone",
    "intimate":    "soft tender intimate tone",
    "fearful":     "trembling fearful tone",
    "sarcastic":   "sarcastic mocking tone",
    "shocked":     "shocked surprised tone",
    "determined":  "firm resolute tone",
    "regretful":   "soft regretful tone",
    # 5 emotion chuẩn còn lại (có thể xuất hiện ở phim khác)
    "humorous":    "playful lighthearted tone",
    "threatening": "low threatening tone",
}


# ─────────────────────────────────────────────────────────────────
# INTENSITY → ADVERB
# ─────────────────────────────────────────────────────────────────
# Intensity 1-10 chia 4 mức tone modifier.

def intensity_adverb(intensity: int) -> str:
    """Trả về adverb để bổ nghĩa cho tone theo cường độ.

    1-3:  gently     (tone nhẹ)
    4-6:  ""         (mặc định, không thêm)
    7-8:  strongly   (mạnh)
    9-10: intensely  (rất mạnh)
    """
    i = max(1, min(10, intensity or 5))
    if i <= 3:
        return "gently"
    if i <= 6:
        return ""
    if i <= 8:
        return "strongly"
    return "intensely"


# ─────────────────────────────────────────────────────────────────
# CHARACTER → VOICE DESCRIPTOR
# ─────────────────────────────────────────────────────────────────
# Build mô tả giọng từ thông tin nhân vật (gender + age_group + role).

# Map age_group string → tuổi tham khảo
def _parse_age_group(age_group: Optional[str]) -> str:
    """Chuyển age_group string → tier: 'child' / 'young' / 'mature' / 'old'.

    Hỗ trợ format: "8-12", "20-25", "30-35", "50", "trẻ", "trung niên", "lão"...
    """
    if not age_group:
        return "young"   # mặc định trẻ
    s = str(age_group).lower().strip()

    # Tiếng Việt qualitative
    if any(k in s for k in ("trẻ em", "thiếu nhi", "nhi đồng", "child")):
        return "child"
    if any(k in s for k in ("lão", "già", "cao tuổi", "elder", "old")):
        return "old"
    if any(k in s for k in ("trung niên", "trung tuổi", "middle")):
        return "mature"
    if "trẻ" in s or "thanh niên" in s or "young" in s:
        return "young"

    # Numeric: lấy số đầu tiên
    import re as _re
    m = _re.search(r'\d+', s)
    if m:
        n = int(m.group())
        if n < 13:
            return "child"
        if n < 30:        # 13-29: thanh niên, sinh viên
            return "young"
        if n < 55:        # 30-54: trung niên (CEO, tổng tài)
            return "mature"
        return "old"

    return "young"


def build_voice_descriptor(
    gender: Optional[str],
    age_group: Optional[str],
    role: Optional[str] = None,
) -> str:
    """Build mô tả giọng dạng 'young woman' / 'mature male voice' / ...

    Args:
        gender: "nam" / "nu" / "?" / None
        age_group: vd "20-25", "trung niên", "50"...
        role: vd "nam_chinh", "nu_chinh", "phan_dien"... (chỉ dùng nếu gender không có)
    """
    g = (gender or "").lower().strip()
    tier = _parse_age_group(age_group)

    # Infer gender từ role nếu thiếu
    if g not in ("nam", "nu"):
        if role:
            r = str(role).lower()
            if "nam" in r:
                g = "nam"
            elif "nu" in r or "nữ" in r:
                g = "nu"

    # Build descriptor
    if g == "nam":
        if tier == "child":
            return "young boy voice"
        if tier == "young":
            return "young man"
        if tier == "mature":
            return "mature male voice"
        return "elderly male voice"
    if g == "nu":
        if tier == "child":
            return "young girl voice"
        if tier == "young":
            return "young woman"
        if tier == "mature":
            return "mature female voice"
        return "elderly female voice"

    # Unknown gender — neutral
    if tier == "child":
        return "child voice"
    if tier == "old":
        return "elderly voice"
    return "adult voice"


# ─────────────────────────────────────────────────────────────────
# BUILD FULL INSTRUCTION
# ─────────────────────────────────────────────────────────────────

def build_tts_instruction(
    emotion: Optional[str],
    intensity: Optional[int] = 5,
    *,
    gender: Optional[str] = None,
    age_group: Optional[str] = None,
    role: Optional[str] = None,
    voice_override: Optional[str] = None,
) -> str:
    """Build control instruction để prefix vào text khi gọi VoxCPM.

    Output có format: `(<voice descriptor>, <adverb> <emotion tone>)`

    Args:
        emotion: 1 trong 14 emotion code (neutral, happy, sad, ...)
        intensity: 1-10 (mặc định 5)
        gender: "nam"/"nu"/"?" — của speaker, lấy từ Bible.Cast
        age_group: vd "20-25" — lấy từ Bible.Cast
        role: vd "nam_chinh" — fallback nếu gender thiếu
        voice_override: nếu muốn override voice descriptor hoàn toàn
            (vd: user edit tay "old wise voice")

    Returns:
        String instruction VD: "(young woman, strongly soft melancholy tone)"
        Trả "" nếu không đủ data để build (caller có thể quyết định
        không prefix gì).
    """
    voice = voice_override or build_voice_descriptor(gender, age_group, role)

    tone = EMOTION_TONE.get((emotion or "").lower().strip(), "")
    if not tone:
        # Không có emotion → chỉ voice descriptor (vẫn hữu ích)
        if not voice:
            return ""
        return f"({voice})"

    adverb = intensity_adverb(intensity or 5)
    tone_part = f"{adverb} {tone}".strip()

    if not voice:
        return f"({tone_part})"
    return f"({voice}, {tone_part})"


# ─────────────────────────────────────────────────────────────────
# PROMPT FORMATTER (prefix vào text trước khi gửi VoxCPM)
# ─────────────────────────────────────────────────────────────────

def prefix_instruction(text: str, instruction: Optional[str]) -> str:
    """Prefix instruction vào text. Nếu instruction rỗng/None → return text gốc.

    VoxCPM yêu cầu instruction nằm trước text trong cùng 1 string:
        "(young woman, gentle tone)Hello there!"
    """
    if not instruction:
        return text or ""
    instruction = instruction.strip()
    if not instruction:
        return text or ""
    # Bảo đảm có dấu ngoặc
    if not (instruction.startswith("(") and instruction.endswith(")")):
        instruction = f"({instruction})"
    return f"{instruction}{text or ''}"