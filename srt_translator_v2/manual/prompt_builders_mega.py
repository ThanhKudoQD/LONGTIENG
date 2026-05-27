"""
Mega-chunk manual prompt builders (v4).

Module này thay thế các builder per-chunk cũ bằng builder mega-chunk.
KHÔNG xóa code cũ — chỉ thêm builder mới với tên stage khác để giữ backward-compat.

Stages mới (v4.2 — đã bỏ chunks_full):
  - bible_unified     1 unit  (gộp cast+world+glossary+arcs, toàn phim 1 paste)
  - translate_mega    N units (mega-chunk từ Bible arcs, ~500 dòng/cái, configurable)
                              (gộp speaker + translate trong cùng 1 prompt)
  - review_pass1      1 unit  (consistency scan toàn phim)
  - review_pass2      N units (per-arc polish)

Workflow user:
  Bible (1) → Translate Mega (N) → Review P1 (1) → Review P2 (N)

Khái niệm "mega-chunk":
  Mega-chunk gom các Arc liên tiếp HOẶC chia 1 Arc dài thành nhiều step,
  mỗi cái ≤ target_lines (default 500, configurable per-project).
  Mega luôn nằm GỌN trong 1 arc hoặc gộp toàn vẹn các arc liền kề.
"""
from __future__ import annotations
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from sqlalchemy.orm import Session

_TRANSLATOR_DIR = Path(__file__).parent.parent
if str(_TRANSLATOR_DIR) not in sys.path:
    sys.path.insert(0, str(_TRANSLATOR_DIR))

from config import PipelineConfig
from core.srt_parser import SrtEntry
from manual.prompt_builders import (
    BuiltPrompt, StageUnit,
    _load_entries, _load_bible, _load_chunk_map,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════
# CONFIG (constants, có thể override per-project qua Project.mega_target_lines)
# ═════════════════════════════════════════════════════════════════

# Default target — user có thể chỉnh trong UI Settings.
# Mega-partition cố gắng giữ mỗi mega ≤ DEFAULT_MEGA_TARGET_LINES.
DEFAULT_MEGA_TARGET_LINES = 500
MEGA_TARGET_MIN = 200
MEGA_TARGET_MAX = 2000

MEGA_CHUNK_OVERLAP_LINES = 30    # Context before/after window

REVIEW_CONTEXT_LINES = 5         # Số dòng before/after mỗi issue trong Pass 1


def _resolve_mega_target(db: Session, project_id: int) -> int:
    """Lấy mega_target_lines từ Project, fallback default nếu chưa set."""
    try:
        from dubeditor.models import Project as DBProject
        p = db.query(DBProject).filter(DBProject.id == project_id).first()
        if p is not None:
            val = getattr(p, "mega_target_lines", None)
            if val and MEGA_TARGET_MIN <= val <= MEGA_TARGET_MAX:
                return int(val)
    except Exception as e:
        logger.warning(f"[mega] resolve target failed, using default: {e}")
    return DEFAULT_MEGA_TARGET_LINES


# ═════════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════════

def _load_translated_lines(db: Session, project_id: int) -> dict[int, dict]:
    """Load các dòng đã có bản dịch (text_v1, text_v2) từ DB.
    Trả dict {line_index: {"v1": str, "v2": str|None, "speaker_zh": str|None}}.
    """
    from dubeditor.models import Subtitle
    subs = (db.query(Subtitle)
              .filter(Subtitle.project_id == project_id)
              .order_by(Subtitle.index)
              .all())
    out = {}
    for s in subs:
        v1 = getattr(s, "text_v1", None) or getattr(s, "text_vi", None) or ""
        v2 = getattr(s, "text_v2", None)
        out[s.index] = {
            "v1": v1,
            "v2": v2 if v2 else None,
            "speaker_zh": s.speaker_zh,
            "text_zh": s.original_text or "",
        }
    return out


def _format_bible_block(bible) -> str:
    """Render Bible thành text block ngắn gọn cho prompt."""
    lines = []
    # World
    w = bible.world
    lines.append(f"GENRE: {', '.join(w.genre)} ({w.genre_id})")
    lines.append(f"ERA: {w.era}")
    lines.append(f"TONE: {w.tone}")
    lines.append(f"PLOT: {w.plot}")
    lines.append("")
    # Arcs
    lines.append("ARCS:")
    for arc in w.arcs:
        lines.append(f"  - Arc {arc.index} [{arc.r[0]}-{arc.r[1]}]: "
                     f"{arc.t} (tone: {arc.tone})")
        if getattr(arc, "summary", None):
            lines.append(f"      {arc.summary}")
    lines.append("")
    # Characters
    lines.append("CHARACTERS:")
    for ch in bible.cast.characters:
        age = f", {ch.age}" if ch.age else ""
        catch = f' [catchphrase: "{ch.catchphrase}"]' if getattr(ch, "catchphrase", None) else ""
        lines.append(f"  - {ch.vi} ({ch.zh}): {ch.g}, {ch.role}{age}{catch}")
        lines.append(f"      char: {ch.char}")
        if ch.rel:
            rel_str = "; ".join(f"{other}→{rel}" for other, rel in ch.rel.items())
            lines.append(f"      rel: {rel_str}")
    lines.append("")
    # Glossary — hỗ trợ cả format mới (5 nhóm) và cũ (1 list terms)
    lines.append("GLOSSARY:")
    glossary = bible.glossary

    # Check xem có format mới không (5 nhóm) hoặc cũ (terms)
    has_new_format = any(
        hasattr(glossary, attr) and getattr(glossary, attr)
        for attr in ["titles", "places_orgs", "concepts", "cliches", "idioms"]
    )

    if has_new_format:
        groups = [
            ("titles", "Chức vụ / Danh xưng"),
            ("places_orgs", "Địa danh / Tổ chức"),
            ("concepts", "Khái niệm thể loại"),
            ("cliches", "Cliché / Tropes"),
            ("idioms", "Thành ngữ / Nói đểu"),
        ]
        for attr, label in groups:
            items = getattr(glossary, attr, None) or []
            if not items:
                continue
            lines.append(f"  ━ {label}:")
            for t in items:
                note = f"  ({t.note})" if getattr(t, "note", None) else ""
                lines.append(f"    - {t.zh} → \"{t.vi}\"{note}")
    elif getattr(glossary, "terms", None):
        # Fallback: format cũ
        for t in glossary.terms:
            note = f"  ({t.note})" if getattr(t, "note", None) else ""
            lines.append(f"  - {t.zh} → \"{t.vi}\"{note}")
    else:
        lines.append("  (chưa có term nào)")
    return "\n".join(lines)


def _format_chinese_subtitles_block(
    entries: list[SrtEntry],
    start: int = 1,
    end: Optional[int] = None,
    with_duration: bool = False,
) -> str:
    """Format thoại TQ thành block 'idx | (duration |) text_zh'.
    Bỏ qua noise (text rỗng từ stage 0)."""
    if end is None:
        end = entries[-1].index if entries else 0
    out = []
    for e in entries:
        if e.index < start or e.index > end:
            continue
        if not (e.text or "").strip():
            continue
        if with_duration:
            dur = max(0.1, e.duration_sec)
            out.append(f"{e.index} | {dur:.1f}s | {e.text}")
        else:
            out.append(f"{e.index} | {e.text}")
    return "\n".join(out) if out else "(không có dòng)"


def _load_prompt_template(name: str, config: PipelineConfig) -> str:
    """Load prompt template từ prompts/v3/ (hoặc prompts/v4_manual/ nếu tồn tại)."""
    # Ưu tiên v4_manual nếu có, fallback v3
    v4_dir = config.prompts_dir.parent / "v4_manual"
    v4_path = v4_dir / f"{name}.txt"
    if v4_path.exists():
        return v4_path.read_text(encoding="utf-8")
    v3_path = config.prompts_dir / f"{name}.txt"
    return v3_path.read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════
# MEGA-CHUNK PARTITIONING — dùng Bible.arcs làm nguồn (v4.2)
# ═════════════════════════════════════════════════════════════════

@dataclass
class MegaChunk:
    """1 mega-chunk = đoạn dòng liên tiếp trong 1 arc HOẶC nhiều arc liền nhau.

    v4.2: không dựa vào DB chunks nữa. Mega chia trực tiếp từ Bible.arcs.
    """
    index: int                       # 0-based
    line_range: tuple[int, int]      # (start_line, end_line) inclusive
    arc_indices: list[int]           # arcs liên quan (1 hoặc nhiều)
    arc_step: Optional[tuple[int, int]] = None  # (step, total_steps) nếu arc bị split
    title: str = ""


def partition_into_mega_from_arcs(
    bible, total_lines: int, target_lines: int = DEFAULT_MEGA_TARGET_LINES,
) -> list[MegaChunk]:
    """Phân chia phim thành mega chunks dựa trên Bible.arcs.

    Logic:
      - Mỗi arc xét lần lượt theo thứ tự.
      - Nếu arc ≤ target_lines: thử gộp với mega đang xây.
        + Nếu mega đang xây + arc ≤ target → gộp tiếp.
        + Nếu vượt → flush mega cũ, mở mega mới với arc này.
      - Nếu arc > target_lines: flush mega đang xây, chia arc thành nhiều step,
        mỗi step là 1 mega riêng (cùng arc_index, có arc_step).

    Yêu cầu: bible.world.arcs đã validated (cover [1, total_lines], no gap).
    """
    if not bible or not bible.world or not bible.world.arcs:
        # Fallback: nếu không có arcs, tạo 1 mega cover toàn phim
        if total_lines > 0:
            return [MegaChunk(
                index=0,
                line_range=(1, total_lines),
                arc_indices=[],
                title="Toàn phim (không có arcs)",
            )]
        return []

    arcs = sorted(bible.world.arcs, key=lambda a: a.r[0])
    megas: list[MegaChunk] = []

    # State cho việc gộp các arc ngắn
    cur_start: Optional[int] = None
    cur_end: int = 0
    cur_arcs: list[int] = []
    cur_titles: list[str] = []
    cur_lines: int = 0

    def flush_merged():
        nonlocal cur_start, cur_end, cur_arcs, cur_titles, cur_lines
        if cur_start is None or not cur_arcs:
            return
        title = " · ".join(cur_titles[:3]) + (" ..." if len(cur_titles) > 3 else "")
        megas.append(MegaChunk(
            index=len(megas),
            line_range=(cur_start, cur_end),
            arc_indices=list(cur_arcs),
            arc_step=None,
            title=title,
        ))
        cur_start = None
        cur_end = 0
        cur_arcs = []
        cur_titles = []
        cur_lines = 0

    for arc in arcs:
        arc_lines = arc.r[1] - arc.r[0] + 1

        if arc_lines > target_lines:
            # Arc dài — flush mega đang xây, sau đó chia arc này thành nhiều step
            flush_merged()

            # Chia đều: số step = ceil(arc_lines / target)
            import math
            n_steps = max(1, math.ceil(arc_lines / target_lines))
            step_size = math.ceil(arc_lines / n_steps)

            for k in range(n_steps):
                s = arc.r[0] + k * step_size
                e = min(arc.r[1], arc.r[0] + (k + 1) * step_size - 1)
                if s > arc.r[1]:
                    break
                megas.append(MegaChunk(
                    index=len(megas),
                    line_range=(s, e),
                    arc_indices=[arc.index],
                    arc_step=(k + 1, n_steps),
                    title=f"{arc.t} — Step {k + 1}/{n_steps}",
                ))
        else:
            # Arc ngắn — thử gộp với mega đang xây
            if cur_start is None:
                cur_start = arc.r[0]
                cur_end = arc.r[1]
                cur_arcs = [arc.index]
                cur_titles = [arc.t]
                cur_lines = arc_lines
            elif cur_lines + arc_lines <= target_lines:
                # Gộp tiếp
                cur_end = arc.r[1]
                cur_arcs.append(arc.index)
                cur_titles.append(arc.t)
                cur_lines += arc_lines
            else:
                # Vượt target — flush + mở mega mới
                flush_merged()
                cur_start = arc.r[0]
                cur_end = arc.r[1]
                cur_arcs = [arc.index]
                cur_titles = [arc.t]
                cur_lines = arc_lines

    flush_merged()
    return megas


# Backward-compat alias (code cũ có thể vẫn gọi)
def partition_into_mega_chunks(chunk_map=None, bible=None,
                                total_lines: int = 0,
                                target_lines: int = DEFAULT_MEGA_TARGET_LINES,
                                ) -> list[MegaChunk]:
    """DEPRECATED — dùng partition_into_mega_from_arcs.

    Giữ alias để code cũ không vỡ. Nếu được gọi với chunk_map thì sẽ
    cố gắng convert sang arcs (nếu có bible).
    """
    if bible is not None and total_lines > 0:
        return partition_into_mega_from_arcs(bible, total_lines, target_lines)
    logger.warning("[mega] partition_into_mega_chunks called without bible/total_lines — "
                   "trả empty (deprecated path)")
    return []


# ═════════════════════════════════════════════════════════════════
# STAGE: BIBLE UNIFIED — với preset + advanced options
# ═════════════════════════════════════════════════════════════════

# Preset definitions — mỗi preset map sang 1 set rule cho cast + glossary
BIBLE_PRESETS = {
    "compact": {
        "label": "⚡ Gọn lẹ",
        "description": (
            "MODE GỌN LẸ — chỉ tập trung vào nhân vật chính & thuật ngữ quan trọng.\n"
            "Dùng khi: phim ngắn, muốn nhanh, hoặc Bible chỉ phục vụ pipeline tự động."
        ),
        "cast_rules": (
            "Liệt kê CHỈ các nhân vật sau:\n"
            "  ✓ Nhân vật chính (nam_chinh, nu_chinh)\n"
            "  ✓ Nhân vật có ≥10 dòng thoại trong phim\n"
            "  ✓ Phản diện chính (nếu có)\n"
            "  ✗ KHÔNG đưa: nhân vật phụ <10 dòng, người ngẫu nhiên, cameo\n"
            "  ✗ KHÔNG đưa: nhân vật không có tên riêng (vd 'mẹ', 'cha')\n"
            "    TRỪ KHI họ là nhân vật cốt lõi (mẹ nam chính có 30 dòng → đưa vào)"
        ),
        "glossary_rules": (
            "Chỉ đưa các thuật ngữ TIER 1 (quan trọng nhất):\n"
            "  ✓ titles (chức vụ chính): chỉ chức danh dùng ≥5 lần\n"
            "  ✓ places_orgs (tổ chức chính): công ty/gia tộc cốt lõi của plot\n"
            "  ✓ concepts (khái niệm cốt lõi): chỉ khái niệm xuất hiện ≥5 lần\n"
            "  ✗ BỎ QUA: cliches, idioms (để dịch ad-hoc trong giai đoạn translate)\n"
            "Mục tiêu: glossary ngắn gọn, AI dịch giai đoạn sau không bị overload."
        ),
    },
    "balanced": {
        "label": "📋 Đầy đủ (khuyến nghị)",
        "description": (
            "MODE ĐẦY ĐỦ — bắt đầy đủ nhân vật + thuật ngữ quan trọng, cân bằng giữa\n"
            "độ chi tiết và độ gọn. Đây là DEFAULT cho hầu hết phim."
        ),
        "cast_rules": (
            "Liệt kê các nhân vật sau:\n"
            "  ✓ Tất cả nhân vật có TÊN RIÊNG (kể cả xuất hiện 1 dòng)\n"
            "    VD: Cố Trầm Châu, 缈缈, 颂颂, 肖叔叔\n"
            "  ✓ Nhân vật KHÔNG có tên riêng nhưng có ≥2 dòng + vai trò rõ\n"
            "    VD: 'mẹ' (5 dòng) → đưa vào với zh='妈', vi='Mẹ', role='phu'\n"
            "  ✓ Cameo có 1 dòng nhưng quan trọng cho plot (vd: cha mất nói lời cuối)\n"
            "  ✗ KHÔNG đưa: extra (路人甲), narration thuần\n"
            "Bắt đủ nhân vật là quan trọng — pipeline dịch sẽ dùng thông tin này\n"
            "để gán speaker đúng."
        ),
        "glossary_rules": (
            "Đưa các thuật ngữ TIER 1 + TIER 2:\n"
            "  ✓ titles: tất cả chức danh xuất hiện ≥2 lần\n"
            "  ✓ places_orgs: tất cả tổ chức/địa danh đặc thù\n"
            "  ✓ concepts: tất cả khái niệm thể loại\n"
            "  ✓ cliches: cliché xuất hiện ≥2 lần (giúp dịch giả nhận diện trope)\n"
            "  ✓ idioms: thành ngữ + nói đểu xuất hiện ≥1 lần (quan trọng cho dub)\n"
            "Mục tiêu: glossary đủ dùng cho 90% case dịch."
        ),
    },
    "exhaustive": {
        "label": "🔬 Cực kỳ chi tiết",
        "description": (
            "MODE CỰC CHI TIẾT — không bỏ sót gì. Dùng khi cần Bible làm tài liệu\n"
            "tham khảo dài hạn, hoặc phim phức tạp có nhiều nhân vật/thuật ngữ."
        ),
        "cast_rules": (
            "Liệt kê TẤT CẢ nhân vật có lời thoại trong phim:\n"
            "  ✓ Mọi nhân vật có tên riêng (kể cả xuất hiện 1 dòng)\n"
            "  ✓ Mọi nhân vật có vai trò rõ (mẹ, cha, bạn, sếp, đồng nghiệp...)\n"
            "  ✓ Cameo / khách mời có ≥1 dòng\n"
            "  ✓ Nhân vật vô danh nhưng có hành động ảnh hưởng plot\n"
            "    (vd: 'người lạ mặt đưa thư', 'tài xế taxi')\n"
            "  ✗ CHỈ KHÔNG đưa: narration thuần, extra hoàn toàn vô tăm tích\n"
            "Có thể có 30-60 nhân vật cho phim dài. Đó là bình thường ở mode này."
        ),
        "glossary_rules": (
            "Đưa TẤT CẢ thuật ngữ đáng chú ý:\n"
            "  ✓ titles: mọi chức danh đặc thù (kể cả 1 lần)\n"
            "  ✓ places_orgs: mọi tên riêng tổ chức/địa danh\n"
            "  ✓ concepts: mọi khái niệm thể loại + plot device\n"
            "  ✓ cliches: mọi cliché/trope nhận diện được (kể cả 1 lần)\n"
            "  ✓ idioms: mọi thành ngữ + cụm nói đểu/mỉa mai/khích bác\n"
            "Glossary có thể dài 100-200 entries. Đó là bình thường."
        ),
    },
}


# Advanced flags — khi user mở panel "Tùy chỉnh nâng cao"
BIBLE_ADVANCED_DEFAULTS = {
    # Cast inclusion
    "include_unnamed_with_role": True,    # 'mẹ', 'cha dượng' → đưa vào
    "include_single_line_named": True,    # nhân vật có tên riêng nhưng 1 dòng
    "include_cameo": True,                 # cameo quan trọng cho plot
    # Glossary nhóm — bật/tắt từng nhóm
    "glossary_titles": True,
    "glossary_places_orgs": True,
    "glossary_concepts": True,
    "glossary_cliches": True,
    "glossary_idioms": True,
    # Min frequency cho từng nhóm (override preset)
    "titles_min_freq": None,    # None = dùng preset default
    "concepts_min_freq": None,
    "idioms_min_freq": None,
}


def _resolve_bible_options(options: Optional[dict]) -> dict:
    """Merge user options với defaults. Trả dict đầy đủ."""
    opts = {
        "preset": "balanced",
        "advanced": dict(BIBLE_ADVANCED_DEFAULTS),
    }
    if not options:
        return opts
    if "preset" in options and options["preset"] in BIBLE_PRESETS:
        opts["preset"] = options["preset"]
    if "advanced" in options and isinstance(options["advanced"], dict):
        opts["advanced"].update(options["advanced"])
    return opts


def _build_cast_rules_block(preset_key: str, advanced: dict) -> str:
    """Build CAST_INCLUSION_RULES dựa vào preset + advanced flags."""
    base_rules = BIBLE_PRESETS[preset_key]["cast_rules"]

    # Nếu advanced flags khác default, thêm overrides
    overrides = []
    if not advanced.get("include_unnamed_with_role", True):
        overrides.append("  ✗ TẮT: KHÔNG đưa nhân vật không có tên riêng "
                          "(kể cả có vai trò 'mẹ', 'cha')")
    if not advanced.get("include_single_line_named", True):
        overrides.append("  ✗ TẮT: KHÔNG đưa nhân vật chỉ có 1 dòng thoại "
                          "(yêu cầu ≥2 dòng)")
    if not advanced.get("include_cameo", True):
        overrides.append("  ✗ TẮT: KHÔNG đưa cameo (kể cả quan trọng plot)")

    if overrides:
        return base_rules + "\n\nOVERRIDES từ user:\n" + "\n".join(overrides)
    return base_rules


def _build_glossary_rules_block(preset_key: str, advanced: dict) -> str:
    """Build GLOSSARY_INCLUSION_RULES dựa vào preset + advanced flags."""
    base_rules = BIBLE_PRESETS[preset_key]["glossary_rules"]

    # List các nhóm bị tắt
    disabled = []
    if not advanced.get("glossary_titles", True):
        disabled.append("titles (Chức vụ / Danh xưng)")
    if not advanced.get("glossary_places_orgs", True):
        disabled.append("places_orgs (Địa danh / Tổ chức)")
    if not advanced.get("glossary_concepts", True):
        disabled.append("concepts (Khái niệm)")
    if not advanced.get("glossary_cliches", True):
        disabled.append("cliches (Cliché / Tropes)")
    if not advanced.get("glossary_idioms", True):
        disabled.append("idioms (Thành ngữ / Nói đểu)")

    # Min frequency overrides
    freq_overrides = []
    if advanced.get("titles_min_freq") is not None:
        freq_overrides.append(f"  • titles: chỉ đưa khi xuất hiện ≥{advanced['titles_min_freq']} lần")
    if advanced.get("concepts_min_freq") is not None:
        freq_overrides.append(f"  • concepts: chỉ đưa khi xuất hiện ≥{advanced['concepts_min_freq']} lần")
    if advanced.get("idioms_min_freq") is not None:
        freq_overrides.append(f"  • idioms: chỉ đưa khi xuất hiện ≥{advanced['idioms_min_freq']} lần")

    extras = []
    if disabled:
        extras.append("\nNHÓM BỊ TẮT (để list RỖNG, đừng đưa entry vào):\n" +
                      "\n".join(f"  ✗ {d}" for d in disabled))
    if freq_overrides:
        extras.append("\nMIN FREQUENCY OVERRIDES:\n" + "\n".join(freq_overrides))

    return base_rules + "".join(extras)


def _build_bible_unified(
    db: Session, project_id: int, config: PipelineConfig,
    options: Optional[dict] = None,
) -> list[BuiltPrompt]:
    """1 prompt duy nhất → AI build cả cast+world+glossary.

    options (optional):
      {
        "preset": "compact" | "balanced" | "exhaustive",
        "advanced": {
          "include_unnamed_with_role": bool,
          "include_single_line_named": bool,
          "include_cameo": bool,
          "glossary_titles": bool,
          "glossary_places_orgs": bool,
          "glossary_concepts": bool,
          "glossary_cliches": bool,
          "glossary_idioms": bool,
          "titles_min_freq": int | null,
          "concepts_min_freq": int | null,
          "idioms_min_freq": int | null,
        }
      }
    """
    entries = _load_entries(db, project_id)
    all_subs = _format_chinese_subtitles_block(entries)
    total_lines = len(entries) if entries else 0

    opts = _resolve_bible_options(options)
    preset = BIBLE_PRESETS[opts["preset"]]

    cast_rules = _build_cast_rules_block(opts["preset"], opts["advanced"])
    glossary_rules = _build_glossary_rules_block(opts["preset"], opts["advanced"])

    template = _load_prompt_template("bible_unified", config)
    prompt = (template
              .replace("{TOTAL_LINES}", str(total_lines))
              .replace("{ALL_SUBTITLES}", all_subs)
              .replace("{PRESET_LABEL}", preset["label"])
              .replace("{PRESET_DESCRIPTION}", preset["description"])
              .replace("{CAST_INCLUSION_RULES}", cast_rules)
              .replace("{GLOSSARY_INCLUSION_RULES}", glossary_rules))

    label_extra = f" [{preset['label']}]"
    return [BuiltPrompt(
        stage="bible_unified",
        unit_key="default",
        label=f"Build Bible (cast + world + glossary){label_extra}",
        prompt=prompt,
        meta={
            "json_root_key": None,
            "expects": ["cast", "world", "glossary"],
            "preset": opts["preset"],
            "advanced": opts["advanced"],
            "total_lines": total_lines,
        },
    )]


# ═════════════════════════════════════════════════════════════════
# STAGE: CHUNKS + SCENES FULL
# ═════════════════════════════════════════════════════════════════

def _build_chunks_full(
    db: Session, project_id: int, config: PipelineConfig
) -> list[BuiltPrompt]:
    """1 prompt duy nhất → AI chia toàn phim thành chunks + scenes."""
    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)
    all_subs = _format_chinese_subtitles_block(entries)
    bible_block = _format_bible_block(bible)

    template = _load_prompt_template("chunks_scenes_full", config)
    prompt = (template
              .replace("{BIBLE_BLOCK}", bible_block)
              .replace("{ALL_SUBTITLES}", all_subs))

    return [BuiltPrompt(
        stage="chunks_full",
        unit_key="default",
        label="Chia Chunks + Scenes — toàn phim 1 paste",
        prompt=prompt,
        meta={"json_root_key": "chunks"},
    )]


# ═════════════════════════════════════════════════════════════════
# STAGE: TRANSLATE MEGA (gộp speaker + translate)
# ═════════════════════════════════════════════════════════════════

def _format_characters_in_mega(mega: MegaChunk, bible) -> str:
    """Tất cả nhân vật có liên quan đến các arc của mega-chunk.

    v4.2: lấy từ Bible cast (filter theo arc.summary mention hoặc lấy hết cast main+supporting).
    Đơn giản hóa: với mỗi mega, hiển thị toàn bộ characters tier=main+supporting,
    cộng thêm các minor xuất hiện trong arc summary.
    """
    if not bible.cast.characters:
        return "(không có nhân vật trong cast)"

    # Lấy text summary của các arc trong mega để filter minor characters
    mega_summary_text = ""
    if mega.arc_indices and bible.world.arcs:
        for ai in mega.arc_indices:
            if ai < len(bible.world.arcs):
                arc = bible.world.arcs[ai]
                mega_summary_text += " " + (getattr(arc, "summary", "") or "")
                mega_summary_text += " " + (arc.t or "")

    lines = []
    for ch in bible.cast.characters:
        tier = getattr(ch, "tier", None)
        # Luôn show main + supporting
        # Show minor/cameo nếu được nhắc trong arc summary
        if tier in ("main", "supporting"):
            include = True
        elif ch.zh in mega_summary_text or ch.vi in mega_summary_text:
            include = True
        elif tier in (None, "minor"):
            # Không có tier info — đưa vào nếu role là main/phụ
            include = ch.role in ("nam_chinh", "nu_chinh", "nam_phu", "nu_phu", "phan_dien")
        else:
            include = False

        if not include:
            continue

        age = f", {ch.age}" if ch.age else ""
        catch = f' [catchphrase: "{ch.catchphrase}"]' if getattr(ch, "catchphrase", None) else ""
        alias = ""
        if ch.alias:
            alias = f" / alias: {', '.join(ch.alias)}"
        lines.append(f"- {ch.vi} ({ch.zh}){alias}: {ch.g}, {ch.role}{age}{catch}")
        lines.append(f"    {ch.char}")
    return "\n".join(lines) if lines else "(không xác định nhân vật trong mega này)"


def _format_relationships_in_mega(mega: MegaChunk, bible) -> str:
    """Relationship giữa các nhân vật chính + supporting (đủ cho dịch).

    v4.2: đơn giản hóa — show quan hệ giữa tất cả main+supporting characters.
    """
    if not bible.cast.characters:
        return "(không có)"

    # Lấy set zh của main+supporting
    important_zh = set()
    for ch in bible.cast.characters:
        tier = getattr(ch, "tier", None)
        if tier in ("main", "supporting") or ch.role in (
            "nam_chinh", "nu_chinh", "nam_phu", "nu_phu", "phan_dien"
        ):
            important_zh.add(ch.zh)

    if not important_zh:
        return "(không có quan hệ rõ)"

    lines = []
    seen = set()
    for ch in bible.cast.characters:
        if ch.zh not in important_zh:
            continue
        for other_zh, rel in (ch.rel or {}).items():
            if other_zh not in important_zh:
                continue
            pair = tuple(sorted([ch.zh, other_zh]))
            if pair in seen:
                continue
            seen.add(pair)
            other = bible.cast.get_by_zh(other_zh)
            other_vi = other.vi if other else other_zh
            lines.append(f"- {ch.vi} ↔ {other_vi}: {rel}")
    return "\n".join(lines) if lines else "(không có quan hệ rõ)"


def _format_glossary_in_mega(mega: MegaChunk, entries_by_idx, bible) -> str:
    """Lọc glossary terms xuất hiện trong text của mega.

    v4.2: vẫn quét text TQ trong range mega để lọc terms có liên quan.
    """
    mega_text = ""
    for i in range(mega.line_range[0], mega.line_range[1] + 1):
        e = entries_by_idx.get(i)
        if e:
            mega_text += (e.text or "") + " "

    glossary = bible.glossary

    # Format mới: 5 nhóm
    has_new_format = any(
        hasattr(glossary, attr) and getattr(glossary, attr)
        for attr in ["titles", "places_orgs", "concepts", "cliches", "idioms"]
    )

    if has_new_format:
        groups = [
            ("titles", "Chức vụ / Danh xưng"),
            ("places_orgs", "Địa danh / Tổ chức"),
            ("concepts", "Khái niệm thể loại"),
            ("cliches", "Cliché / Tropes"),
            ("idioms", "Thành ngữ / Nói đểu — DỊCH THOÁT Ý, không literal"),
        ]
        out_blocks = []
        for attr, label in groups:
            items = getattr(glossary, attr, None) or []
            relevant = [t for t in items if t.zh in mega_text]
            if not relevant:
                continue
            block = [f"  ━ {label}:"]
            for t in relevant:
                note = f"  ({t.note})" if getattr(t, "note", None) else ""
                block.append(f"    - {t.zh} → \"{t.vi}\"{note}")
            out_blocks.append("\n".join(block))
        return "\n".join(out_blocks) if out_blocks else "(không có thuật ngữ trong mega này)"

    # Fallback: format cũ
    if hasattr(glossary, "find_in_text"):
        relevant = glossary.find_in_text(mega_text)
        if not relevant:
            return "(không có thuật ngữ đặc thù trong mega này)"
        lines = []
        for t in relevant:
            note = f"  ({t.note})" if getattr(t, "note", None) else ""
            lines.append(f"- {t.zh} → \"{t.vi}\"{note}")
        return "\n".join(lines)

    return "(không có thuật ngữ)"


# NOTE: _format_scenes_in_mega đã bị BỎ ở v4.2 (không còn dùng scene/chunk).


def _format_world_block(bible) -> str:
    w = bible.world
    return (f"Genre: {', '.join(w.genre)} (id: {w.genre_id})\n"
            f"Era: {w.era}\n"
            f"Tone phim: {w.tone}\n"
            f"Plot: {w.plot}")


def _format_arc_block(mega: MegaChunk, bible) -> tuple[str, str, str]:
    """Trả (arc_title, arc_tone, arc_summary). 
    
    v4.2: support cả arc-step (1 arc chia thành nhiều mega) và multi-arc merge.
    """
    if not mega.arc_indices:
        return ("(toàn phim)", "neutral", "(không xác định)")
    arcs = [bible.world.arcs[i] for i in mega.arc_indices
            if i < len(bible.world.arcs)]
    if not arcs:
        return ("(unknown)", "neutral", "(không xác định)")

    # Single arc — có thể có step info
    if len(arcs) == 1:
        a = arcs[0]
        title = a.t
        if mega.arc_step:
            step, total = mega.arc_step
            title = f"{a.t} (Step {step}/{total})"
        return (title, a.tone, getattr(a, "summary", "(không có tóm tắt)"))

    # Multi-arc merge
    titles = " → ".join(a.t for a in arcs)
    tones = " → ".join(a.tone for a in arcs)
    summaries = "\n".join(
        f"Arc {a.index}: {getattr(a, 'summary', a.t)}" for a in arcs
    )
    return (titles, tones, summaries)


def _format_dialogue_for_translate(
    entries_by_idx: dict[int, SrtEntry],
    start: int,
    end: int,
) -> str:
    """Format thoại cần dịch trong mega: idx | duration | text_zh (KHÔNG speaker)."""
    lines = []
    for i in range(start, end + 1):
        e = entries_by_idx.get(i)
        if not e:
            continue
        if not (e.text or "").strip():
            continue
        dur = max(0.1, e.duration_sec)
        lines.append(f"{e.index} | {dur:.1f}s | {e.text}")
    return "\n".join(lines) if lines else "(không có dòng)"


def _format_context_for_mega(
    entries_by_idx, speaker_map, translated_map,
    start: int, end: int,
) -> str:
    """Context block: line | speaker | text_zh | v1 (nếu đã dịch)."""
    if start > end:
        return "(không có)"
    lines = []
    for i in range(start, end + 1):
        e = entries_by_idx.get(i)
        if not e or not (e.text or "").strip():
            continue
        spk = speaker_map.get(i, {}).get("speaker_zh") or "?"
        translated = translated_map.get(i, {})
        v1 = translated.get("v1") or ""
        if v1:
            lines.append(f"{e.index} | {spk} | {e.text} → {v1}")
        else:
            lines.append(f"{e.index} | {spk} | {e.text}")
    return "\n".join(lines) if lines else "(không có)"


def _load_genre_pack_str(bible, config) -> str:
    """Tận dụng load_genre_pack có sẵn của Stage 4.

    v4.3: thêm fallback — nếu genre_id chính không có file pack,
    thử suy ra từ era + genre name list. VD genre_id="some_unknown"
    nhưng era="hiện đại" → fallback "do_thi".
    """
    try:
        from stages.stage4_translate import load_genre_pack, format_genre_pack_for_prompt

        genre_id = bible.world.genre_id or ""

        # Thử load với genre_id chính
        pack = load_genre_pack(genre_id, config)

        # v4.3: fallback nếu không có pack
        if pack is None and genre_id != "other":
            fallback_id = _infer_genre_id_fallback(bible)
            if fallback_id and fallback_id != genre_id:
                logger.info(
                    f"[mega] genre_id='{genre_id}' không có pack, "
                    f"fallback sang '{fallback_id}'"
                )
                pack = load_genre_pack(fallback_id, config)

        return format_genre_pack_for_prompt(pack)
    except Exception as e:
        logger.warning(f"[mega] load genre pack failed: {e}")
        return "(không có genre pack)"


def _infer_genre_id_fallback(bible) -> Optional[str]:
    """v4.3: suy ra genre_id phù hợp từ era + genre name list nếu pack không tồn tại.

    Ưu tiên:
      1. era cổ đại → "co_trang"
      2. era dân quốc → "dan_quoc"
      3. genre chứa "tu tiên" / "tiên hiệp" / "tu chân" → "xianxia"
      4. era hiện đại + genre chứa "tổng tài"/"CEO" → "modern_ceo_romance"
      5. era hiện đại default → "do_thi"
    """
    if not bible or not bible.world:
        return None

    era = (bible.world.era or "").lower()
    genre_list = bible.world.genre or []
    genre_str = " ".join(genre_list).lower() if genre_list else ""

    # Cổ đại
    if any(k in era for k in ["cổ đại", "co dai", "cổ", "古"]):
        return "co_trang"

    # Dân quốc
    if any(k in era for k in ["dân quốc", "dan quoc", "1920", "1930", "民国"]):
        return "dan_quoc"

    # Tu tiên / Tiên hiệp
    if any(k in genre_str for k in ["tu tiên", "tu tien", "tiên hiệp", "tien hiep",
                                      "tu chân", "huyền huyễn", "xianxia"]):
        return "xianxia"

    # Hiện đại + tổng tài → modern_ceo_romance
    if "hiện đại" in era or "hien dai" in era or "现代" in era:
        if any(k in genre_str for k in ["tổng tài", "tong tai", "ceo", "tổng giám đốc"]):
            return "modern_ceo_romance"
        return "do_thi"

    # Default
    return "do_thi"


def _build_translate_mega_one(
    mega: MegaChunk, entries, entries_by_idx, bible,
    speaker_map, translated_map, config: PipelineConfig,
    speaker_mode: str = "full",
) -> BuiltPrompt:
    """Build prompt cho 1 mega-chunk (v4.3: hỗ trợ 3 speaker_mode)."""
    from manual.speaker_modes import (
        format_speaker_block_for_prompt, get_speaker_field_hint, MODE_INFO,
    )

    start, end = mega.line_range

    # Context before/after
    ctx_before = _format_context_for_mega(
        entries_by_idx, speaker_map, translated_map,
        max(1, start - MEGA_CHUNK_OVERLAP_LINES), start - 1,
    )
    ctx_after = _format_context_for_mega(
        entries_by_idx, speaker_map, translated_map,
        end + 1, min(len(entries), end + MEGA_CHUNK_OVERLAP_LINES),
    )

    arc_title, arc_tone, arc_summary = _format_arc_block(mega, bible)

    # v4.3: build speaker block tương ứng với mode
    speaker_block = format_speaker_block_for_prompt(speaker_mode, bible)
    speaker_hint = get_speaker_field_hint(speaker_mode)

    template = _load_prompt_template("translate_mega", config)
    prompt = (template
              .replace("{WORLD_BLOCK}", _format_world_block(bible))
              .replace("{CHARACTERS_IN_CHUNK}", _format_characters_in_mega(mega, bible))
              .replace("{RELATIONSHIPS}", _format_relationships_in_mega(mega, bible))
              .replace("{GLOSSARY_CHUNK}", _format_glossary_in_mega(mega, entries_by_idx, bible))
              .replace("{GENRE_PACK}", _load_genre_pack_str(bible, config))
              .replace("{ARC_TITLE}", arc_title)
              .replace("{ARC_TONE}", arc_tone)
              .replace("{ARC_SUMMARY}", arc_summary)
              .replace("{CONTEXT_BEFORE}", ctx_before)
              .replace("{CONTEXT_AFTER}", ctx_after)
              .replace("{DIALOGUE_INPUT}", _format_dialogue_for_translate(
                  entries_by_idx, start, end))
              .replace("{SPEAKER_BLOCK}", speaker_block)
              .replace("{SPEAKER_FIELD_HINT}", speaker_hint))

    # v4.2 — template không còn {SCENES_IN_CHUNK}, nhưng nếu template cũ vẫn dùng,
    # ta vẫn replace bằng empty để không break.
    if "{SCENES_IN_CHUNK}" in prompt:
        prompt = prompt.replace("{SCENES_IN_CHUNK}", "(v4.2: không dùng scene)")

    label = f"Mega {mega.index + 1} [dòng {start}-{end}, {end - start + 1} dòng]"
    if mega.arc_step:
        step, total = mega.arc_step
        label += f" — {mega.title} (Step {step}/{total})"
    elif mega.title:
        label += f": {mega.title}"

    # v4.3: thêm hint mode vào label
    mode_label = MODE_INFO.get(speaker_mode, {}).get("label", speaker_mode)
    label += f"  ·  Mode: {mode_label}"

    return BuiltPrompt(
        stage="translate_mega",
        unit_key=f"mega_{mega.index}",
        label=label,
        prompt=prompt,
        meta={
            "mega_index": mega.index,
            "line_range": [start, end],
            "arc_indices": mega.arc_indices,
            "arc_step": list(mega.arc_step) if mega.arc_step else None,
            "json_root_key": "lines",
            "expects_new_terms": True,
            "speaker_mode": speaker_mode,   # v4.3
        },
    )


def _build_translate_mega(
    db: Session, project_id: int, config: PipelineConfig,
    unit_key: Optional[str] = None,
    options: Optional[dict] = None,
) -> list[BuiltPrompt]:
    """v4.3: nhận options.speaker_mode ∈ {full, medium, simple}."""
    from manual.speaker_modes import MODE_INFO

    # Resolve speaker_mode (default full)
    speaker_mode = "full"
    if options and isinstance(options, dict):
        sm = options.get("speaker_mode")
        if sm in MODE_INFO:
            speaker_mode = sm
        elif sm:
            logger.warning(f"[mega translate] Unknown speaker_mode '{sm}', dùng 'full'")

    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)
    entries_by_idx = {e.index: e for e in entries}
    total_lines = len(entries)

    # Speaker map có thể rỗng nếu user skip speaker stage
    try:
        from manual.prompt_builders import _load_speaker_map
        speaker_map = _load_speaker_map(db, project_id)
    except Exception:
        speaker_map = {}

    translated_map = _load_translated_lines(db, project_id)

    # v4.2: partition dựa vào Bible.arcs, target lấy từ Project config
    target = _resolve_mega_target(db, project_id)
    megas = partition_into_mega_from_arcs(bible, total_lines, target)

    prompts = []
    for mega in megas:
        uk = f"mega_{mega.index}"
        if unit_key and unit_key != uk:
            continue
        prompts.append(_build_translate_mega_one(
            mega, entries, entries_by_idx, bible,
            speaker_map, translated_map, config,
            speaker_mode=speaker_mode,
        ))
    if unit_key and not prompts:
        raise ValueError(f"Mega-chunk unit '{unit_key}' không tồn tại.")
    return prompts


def list_mega_units(db: Session, project_id: int) -> list[StageUnit]:
    """Liệt kê các mega-chunks cho frontend (v4.2: từ Bible arcs)."""
    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)
    total_lines = len(entries)
    target = _resolve_mega_target(db, project_id)
    megas = partition_into_mega_from_arcs(bible, total_lines, target)

    out = []
    for m in megas:
        n_lines = m.line_range[1] - m.line_range[0] + 1
        label_main = f"Mega {m.index + 1} [dòng {m.line_range[0]}-{m.line_range[1]}, {n_lines} dòng]"
        if m.arc_step:
            step, total = m.arc_step
            label = f"{label_main} — {m.title} (Step {step}/{total})"
        elif m.title:
            label = f"{label_main}: {m.title}"
        else:
            label = label_main
        out.append(StageUnit(unit_key=f"mega_{m.index}", label=label))
    return out


# ═════════════════════════════════════════════════════════════════
# STAGE: REVIEW PASS 1 — consistency scan
# ═════════════════════════════════════════════════════════════════

def _scan_consistency_issues(
    db: Session, project_id: int, bible, entries, translated_map,
) -> list[dict]:
    """Code-based scan để tìm các issue khả nghi.

    Trả về list dict issues, mỗi dict có: id, type, line_index, speaker, 
    current_v1, context_before, context_after, detail.
    """
    import re

    issues = []
    issue_id_counter = 0

    def next_id():
        nonlocal issue_id_counter
        issue_id_counter += 1
        return f"issue_{issue_id_counter:03d}"

    def get_context(line_idx, span=REVIEW_CONTEXT_LINES):
        before = []
        after = []
        for j in range(line_idx - span, line_idx):
            t = translated_map.get(j)
            if t and t.get("v1"):
                before.append(f"{j} | {t.get('speaker_zh') or '?'} | {t['v1']}")
        for j in range(line_idx + 1, line_idx + span + 1):
            t = translated_map.get(j)
            if t and t.get("v1"):
                after.append(f"{j} | {t.get('speaker_zh') or '?'} | {t['v1']}")
        return "\n".join(before) or "(không có)", "\n".join(after) or "(không có)"

    # Build name → canonical name map từ bible
    canonical_vi = {ch.vi: ch.vi for ch in bible.cast.characters}
    for ch in bible.cast.characters:
        canonical_vi[ch.vi] = ch.vi  # canonical
        # Detect các alias hoặc phiên âm khác
        # (đơn giản: chỉ check exact tên vi trong dòng dịch)

    # Build glossary lookup
    glossary_map = {}  # zh → vi
    for t in bible.glossary.terms:
        glossary_map[t.zh] = t.vi

    # Sort line indices
    sorted_lines = sorted(translated_map.keys())

    # Pronoun pairs để detect shift
    formal_pronouns = {"ngài", "tiểu thư", "công tử", "đại nhân", "phu nhân"}
    casual_pronouns = {"anh", "em", "cậu", "tớ", "bạn"}
    very_casual = {"mày", "tao", "nó"}

    prev_v1_by_speaker_pair = {}  # (spk_a, spk_b) → last v1

    for line_idx in sorted_lines:
        t = translated_map.get(line_idx, {})
        v1 = t.get("v1") or ""
        spk = t.get("speaker_zh") or "?"
        text_zh = t.get("text_zh") or ""

        if not v1:
            # Check nếu zh có content nhưng v1 rỗng → EMPTY_LINE
            if text_zh.strip() and any(c for c in text_zh if '\u4e00' <= c <= '\u9fff'):
                # Có thể là noise, để AI quyết
                before, after = get_context(line_idx)
                issues.append({
                    "id": next_id(),
                    "type": "EMPTY_LINE",
                    "line_index": line_idx,
                    "speaker": spk,
                    "current_v1": "",
                    "text_zh": text_zh,
                    "context_before": before,
                    "context_after": after,
                    "detail": "Dòng có thoại TQ nhưng v1 rỗng — có thể bị bỏ sót",
                })
            continue

        v1_lower = v1.lower()

        # 1. RESIDUAL_CHINESE
        if re.search(r"[\u4e00-\u9fff]", v1):
            before, after = get_context(line_idx)
            issues.append({
                "id": next_id(),
                "type": "RESIDUAL_CHINESE",
                "line_index": line_idx,
                "speaker": spk,
                "current_v1": v1,
                "text_zh": text_zh,
                "context_before": before,
                "context_after": after,
                "detail": "Bản dịch v1 còn chứa Hán tự chưa dịch",
            })

        # 2. GLOSSARY_VIOLATION
        for zh_term, vi_term in glossary_map.items():
            if zh_term in text_zh and vi_term.lower() not in v1_lower:
                # Có thuật ngữ trong zh nhưng v1 không có bản dịch glossary
                before, after = get_context(line_idx)
                issues.append({
                    "id": next_id(),
                    "type": "GLOSSARY_VIOLATION",
                    "line_index": line_idx,
                    "speaker": spk,
                    "current_v1": v1,
                    "text_zh": text_zh,
                    "context_before": before,
                    "context_after": after,
                    "detail": f"zh có '{zh_term}' (glossary→'{vi_term}') "
                              f"nhưng v1 không dùng bản dịch này",
                })
                break  # chỉ flag 1 lần/dòng

        # 3. PRONOUN_SHIFT — so với 5 dòng gần nhất cùng speaker
        if spk and spk != "?":
            v1_pronouns_formal = any(p in v1_lower for p in formal_pronouns)
            v1_pronouns_casual = any(p in v1_lower.split() for p in casual_pronouns)

            # Check dòng cùng speaker gần nhất
            for j in range(line_idx - 1, max(0, line_idx - 6), -1):
                prev = translated_map.get(j, {})
                if prev.get("speaker_zh") != spk:
                    continue
                prev_v1 = (prev.get("v1") or "").lower()
                if not prev_v1:
                    continue
                prev_formal = any(p in prev_v1 for p in formal_pronouns)
                prev_casual = any(p in prev_v1.split() for p in casual_pronouns)
                if (prev_casual and v1_pronouns_formal) or (prev_formal and v1_pronouns_casual):
                    before, after = get_context(line_idx)
                    issues.append({
                        "id": next_id(),
                        "type": "PRONOUN_SHIFT",
                        "line_index": line_idx,
                        "speaker": spk,
                        "current_v1": v1,
                        "text_zh": text_zh,
                        "context_before": before,
                        "context_after": after,
                        "detail": f"Xưng hô shift đột ngột so với dòng {j} cùng speaker "
                                  f"(formal↔casual)",
                    })
                break

        # 4. CPS_TOO_HIGH
        e = next((entry for entry in entries if entry.index == line_idx), None)
        if e:
            dur = max(0.1, e.duration_sec)
            cps = len(v1) / dur if dur > 0 else 0
            if cps > 25:
                before, after = get_context(line_idx)
                issues.append({
                    "id": next_id(),
                    "type": "CPS_TOO_HIGH",
                    "line_index": line_idx,
                    "speaker": spk,
                    "current_v1": v1,
                    "text_zh": text_zh,
                    "context_before": before,
                    "context_after": after,
                    "detail": f"CPS={cps:.1f} (dur={dur:.1f}s, {len(v1)} ký tự) — quá cao cho TTS",
                })

    return issues


def _format_issues_block(issues: list[dict]) -> str:
    """Format issues thành text block đẹp cho prompt."""
    if not issues:
        return "(KHÔNG CÓ ISSUE NÀO — không cần Pass 1)"
    blocks = []
    for issue in issues:
        block = (
            f"┌─ {issue['id']} [{issue['type']}] dòng {issue['line_index']}\n"
            f"│  speaker: {issue['speaker']}\n"
            f"│  text_zh: {issue.get('text_zh', '')}\n"
            f"│  current_v1: {issue['current_v1'] or '(rỗng)'}\n"
            f"│  detail: {issue['detail']}\n"
            f"│  --- context before ---\n"
            f"│  {issue['context_before'].replace(chr(10), chr(10) + '│  ')}\n"
            f"│  --- context after ---\n"
            f"│  {issue['context_after'].replace(chr(10), chr(10) + '│  ')}\n"
            f"└─"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _build_review_pass1(
    db: Session, project_id: int, config: PipelineConfig,
) -> list[BuiltPrompt]:
    """Build prompt Review Pass 1 — consistency scan."""
    bible = _load_bible(db, project_id)
    entries = _load_entries(db, project_id)
    translated_map = _load_translated_lines(db, project_id)

    issues = _scan_consistency_issues(db, project_id, bible, entries, translated_map)

    if not issues:
        return [BuiltPrompt(
            stage="review_pass1",
            unit_key="default",
            label="Review Pass 1 — không có issue nào (skip)",
            prompt="(Tool không phát hiện issue nào cần review. Pass 1 skip.)",
            meta={"issue_count": 0, "issues": []},
        )]

    template = _load_prompt_template("review_pass1_consistency", config)
    bible_block = _format_bible_block(bible)
    issues_block = _format_issues_block(issues)

    prompt = (template
              .replace("{BIBLE_BLOCK}", bible_block)
              .replace("{ISSUES_BLOCK}", issues_block))

    return [BuiltPrompt(
        stage="review_pass1",
        unit_key="default",
        label=f"Review Pass 1 — {len(issues)} issues phát hiện",
        prompt=prompt,
        meta={
            "issue_count": len(issues),
            "issues": issues,  # giữ để parser map id → line_index khi apply
            "json_root_key": "decisions",
        },
    )]


# ═════════════════════════════════════════════════════════════════
# STAGE: REVIEW PASS 2 — per-arc polish
# ═════════════════════════════════════════════════════════════════

def _format_translated_dialogue_for_arc(
    arc, entries_by_idx, translated_map,
) -> str:
    """Format thoại đã dịch của 1 arc cho Pass 2 review."""
    lines = []
    for i in range(arc.r[0], arc.r[1] + 1):
        e = entries_by_idx.get(i)
        if not e or not (e.text or "").strip():
            continue
        t = translated_map.get(i, {})
        v1 = t.get("v1") or "(chưa dịch)"
        v2 = t.get("v2") or "null"
        spk = t.get("speaker_zh") or "?"
        lines.append(f"{i} | {spk} | {e.text} | v1: {v1} | v2: {v2}")
    return "\n".join(lines) if lines else "(không có dòng)"


def _format_scenes_in_arc(arc, chunk_map=None) -> str:
    """v4.2: không còn scene structure, chỉ hiện info arc gọn."""
    lines = [
        f"Arc {arc.index}: {arc.t}",
        f"Range: [{arc.r[0]}, {arc.r[1]}] ({arc.r[1] - arc.r[0] + 1} dòng)",
        f"Tone: {arc.tone}",
    ]
    summary = getattr(arc, "summary", None)
    if summary:
        lines.append(f"Summary: {summary}")
    return "\n".join(lines)


def _build_review_pass2_one_arc(
    arc, entries_by_idx, bible, translated_map, config,
) -> BuiltPrompt:
    """v4.2: không còn cần chunk_map."""
    template = _load_prompt_template("review_pass2_polish", config)
    bible_block = _format_bible_block(bible)
    arc_summary = getattr(arc, "summary", "(không có tóm tắt)")

    prompt = (template
              .replace("{BIBLE_BLOCK}", bible_block)
              .replace("{ARC_TITLE}", arc.t)
              .replace("{ARC_TONE}", arc.tone)
              .replace("{ARC_SUMMARY}", arc_summary)
              .replace("{SCENES_IN_ARC}", _format_scenes_in_arc(arc))
              .replace("{TRANSLATED_DIALOGUE}",
                       _format_translated_dialogue_for_arc(arc, entries_by_idx, translated_map)))

    return BuiltPrompt(
        stage="review_pass2",
        unit_key=f"arc_{arc.index}",
        label=f"Review Pass 2 — Arc {arc.index}: {arc.t} (dòng {arc.r[0]}-{arc.r[1]})",
        prompt=prompt,
        meta={
            "arc_index": arc.index,
            "line_range": [arc.r[0], arc.r[1]],
            "json_root_key": "fixes",
        },
    )


def _build_review_pass2(
    db: Session, project_id: int, config: PipelineConfig,
    unit_key: Optional[str] = None,
) -> list[BuiltPrompt]:
    entries = _load_entries(db, project_id)
    bible = _load_bible(db, project_id)
    translated_map = _load_translated_lines(db, project_id)
    entries_by_idx = {e.index: e for e in entries}

    prompts = []
    for arc in bible.world.arcs:
        uk = f"arc_{arc.index}"
        if unit_key and unit_key != uk:
            continue
        prompts.append(_build_review_pass2_one_arc(
            arc, entries_by_idx, bible, translated_map, config,
        ))
    if unit_key and not prompts:
        raise ValueError(f"Pass 2 unit '{unit_key}' không tồn tại.")
    return prompts


# ═════════════════════════════════════════════════════════════════
# PUBLIC DISPATCHER (extends manual.prompt_builders)
# ═════════════════════════════════════════════════════════════════

_MEGA_BUILDERS = {
    "bible_unified":   _build_bible_unified,
    # "chunks_full":   BỎ ở v4.2 — không còn dùng chunks/scenes nữa
    "translate_mega":  _build_translate_mega,
    "review_pass1":    _build_review_pass1,
    "review_pass2":    _build_review_pass2,
}

_MEGA_MULTI_UNIT = {"translate_mega", "review_pass2"}


def build_prompt_mega(
    stage: str,
    db: Session,
    project_id: int,
    config: PipelineConfig,
    unit_key: Optional[str] = None,
    options: Optional[dict] = None,
) -> list[BuiltPrompt]:
    """Build prompt cho stages mega (v4 manual mode).

    options (optional): stage-specific config passed to builder.
      Hiện tại chỉ bible_unified support options (preset + advanced flags).
      Các stage khác ignore options.
    """
    if stage not in _MEGA_BUILDERS:
        raise ValueError(
            f"Stage '{stage}' không hợp lệ cho mega mode. "
            f"Hợp lệ: {list(_MEGA_BUILDERS.keys())}"
        )
    builder = _MEGA_BUILDERS[stage]

    # bible_unified hỗ trợ options
    if stage == "bible_unified":
        return builder(db, project_id, config, options=options)
    # v4.3: translate_mega hỗ trợ options (speaker_mode)
    if stage == "translate_mega":
        return builder(db, project_id, config, unit_key=unit_key, options=options)
    # Multi-unit khác
    if stage in _MEGA_MULTI_UNIT:
        return builder(db, project_id, config, unit_key=unit_key)
    # Single-unit khác
    return builder(db, project_id, config)


def list_units_mega(
    stage: str,
    db: Session,
    project_id: int,
    config: PipelineConfig,
) -> list[StageUnit]:
    """List units cho stages mega."""
    if stage not in _MEGA_BUILDERS:
        raise ValueError(f"Stage '{stage}' không hợp lệ cho mega mode")
    if stage not in _MEGA_MULTI_UNIT:
        return [StageUnit(unit_key="default", label=stage)]
    if stage == "translate_mega":
        return list_mega_units(db, project_id)
    if stage == "review_pass2":
        bible = _load_bible(db, project_id)
        return [
            StageUnit(
                unit_key=f"arc_{arc.index}",
                label=f"Arc {arc.index}: {arc.t} (dòng {arc.r[0]}-{arc.r[1]})",
            )
            for arc in bible.world.arcs
        ]
    return []
