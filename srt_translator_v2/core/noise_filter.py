"""
Noise filter — pre-process subtitle text trước khi gửi LLM dịch.

Strip các marker phụ đề không cần dịch:
- [音乐] / [Tiếng vỗ tay] / [BGM] / [sigh] / [laughing] — sound markers
- (旁白) / (画外音) — annotations
- *sigh* / *whisper* — action descriptors
- ♪ ... ♪ — music notation
- Filler TQ lặp lại rỗng nghĩa: 啊啊啊啊, 嗯嗯嗯, 那个那个

Trả về:
- clean_text: text sau khi strip
- is_noise: True nếu sau strip rỗng / chỉ còn filler
"""
from __future__ import annotations
import re


# Patterns cần strip (bracket markers)
_BRACKET_PATTERNS = [
    re.compile(r"\[[^\]]*\]"),          # [...]
    re.compile(r"\([^)]*\)"),            # (...)
    re.compile(r"\{[^}]*\}"),            # {...}
    re.compile(r"【[^】]*】"),            # 【...】 (TQ full-width)
    re.compile(r"\*[^*]+\*"),            # *...*
    re.compile(r"♪[^♪]*♪"),              # music
    re.compile(r"[♫♬]"),                 # music notes
]

# Filler/echo TQ lặp lại
_FILLER_REPEATS = re.compile(
    r"^([啊呃嗯哦哈嘿哎呀呐])\1+[!！?？.。,，]*$"
)

# Chỉ chứa dấu câu / khoảng trắng / ký tự lạ
_PUNCT_ONLY = re.compile(r"^[\s\.\,\!\?\;\:\-\—\"'。，！？；：、…\d]+$")


def strip_noise(text: str) -> tuple[str, bool]:
    """Strip noise markers khỏi text.

    Returns:
        (clean_text, is_noise)
        - clean_text: text sau khi strip
        - is_noise: True nếu sau strip còn rỗng / filler / punct-only
    """
    if not text or not text.strip():
        return "", True

    cleaned = text
    for pat in _BRACKET_PATTERNS:
        cleaned = pat.sub("", cleaned)

    # Strip dồn khoảng trắng
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    if not cleaned:
        return "", True

    # Filler lặp lại
    if _FILLER_REPEATS.match(cleaned):
        return cleaned, True

    # Chỉ dấu câu
    if _PUNCT_ONLY.match(cleaned):
        return cleaned, True

    # Quá ngắn (< 1 ký tự CJK / Latin có nghĩa)
    # Bỏ tất cả punct, đếm còn lại
    char_only = re.sub(r"[\s\.\,\!\?\;\:\-\—\"'。，！？；：、…\d]+", "", cleaned)
    if len(char_only) == 0:
        return cleaned, True

    return cleaned, False


def is_likely_noise(text: str) -> bool:
    """Quick check không cần clean text."""
    _, noise = strip_noise(text)
    return noise
