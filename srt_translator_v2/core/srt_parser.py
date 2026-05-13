"""
SRT parsing + building + CPS calculation.

Hỗ trợ format SRT chuẩn:
    1
    00:00:01,000 --> 00:00:03,500
    Văn bản

    2
    ...
"""
from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class SrtEntry:
    """1 dòng SRT thô (chưa qua pipeline)."""
    index: int
    start_sec: float
    end_sec: float
    text: str

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec

    @property
    def char_count(self) -> int:
        """Đếm ký tự (loại bỏ space đầu/cuối)."""
        return len(self.text.strip())

    @property
    def cps(self) -> float:
        """Characters per second."""
        d = self.duration_sec
        if d <= 0:
            return 999.0
        return self.char_count / d


# ─────────────────────────────────────────────────────────────────
# TIME PARSING
# ─────────────────────────────────────────────────────────────────

_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def parse_time(s: str) -> float:
    """'00:01:23,456' → 83.456 (giây)."""
    m = _TIME_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid SRT time: {s!r}")
    h, mn, sec, ms = m.groups()
    return int(h) * 3600 + int(mn) * 60 + int(sec) + int(ms.ljust(3, "0")[:3]) / 1000.0


def format_time(sec: float) -> str:
    """83.456 → '00:01:23,456'."""
    if sec < 0:
        sec = 0
    total_ms = int(round(sec * 1000))
    ms = total_ms % 1000
    s = (total_ms // 1000) % 60
    m = (total_ms // 60000) % 60
    h = total_ms // 3600000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ─────────────────────────────────────────────────────────────────
# PARSE
# ─────────────────────────────────────────────────────────────────

_BLOCK_RE = re.compile(
    r"(\d+)\s*\n([\d:,.]+)\s*-->\s*([\d:,.]+)\s*\n((?:[^\n]+\n?)+)",
    re.MULTILINE,
)


def parse_srt(raw: str) -> list[SrtEntry]:
    """Parse SRT text → list[SrtEntry]."""
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Strip BOM
    if raw.startswith("\ufeff"):
        raw = raw[1:]

    entries: list[SrtEntry] = []
    for m in _BLOCK_RE.finditer(raw):
        idx, t_start, t_end, text = m.groups()
        try:
            entries.append(SrtEntry(
                index=int(idx),
                start_sec=parse_time(t_start),
                end_sec=parse_time(t_end),
                text=text.strip(),
            ))
        except (ValueError, IndexError):
            continue

    # Re-index để liên tục
    for i, e in enumerate(entries, start=1):
        e.index = i

    return entries


def parse_srt_file(path: str) -> list[SrtEntry]:
    """Read file rồi parse, hỗ trợ utf-8 + utf-8-sig + gbk fallback."""
    for encoding in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return parse_srt(f.read())
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode SRT file: {path}")


# ─────────────────────────────────────────────────────────────────
# BUILD
# ─────────────────────────────────────────────────────────────────

def build_srt(entries: list[SrtEntry]) -> str:
    """List[SrtEntry] → SRT text."""
    blocks = []
    for e in entries:
        blocks.append(
            f"{e.index}\n"
            f"{format_time(e.start_sec)} --> {format_time(e.end_sec)}\n"
            f"{e.text}\n"
        )
    return "\n".join(blocks)


# ─────────────────────────────────────────────────────────────────
# STATISTICS
# ─────────────────────────────────────────────────────────────────

def srt_stats(entries: list[SrtEntry]) -> dict:
    """Thống kê 1 file SRT — debug/log."""
    if not entries:
        return {"total": 0}

    total_chars = sum(e.char_count for e in entries)
    total_duration = entries[-1].end_sec - entries[0].start_sec
    avg_cps = sum(e.cps for e in entries) / len(entries)
    max_cps = max(e.cps for e in entries)

    return {
        "total_lines": len(entries),
        "total_chars": total_chars,
        "total_duration_sec": round(total_duration, 1),
        "total_duration_min": round(total_duration / 60, 1),
        "avg_chars_per_line": round(total_chars / len(entries), 1),
        "avg_cps": round(avg_cps, 2),
        "max_cps": round(max_cps, 2),
        "first_time": format_time(entries[0].start_sec),
        "last_time": format_time(entries[-1].end_sec),
    }


# ─────────────────────────────────────────────────────────────────
# CPS HELPERS
# ─────────────────────────────────────────────────────────────────

def calculate_cps(text: str, duration_sec: float) -> float:
    """Tính CPS cho 1 text + duration."""
    if duration_sec <= 0:
        return 999.0
    return len(text.strip()) / duration_sec


def max_chars_for_duration(duration_sec: float, target_cps: float) -> int:
    """Số ký tự tối đa cho phép trong khoảng thời gian, với CPS mục tiêu."""
    return max(1, int(duration_sec * target_cps))
