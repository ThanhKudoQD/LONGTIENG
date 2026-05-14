"""
suspicious_scanner — Phát hiện dòng phụ đề bất thường (Stage 0).

Output dùng làm input cho Stage 0 AI cleanup.

Mỗi dòng khả nghi sẽ có `reason` để báo AI biết tại sao nó được flag.
"""
from __future__ import annotations
import re
from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────
# Patterns
# ─────────────────────────────────────────────────────────────────

# Watermark / platform / studio TQ
_WATERMARK_PATTERNS = [
    re.compile(r"\b(腾讯视频|爱奇艺|优酷|搜狐视频|搜狐|芒果TV|哔哩哔哩|B站|湖南卫视|央视)\b"),
    re.compile(r"(字幕组|出品|制作|献映|监制|总制片|总导演)"),
    re.compile(r"(腾讯|爱奇艺|优酷|搜狐|芒果|湖南|央视|哔哩)"),
]

# Số tập / episode marker
_EPISODE_PATTERNS = [
    re.compile(r"第\s*\d+\s*集"),
    re.compile(r"\bEpisode\s*\d+", re.IGNORECASE),
    re.compile(r"\bEP\s*\d+", re.IGNORECASE),
]

# URL / mention / hashtag
_NET_PATTERNS = [
    re.compile(r"https?://\S+"),
    re.compile(r"www\.\S+"),
    re.compile(r"@\w+"),
    re.compile(r"#\w+"),
]

# Ký tự đặc biệt nhiều / dấu trang trí
_DECO_PATTERN = re.compile(r"[※■◆▼►★☆♦♥◇□△○●]+")
_LONG_DASH_PATTERN = re.compile(r"[—_=]{4,}")

# Whitespace bất thường (≥3 space liên tiếp giữa chữ, hoặc tab)
_WHITESPACE_PATTERN = re.compile(r"[ \u3000]{1,}|\t")

# Toàn dấu câu / số / ký tự rời
_PUNCT_ONLY_PATTERN = re.compile(r"^[\s\.\,\!\?\;\:\-\—\"'。，！？；：、…\d]+$")

# Lặp ký tự >= 5 lần liên tiếp (vd 啊啊啊啊啊, 哈哈哈哈哈哈)
_REPEAT_PATTERN = re.compile(r"(.)\1{4,}")


@dataclass
class SuspiciousFlag:
    """1 dòng bị flag — kèm lý do."""
    line_index: int
    text: str
    reasons: list[str]


# ─────────────────────────────────────────────────────────────────
# Detection
# ─────────────────────────────────────────────────────────────────

def detect_reasons(text: str, prev_text: str = "") -> list[str]:
    """Phân tích 1 dòng. Trả về list lý do khả nghi (rỗng nếu OK)."""
    if text is None:
        return ["null_text"]

    t = text.strip()
    reasons: list[str] = []

    # 1. Empty
    if not t:
        return ["empty"]

    # 2. Watermark
    for pat in _WATERMARK_PATTERNS:
        if pat.search(t):
            reasons.append(f"watermark:{pat.pattern}")
            break

    # 3. Episode marker
    for pat in _EPISODE_PATTERNS:
        if pat.search(t):
            reasons.append("episode_marker")
            break

    # 4. URL / mention
    for pat in _NET_PATTERNS:
        if pat.search(t):
            reasons.append("url_or_mention")
            break

    # 5. Decoration chars
    if _DECO_PATTERN.search(t):
        reasons.append("decoration_chars")

    # 6. Long dashes
    if _LONG_DASH_PATTERN.search(t):
        reasons.append("long_dashes")

    # 7. Whitespace gap
    if _WHITESPACE_PATTERN.search(t):
        reasons.append("whitespace_gap")

    # 8. Punct/digits only
    if _PUNCT_ONLY_PATTERN.match(t):
        reasons.append("punct_only")

    # 9. Char repeat ≥5 lần
    m = _REPEAT_PATTERN.search(t)
    if m:
        reasons.append(f"repeat_char:{m.group(1)}")

    # 10. Too long (CJK text thường ≤ 30 chars per sub)
    # Dùng len Unicode (mỗi ký tự CJK = 1 char)
    if len(t) > 80:
        reasons.append("too_long")

    # 11. Trùng lặp với dòng trước ≥ 90%
    if prev_text and prev_text.strip():
        prev_t = prev_text.strip()
        # Nếu identical hoặc 1 là prefix của cái còn lại
        if t == prev_t or (len(t) > 5 and len(prev_t) > 5 and
                           (t.startswith(prev_t) or prev_t.startswith(t))):
            reasons.append("duplicate_prev")

    # 12. Quá ngắn cô lập (1 ký tự + không phải Vâng/Dạ/Hả)
    common_short = {"嗯", "啊", "哦", "哈", "诶", "喂", "哎", "呃"}
    if len(t) == 1 and t not in common_short and not re.match(r"[a-zA-Z\u4e00-\u9fff]", t):
        reasons.append("isolated_char")

    return reasons


def scan_suspicious(
    entries: list,
) -> list[SuspiciousFlag]:
    """Scan toàn bộ entries, trả về danh sách dòng khả nghi.

    Args:
        entries: list[SrtEntry] hoặc object có .index và .text

    Returns:
        list[SuspiciousFlag]
    """
    flags = []
    prev_text = ""
    for e in entries:
        text = getattr(e, "text", "") or ""
        idx = getattr(e, "index", 0)
        reasons = detect_reasons(text, prev_text)
        if reasons:
            flags.append(SuspiciousFlag(
                line_index=idx,
                text=text,
                reasons=reasons,
            ))
        prev_text = text
    return flags


def cluster_suspicious(
    flags: list[SuspiciousFlag],
    entries_by_idx: dict[int, object],
    context_window: int = 10,
    max_cluster_size: int = 8,
) -> list[dict]:
    """Gom các flag thành cluster để gửi AI.

    Mỗi cluster gồm:
      - suspicious_lines: list[SuspiciousFlag] gần nhau
      - context_lines: [10 dòng trước + 10 dòng sau cluster]

    Cluster mới được mở khi 2 flag cách nhau > context_window dòng.

    Args:
        flags: từ scan_suspicious()
        entries_by_idx: map index → entry (để lấy text context)
        context_window: số dòng context mỗi bên
        max_cluster_size: số flag tối đa / cluster (tránh prompt quá to)
    """
    if not flags:
        return []

    clusters: list[list[SuspiciousFlag]] = []
    current: list[SuspiciousFlag] = [flags[0]]

    for f in flags[1:]:
        gap = f.line_index - current[-1].line_index
        # Nếu gần (≤ 2*window) thì gom chung, không thì cluster mới
        if gap <= context_window * 2 and len(current) < max_cluster_size:
            current.append(f)
        else:
            clusters.append(current)
            current = [f]
    clusters.append(current)

    # Build context cho mỗi cluster
    result = []
    for cluster in clusters:
        first_idx = cluster[0].line_index
        last_idx = cluster[-1].line_index

        # Lấy context lines (không bao gồm các flag trong cluster)
        flag_indices = {f.line_index for f in cluster}
        context_before = []
        context_after = []

        for i in range(max(1, first_idx - context_window), first_idx):
            if i in flag_indices:
                continue
            e = entries_by_idx.get(i)
            if e:
                context_before.append({
                    "i": i,
                    "text": getattr(e, "text", "") or "",
                })

        # Tìm max index trong entries
        max_idx = max(entries_by_idx.keys()) if entries_by_idx else last_idx
        for i in range(last_idx + 1, min(max_idx, last_idx + context_window) + 1):
            if i in flag_indices:
                continue
            e = entries_by_idx.get(i)
            if e:
                context_after.append({
                    "i": i,
                    "text": getattr(e, "text", "") or "",
                })

        result.append({
            "suspicious": [
                {"i": f.line_index, "text": f.text, "reasons": f.reasons}
                for f in cluster
            ],
            "context_before": context_before,
            "context_after": context_after,
        })

    return result
