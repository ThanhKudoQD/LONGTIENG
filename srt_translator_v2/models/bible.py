"""
Pydantic models cho Bible — hồ sơ phim đầy đủ.

Bible gồm 3 phần độc lập:
- Cast (1A): danh sách nhân vật
- World (1B): bối cảnh + story arc
- Glossary (1C): thuật ngữ riêng phim
"""
from __future__ import annotations
from typing import Optional, Literal
from pydantic import BaseModel, Field, field_validator


# Helper — chuẩn hóa các giá trị gender LLM hay trả về.
# LLM thường trả: "nữ", "nam", "Nu", "Nam", "f", "m", "female", "male"...
_GENDER_MAP = {
    "nam": "nam", "m": "nam", "male": "nam", "boy": "nam", "man": "nam",
    "nu":  "nu",  "nữ": "nu", "f": "nu",     "female": "nu", "girl": "nu", "woman": "nu",
}

def _normalize_gender(v: str) -> str:
    if not v:
        return "?"
    v = str(v).strip().lower()
    return _GENDER_MAP.get(v, "?")

# Tương tự cho role — LLM hay trả thiếu/dư underscore, capitalize...
_ROLE_MAP = {
    "nam_chinh": "nam_chinh", "nam chinh": "nam_chinh", "namchinh": "nam_chinh", "nam chính": "nam_chinh",
    "nu_chinh":  "nu_chinh",  "nu chinh":  "nu_chinh",  "nuchinh":  "nu_chinh",  "nữ chính": "nu_chinh",
    "nam_phu":   "nam_phu",   "nam phu":   "nam_phu",   "namphu":   "nam_phu",   "nam phụ": "nam_phu",
    "nu_phu":    "nu_phu",    "nu phu":    "nu_phu",    "nuphu":    "nu_phu",    "nữ phụ": "nu_phu",
    "phan_dien": "phan_dien", "phan dien": "phan_dien", "phandien": "phan_dien", "phản diện": "phan_dien",
    "phu":       "phu",       "phụ":       "phu",
    "khach":     "khach",     "khách":     "khach",
}

def _normalize_role(v: str) -> str:
    if not v:
        return "phu"
    v = str(v).strip().lower()
    return _ROLE_MAP.get(v, "phu")


# ─────────────────────────────────────────────────────────────────
# 1A — CAST (Nhân vật)
# ─────────────────────────────────────────────────────────────────

class Pronouns(BaseModel):
    """Cách tự xưng của 1 nhân vật khi nói với từng đối tượng."""
    default: str = Field(default="tôi", description="Mặc định khi không có context")
    when_angry: Optional[str] = Field(default=None, description="Khi giận dữ")
    when_intimate: Optional[str] = Field(default=None, description="Khi thân mật/yêu")
    when_formal: Optional[str] = Field(default=None, description="Khi trang trọng")
    when_inferior: Optional[str] = Field(default=None, description="Khi nói với cấp trên")
    when_superior: Optional[str] = Field(default=None, description="Khi nói với cấp dưới")


class Character(BaseModel):
    """1 nhân vật trong phim."""
    zh: str = Field(description="Tên tiếng Trung gốc, vd: 顾沉舟")
    vi: str = Field(description="Tên Hán Việt, vd: Cố Trầm Châu")
    aliases_zh: list[str] = Field(default_factory=list, description="Các tên gọi khác trong phim")
    aliases_vi: list[str] = Field(default_factory=list)

    role: Literal[
        "nam_chinh", "nu_chinh",      # vai chính
        "nam_phu", "nu_phu",          # vai phụ quan trọng
        "phan_dien",                  # phản diện
        "phu",                        # nhân vật phụ thường
        "khach",                      # thoáng qua
    ] = "phu"

    gender: Literal["nam", "nu", "?"] = "?"
    age_group: Optional[str] = Field(default=None, description="vd: 25-30, lão, trẻ")
    social_status: Optional[str] = Field(default=None, description="vd: tổng tài, sinh viên, hoàng hậu")

    personality: str = Field(default="", description="Tính cách ngắn, 1-2 dòng")
    speaking_style: str = Field(default="", description="Kiểu nói đặc trưng")

    # Tự xưng và xưng hô
    self_address: Pronouns = Field(default_factory=Pronouns)
    addresses: dict[str, str] = Field(
        default_factory=dict,
        description="Map character_id -> cách gọi đối tượng đó (vd: 'co_tan' -> 'em trai')"
    )

    # Mối quan hệ
    relationships: dict[str, str] = Field(
        default_factory=dict,
        description="Map character_id -> mô tả mối quan hệ"
    )

    notes: str = Field(default="", description="Ghi chú thêm")

    # Validators — chấp nhận giá trị LLM hay trả về sai chuẩn
    @field_validator("gender", mode="before")
    @classmethod
    def _norm_gender(cls, v):
        return _normalize_gender(v) if v else "?"

    @field_validator("role", mode="before")
    @classmethod
    def _norm_role(cls, v):
        return _normalize_role(v) if v else "phu"


class Cast(BaseModel):
    """Toàn bộ dàn nhân vật của phim."""
    characters: list[Character] = Field(default_factory=list)

    def get_by_zh(self, zh_name: str) -> Optional[Character]:
        for c in self.characters:
            if c.zh == zh_name or zh_name in c.aliases_zh:
                return c
        return None

    def get_by_vi(self, vi_name: str) -> Optional[Character]:
        for c in self.characters:
            if c.vi == vi_name or vi_name in c.aliases_vi:
                return c
        return None


# ─────────────────────────────────────────────────────────────────
# 1B — WORLD (Bối cảnh + Story Arc)
# ─────────────────────────────────────────────────────────────────

GenreTag = Literal[
    "do_thi",          # đô thị
    "co_trang",        # cổ trang
    "dan_quoc",        # dân quốc
    "tien_hiep",       # tiên hiệp
    "huyen_huyen",     # huyền huyễn
    "vo_hiep",         # võ hiệp
    "khoa_huyen",      # khoa huyễn
    "khong_xac_dinh",
]

SubGenreTag = Literal[
    "ngon_tinh",            # ngôn tình
    "trong_sinh",           # trọng sinh
    "bao_thu",              # báo thù
    "cung_dau",             # cung đấu
    "tong_tai",             # tổng tài
    "chien_than",           # chiến thần
    "hac_dao",              # hắc đạo
    "than_y",               # thần y
    "trong_dau",            # tranh đấu / phim "đấu trí"
    "hai_huoc",             # hài hước
    "kinh_di",              # kinh dị
    "trinh_tham",           # trinh thám
    "gia_dau",              # gia tộc đấu
    "hoc_duong",            # học đường
    "khong_xac_dinh",
]


class StoryArc(BaseModel):
    """Một đoạn cốt truyện lớn (1 arc trong 60 tập)."""
    index: int
    title: str = Field(description="Tên ngắn, vd: 'Bị áp bức'")
    summary: str = Field(description="Tóm tắt 2-3 câu")
    start_line: int = Field(description="Dòng SRT bắt đầu arc")
    end_line: int = Field(description="Dòng SRT kết thúc arc")
    emotional_tone: str = Field(description="Tone chính, vd: 'đau khổ + uất ức'")
    key_events: list[str] = Field(default_factory=list, description="Sự kiện chính trong arc")


class World(BaseModel):
    """Bối cảnh thế giới + cốt truyện tổng thể."""
    genre_main: GenreTag = "khong_xac_dinh"
    genre_sub: list[SubGenreTag] = Field(default_factory=list)

    era: Optional[str] = Field(default=None, description="vd: 'hiện đại', 'Đại Đường', 'tu tiên giới'")
    setting: Optional[str] = Field(default=None, description="Bối cảnh không gian chính")

    plot_summary: str = Field(default="", description="Tóm tắt cốt truyện 3-5 câu")
    main_conflict: str = Field(default="", description="Xung đột chính")
    tone_overall: str = Field(default="", description="Tone tổng thể, vd: 'báo thù lạnh lùng, có ngôn tình ấm áp xen kẽ'")

    story_arcs: list[StoryArc] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# 1C — GLOSSARY (Thuật ngữ riêng phim)
# ─────────────────────────────────────────────────────────────────

class GlossaryTerm(BaseModel):
    """1 thuật ngữ riêng của phim, có cách dịch chuẩn."""
    zh: str = Field(description="Thuật ngữ tiếng Trung")
    vi: str = Field(description="Dịch tiếng Việt chuẩn cho phim này")
    category: Literal[
        "organization",   # tổ chức (vd: 毒蝎组织 → Tổ chức Bọ Cạp)
        "location",       # địa danh
        "title",          # chức vụ, tước hiệu
        "object",         # vật phẩm (kiếm, ấn ngọc...)
        "concept",        # khái niệm (vd: kim đan, nguyên anh)
        "nickname",       # biệt danh (vd: 老三 → Lão Tam)
        "idiom",          # thành ngữ 4 chữ
        "cliche",         # cliché câu thoại
        "other",
    ] = "other"
    notes: str = Field(default="", description="Ghi chú cách dùng / khi nào dịch khác")


class Glossary(BaseModel):
    """Tổng hợp thuật ngữ riêng của phim."""
    terms: list[GlossaryTerm] = Field(default_factory=list)

    def get(self, zh: str) -> Optional[GlossaryTerm]:
        for t in self.terms:
            if t.zh == zh:
                return t
        return None


# ─────────────────────────────────────────────────────────────────
# GENRE PACK (Thư viện thể loại)
# ─────────────────────────────────────────────────────────────────

class GenrePack(BaseModel):
    """1 pack thể loại có sẵn — kế thừa cho phim cùng thể loại."""
    id: str
    name_vi: str
    name_zh: str
    description: str

    # Đặc trưng tone
    tone_signature: str
    typical_pronouns: dict[str, str] = Field(
        default_factory=dict,
        description="Map situation -> pronoun pair, vd: 'ceo_với_thư_ký' -> 'tôi-cô'"
    )

    # Thuật ngữ + cliché có sẵn
    common_terms: list[GlossaryTerm] = Field(default_factory=list)
    common_cliches: list[GlossaryTerm] = Field(default_factory=list)

    # Few-shot examples cho prompt
    translation_examples: list[dict] = Field(
        default_factory=list,
        description="List of {zh, vi, context, note}"
    )

    # Quy tắc style override
    style_notes: str = Field(default="")


# ─────────────────────────────────────────────────────────────────
# MASTER BIBLE
# ─────────────────────────────────────────────────────────────────

class Bible(BaseModel):
    """Hồ sơ phim đầy đủ — output của Stage 1."""
    version: int = 1
    project_id: Optional[int] = None

    cast: Cast = Field(default_factory=Cast)
    world: World = Field(default_factory=World)
    glossary: Glossary = Field(default_factory=Glossary)
    genre_pack_id: Optional[str] = None