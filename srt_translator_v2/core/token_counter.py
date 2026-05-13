"""
Token estimation — tránh vượt context limit.

Không dùng tokenizer chính xác (tránh phụ thuộc thư viện nặng).
Dùng heuristic đủ tốt cho việc plan chi phí + tránh vượt limit.
"""
from __future__ import annotations
import re


# Tỷ lệ token/char trung bình theo ngôn ngữ
_CHAR_TO_TOKEN_RATIO = {
    "zh": 0.5,      # 1 ký tự Trung ≈ 0.5-1 token (thường hơi cao hơn)
    "vi": 0.4,      # tiếng Việt unicode dày token hơn ASCII
    "en": 0.25,
    "mixed": 0.4,
}


def estimate_tokens(text: str, lang: str = "mixed") -> int:
    """Ước lượng số token. Heuristic, không chính xác tuyệt đối."""
    if not text:
        return 0
    ratio = _CHAR_TO_TOKEN_RATIO.get(lang, 0.4)
    return max(1, int(len(text) * ratio))


def estimate_tokens_zh(text: str) -> int:
    """Estimate cho chuỗi tiếng Trung."""
    # Đếm CJK chars
    cjk_count = len(re.findall(r'[\u4e00-\u9fff]', text))
    ascii_count = len(text) - cjk_count
    # CJK ≈ 1 token / char, ASCII ≈ 0.25 token / char
    return cjk_count + max(1, int(ascii_count * 0.25))


def estimate_tokens_vi(text: str) -> int:
    """Estimate cho tiếng Việt."""
    # Tiếng Việt có dấu, token nặng hơn ASCII
    return max(1, int(len(text) * 0.4))


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate tổng token của list messages format OpenAI/Gemini."""
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total += estimate_tokens(part["text"])
    # Overhead ~10 token cho mỗi message
    total += len(messages) * 10
    return total
