"""
Bible models — v3 compact.

Thay đổi so với v2:
- Cast: BỎ self_address, addresses, social_status, speaking_style
       (gộp speaking_style vào personality làm `char` 1 câu)
- World: BỎ main_conflict, setting (gộp vào plot)
- Glossary: gộp 2 loại (thuật ngữ riêng phim + xưng hô theo thể loại)
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────
# CHARACTER (Cast)
# ─────────────────────────────────────────────────────────────────

class Character(BaseModel):
    """1 nhân vật trong phim."""
    zh: str = ""                              # Tên Trung gốc
    vi: str = ""                              # Tên Việt (Hán Việt)
    alias: list[str] = Field(default_factory=list)  # Biệt danh, cách gọi khác
    g: str = "?"                              # Giới tính: nam/nu/?
    role: str = "phu"                         # nam_chinh/nu_chinh/nam_phu/nu_phu/phan_dien/phu/khach
    age: Optional[str] = None                 # teen/20s/30s/40s/50s/trung niên/già
    char: str = ""                            # Tính cách + kiểu nói 1 câu ngắn
    rel: dict[str, str] = Field(default_factory=dict)  # Map zh_name → quan hệ
    catchphrase: Optional[str] = None         # Câu cửa miệng (optional)


class Cast(BaseModel):
    """Danh sách nhân vật."""
    characters: list[Character] = Field(default_factory=list)

    def get_by_zh(self, zh: str) -> Optional[Character]:
        """Tìm nhân vật theo tên Trung. Match exact hoặc alias."""
        if not zh:
            return None
        for ch in self.characters:
            if ch.zh == zh or zh in ch.alias:
                return ch
        return None

    def get_by_vi(self, vi: str) -> Optional[Character]:
        """Tìm nhân vật theo tên Việt."""
        if not vi:
            return None
        for ch in self.characters:
            if ch.vi == vi:
                return ch
        return None


# ─────────────────────────────────────────────────────────────────
# WORLD (Bối cảnh + Arcs)
# ─────────────────────────────────────────────────────────────────

class StoryArc(BaseModel):
    """1 đoạn cốt truyện lớn."""
    index: int                                # Thứ tự arc (0-based)
    r: tuple[int, int]                        # [start_line, end_line]
    t: str = ""                               # Title arc
    tone: str = "neutral"                     # tone arc: tense/warm/sad/intimate/angry/neutral/mixed


class World(BaseModel):
    """Bối cảnh phim."""
    genre: list[str] = Field(default_factory=list)  # ["đô thị", "tổng tài", "ngôn tình"]
    era: str = "hiện đại"                     # hiện đại/cổ đại/dân quốc/tương lai
    tone: str = ""                            # Tone tổng thể (1 câu)
    plot: str = ""                            # Tóm tắt plot (3-5 câu)
    arcs: list[StoryArc] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# GLOSSARY (gộp thuật ngữ riêng + xưng hô thể loại)
# ─────────────────────────────────────────────────────────────────

class GlossaryTerm(BaseModel):
    """1 thuật ngữ."""
    zh: str = ""                              # Term tiếng Trung
    vi: str = ""                              # Dịch tiếng Việt chuẩn
    cat: str = "khac"                         # Category: chuc_vu/dia_danh/khai_niem/cliche/tu_xung/khac
    n: int = 0                                # Số lần xuất hiện
    note: Optional[str] = None                # Ghi chú khi dùng (optional)


class Glossary(BaseModel):
    """Danh sách thuật ngữ."""
    terms: list[GlossaryTerm] = Field(default_factory=list)

    def find_in_text(self, text: str) -> list[GlossaryTerm]:
        """Trả các term có chuỗi zh xuất hiện trong text."""
        if not text:
            return []
        return [t for t in self.terms if t.zh and t.zh in text]


# ─────────────────────────────────────────────────────────────────
# BIBLE (đầy đủ)
# ─────────────────────────────────────────────────────────────────

class Bible(BaseModel):
    """Bible v3 — hồ sơ phim đầy đủ."""
    project_id: Optional[int] = None
    cast: Cast = Field(default_factory=Cast)
    world: World = Field(default_factory=World)
    glossary: Glossary = Field(default_factory=Glossary)
    # Metadata
    version: int = 1
    model_used: Optional[str] = None
