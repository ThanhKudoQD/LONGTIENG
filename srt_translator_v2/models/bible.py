"""
Bible models — v3 compact + v4.1 mở rộng.

Thay đổi so với v2:
- Cast: BỎ self_address, addresses, social_status, speaking_style
       (gộp speaking_style vào personality làm `char` 1 câu)
- World: BỎ main_conflict, setting (gộp vào plot)
- Glossary: gộp 2 loại (thuật ngữ riêng phim + xưng hô theo thể loại)

v4.1: thêm các field optional (không break v3):
- Character: tier, line_count, catchphrase
- GlossaryTerm: type, usage, trope, register (1 trong số tùy category)
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
    # v4.1 additions
    tier: Optional[str] = None                # main/supporting/minor/cameo
    line_count: Optional[int] = None          # ước lượng số dòng thoại
    catchphrase: Optional[str] = None         # câu cửa miệng


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
    t: str = ""                               # Title arc (5-10 chữ)
    summary: str = ""                         # Tóm tắt nội dung arc (2-3 câu)
    tone: str = "neutral"                     # tone arc: tense/warm/sad/intimate/angry/neutral/mixed


class World(BaseModel):
    """Bối cảnh phim."""
    genre: list[str] = Field(default_factory=list)
    genre_id: str = "other"
    era: str = "hiện đại"
    tone: str = ""
    plot: str = ""
    arcs: list[StoryArc] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# GLOSSARY (gộp thuật ngữ riêng + xưng hô thể loại)
# ─────────────────────────────────────────────────────────────────

# 5 nhóm v4.1 (đẩy vào field `cat`):
#   "title"        — Chức vụ / Danh xưng (vd: 顾总 → Tổng Cố)
#   "place_org"    — Địa danh / Tổ chức (vd: 顾氏集团 → Tập đoàn Cố thị)
#   "concept"      — Khái niệm thể loại (vd: 合同婚姻 → Hôn nhân hợp đồng)
#   "cliche"       — Cliché / Trope (vd: 替嫁 → thay cô dâu)
#   "idiom"        — Thành ngữ / Nói đểu (vd: 阴阳怪气 → nói kháy)
# Tương thích cũ:
#   "chuc_vu", "dia_danh", "khai_niem", "tu_xung", "khac"

class GlossaryTerm(BaseModel):
    """1 thuật ngữ."""
    zh: str = ""
    vi: str = ""
    cat: str = "khac"                         # Category — xem comment trên
    note: Optional[str] = None
    # v4.1 — số lần xuất hiện
    n: Optional[int] = None
    # v4.1 — metadata theo nhóm (chỉ 1 cái có giá trị tùy cat)
    type: Optional[str] = None                # cho titles + places_orgs + concepts
    usage: Optional[str] = None               # cho titles
    trope: Optional[str] = None               # cho cliches
    register: Optional[str] = None            # cho idioms


class Glossary(BaseModel):
    """Danh sách thuật ngữ."""
    terms: list[GlossaryTerm] = Field(default_factory=list)

    def find_in_text(self, text: str) -> list[GlossaryTerm]:
        """Trả các term có chuỗi zh xuất hiện trong text."""
        if not text:
            return []
        return [t for t in self.terms if t.zh and t.zh in text]

    # v4.1: helper properties để access 5 nhóm như attribute
    @property
    def titles(self) -> list[GlossaryTerm]:
        return [t for t in self.terms if t.cat in ("title", "chuc_vu", "tu_xung")]

    @property
    def places_orgs(self) -> list[GlossaryTerm]:
        return [t for t in self.terms if t.cat in ("place_org", "dia_danh")]

    @property
    def concepts(self) -> list[GlossaryTerm]:
        return [t for t in self.terms if t.cat in ("concept", "khai_niem")]

    @property
    def cliches(self) -> list[GlossaryTerm]:
        return [t for t in self.terms if t.cat == "cliche"]

    @property
    def idioms(self) -> list[GlossaryTerm]:
        return [t for t in self.terms if t.cat == "idiom"]


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
