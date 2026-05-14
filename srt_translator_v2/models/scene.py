"""
Scene + Chunk models — v3.

Cấu trúc 3 tầng: Arc → Chunk → Scene
- Arc (đã có trong Bible.world.arcs): 3-8 đoạn cốt truyện lớn
- Chunk: 3-5 chunks/arc, ~250-400 dòng. Là "chương" có ý nghĩa kịch
- Scene: chia tiếp trong chunk (nếu chunk > 100 dòng). Là cảnh con

Bước 2 trả về Chunks + Scenes lồng nhau trong 1 call/arc.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────
# EMOTION (chuẩn 14 loại)
# ─────────────────────────────────────────────────────────────────

EMOTIONS = {
    "neutral", "happy", "sad", "angry", "cold", "tense",
    "intimate", "fearful", "sarcastic", "shocked", "determined",
    "regretful", "humorous", "threatening",
}


def normalize_emotion(value: Optional[str]) -> str:
    """Normalize emotion từ output LLM về 1 trong 14 loại chuẩn."""
    if not value:
        return "neutral"
    v = str(value).strip().lower()
    if v in EMOTIONS:
        return v
    # Aliases
    aliases = {
        "calm": "neutral", "joyful": "happy", "joy": "happy",
        "depressed": "sad", "melancholy": "sad", "grief": "sad",
        "furious": "angry", "mad": "angry", "rage": "angry",
        "indifferent": "cold", "distant": "cold",
        "anxious": "tense", "nervous": "tense", "worried": "tense",
        "loving": "intimate", "tender": "intimate", "romantic": "intimate",
        "scared": "fearful", "afraid": "fearful",
        "mocking": "sarcastic", "ironic": "sarcastic",
        "surprised": "shocked", "astonished": "shocked",
        "resolute": "determined", "firm": "determined",
        "remorseful": "regretful", "guilty": "regretful",
        "playful": "humorous", "funny": "humorous",
        "menacing": "threatening", "ominous": "threatening",
    }
    return aliases.get(v, "neutral")


# ─────────────────────────────────────────────────────────────────
# SCENE — cảnh con trong chunk
# ─────────────────────────────────────────────────────────────────

class Scene(BaseModel):
    """1 phân cảnh kịch."""
    r: tuple[int, int]                                # [start_line, end_line]
    ch: list[str] = Field(default_factory=list)       # characters_present (zh names)
    e: str = "neutral"                                # emotion_primary
    loc: str = ""                                     # location
    tag: Optional[str] = None                         # "HOOK" / "PEAK" / None

    # Suy ra từ tag
    @property
    def is_hook(self) -> bool:
        return self.tag == "HOOK"

    @property
    def is_emotion_peak(self) -> bool:
        return self.tag == "PEAK"

    @property
    def start_line(self) -> int:
        return self.r[0]

    @property
    def end_line(self) -> int:
        return self.r[1]

    @property
    def emotion_primary(self) -> str:
        return normalize_emotion(self.e)


# ─────────────────────────────────────────────────────────────────
# CHUNK — chương trong arc
# ─────────────────────────────────────────────────────────────────

class Chunk(BaseModel):
    """1 chunk (chương) trong arc."""
    r: tuple[int, int]                                # [start_line, end_line]
    t: str = ""                                       # Title chunk (vd "Lần đầu gặp gỡ")
    arc_index: int = 0                                # Thuộc arc nào
    scenes: list[Scene] = Field(default_factory=list) # Scenes con (có thể rỗng nếu chunk ngắn)

    @property
    def start_line(self) -> int:
        return self.r[0]

    @property
    def end_line(self) -> int:
        return self.r[1]

    @property
    def line_count(self) -> int:
        return self.r[1] - self.r[0] + 1

    def get_characters_in_chunk(self) -> list[str]:
        """Tổng hợp characters present trong tất cả scenes của chunk."""
        if not self.scenes:
            return []
        seen = set()
        result = []
        for sc in self.scenes:
            for ch in sc.ch:
                if ch not in seen:
                    seen.add(ch)
                    result.append(ch)
        return result


class ChunkMap(BaseModel):
    """Toàn bộ chunks của phim."""
    chunks: list[Chunk] = Field(default_factory=list)

    def get_chunk_for_line(self, line_idx: int) -> Optional[Chunk]:
        """Tìm chunk chứa dòng line_idx."""
        for c in self.chunks:
            if c.start_line <= line_idx <= c.end_line:
                return c
        return None

    def get_scene_for_line(self, line_idx: int) -> Optional[Scene]:
        """Tìm scene chứa dòng line_idx."""
        chunk = self.get_chunk_for_line(line_idx)
        if not chunk:
            return None
        for sc in chunk.scenes:
            if sc.start_line <= line_idx <= sc.end_line:
                return sc
        return None
