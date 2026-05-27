"""
Speaker modes cho Manual Translate Mega v4.3.

3 modes:
  - full:    AI gán speaker_zh chính xác (tên TQ), 1 character → 1 voice slot riêng
             (UI mapping: mỗi character pick 1 Role)

  - medium:  AI vẫn gán speaker_zh, tool tự map sang 7 slot cố định
             dựa vào Character.role + gender trong Bible.
             (UI mapping: 7 slot, mỗi slot pick 1 Role)
             Slots: NAM_CHINH, NU_CHINH, PHAN_DIEN_NAM, PHAN_DIEN_NU,
                    NAM_PHU, NU_PHU, NARRATION

  - simple:  AI gán trực tiếp M / F (2 slot only)
             (UI mapping: 2 slot, mỗi slot pick 1 Role)
             Slots: M, F

Lưu vào DB:
  - Subtitle.speaker_zh: tên TQ gốc (vẫn lưu cho mọi mode để giữ data)
  - Subtitle.speaker_slot: slot key (NULL với mode FULL, có với MEDIUM/SIMPLE)
"""
from typing import Optional


# ═════════════════════════════════════════════════════════════════
# SLOT DEFINITIONS
# ═════════════════════════════════════════════════════════════════
MEDIUM_SLOTS = [
    {"key": "NAM_CHINH",       "label": "Nam chính",
     "hint": "Giọng nam trầm, ấm, tự tin"},
    {"key": "NU_CHINH",        "label": "Nữ chính",
     "hint": "Giọng nữ trẻ, mềm"},
    {"key": "PHAN_DIEN_NAM",   "label": "Phản diện nam",
     "hint": "Giọng nam dữ / sắc lẹm / lạnh"},
    {"key": "PHAN_DIEN_NU",    "label": "Phản diện nữ",
     "hint": "Giọng nữ sắc lẹm / chua / kiêu"},
    {"key": "NAM_PHU",         "label": "Nam phụ (mọi nam khác)",
     "hint": "Giọng nam phổ thông"},
    {"key": "NU_PHU",          "label": "Nữ phụ (mọi nữ khác)",
     "hint": "Giọng nữ phổ thông"},
    {"key": "NARRATION",       "label": "Voice-over / Narration",
     "hint": "Giọng người dẫn, trung tính"},
]

MEDIUM_SLOT_KEYS = {s["key"] for s in MEDIUM_SLOTS}

SIMPLE_SLOTS = [
    {"key": "M", "label": "Nam (mọi nhân vật nam)",
     "hint": "1 giọng nam dùng cho tất cả"},
    {"key": "F", "label": "Nữ (mọi nhân vật nữ)",
     "hint": "1 giọng nữ dùng cho tất cả"},
]

SIMPLE_SLOT_KEYS = {s["key"] for s in SIMPLE_SLOTS}


MODE_INFO = {
    "full": {
        "label": "Đầy đủ — 1 voice / character",
        "description": "AI gán tên TQ chính xác. Mỗi nhân vật map 1 voice riêng. "
                       "Phù hợp khi có studio nhiều giọng (10+ voice).",
        "template": "translate_mega_full",
    },
    "medium": {
        "label": "Vừa — 7 slot cố định",
        "description": "AI gán tên TQ, tool tự map về 7 slot (Nam/Nữ chính, "
                       "Phản diện nam/nữ, Nam/Nữ phụ, Narration). "
                       "Phù hợp studio 5-7 voice.",
        "template": "translate_mega_medium",
    },
    "simple": {
        "label": "Đơn giản — Nam / Nữ",
        "description": "AI gán trực tiếp M (nam) hoặc F (nữ). "
                       "Phù hợp studio 2 voice (1 nam, 1 nữ).",
        "template": "translate_mega_simple",
    },
}


# ═════════════════════════════════════════════════════════════════
# MAP CHARACTER → SLOT (cho Mode MEDIUM)
# ═════════════════════════════════════════════════════════════════

def character_to_medium_slot(character) -> Optional[str]:
    """Map 1 Character object sang slot key cho Mode MEDIUM.

    Logic theo thứ tự ưu tiên:
      1. role == 'nam_chinh' → NAM_CHINH
      2. role == 'nu_chinh'  → NU_CHINH
      3. role == 'phan_dien' → PHAN_DIEN_NAM/NU theo gender
      4. role ∈ {nam_phu, phu, khach} + g='nam' → NAM_PHU
      5. role ∈ {nu_phu, phu, khach}  + g='nu'  → NU_PHU
      6. Fallback: theo gender → NAM_PHU / NU_PHU
      7. Không xác định → None

    Tham số 'character' có thể là V3Character (pydantic) hoặc dict.
    """
    if character is None:
        return None

    # Hỗ trợ cả pydantic và dict
    role = getattr(character, "role", None) or (character.get("role") if isinstance(character, dict) else None) or ""
    g = getattr(character, "g", None) or (character.get("g") if isinstance(character, dict) else None) or "?"
    role = (role or "").strip().lower()
    g = (g or "?").strip().lower()

    if role == "nam_chinh":
        return "NAM_CHINH"
    if role == "nu_chinh":
        return "NU_CHINH"
    if role == "phan_dien":
        if g == "nam":
            return "PHAN_DIEN_NAM"
        if g == "nu":
            return "PHAN_DIEN_NU"
        # Gender không rõ — đoán theo tier hoặc default NAM
        return "PHAN_DIEN_NAM"

    # Còn lại: phu/khach/nam_phu/nu_phu → map theo gender
    if g == "nam":
        return "NAM_PHU"
    if g == "nu":
        return "NU_PHU"

    return None


def character_to_simple_slot(character) -> Optional[str]:
    """Map 1 Character object sang M/F cho Mode SIMPLE.

    Chỉ dựa vào gender. Không phân vai trò.
    """
    if character is None:
        return None
    g = getattr(character, "g", None) or (character.get("g") if isinstance(character, dict) else None) or "?"
    g = (g or "?").strip().lower()
    if g == "nam":
        return "M"
    if g == "nu":
        return "F"
    return None


def build_character_to_slot_map(bible, mode: str) -> dict[str, str]:
    """Build dict {character.zh: slot_key} cho mode đã chọn.

    Bible là V3Bible. Trả về dict tra cứu nhanh khi parse response.
    """
    out = {}
    if not bible or not bible.cast or not bible.cast.characters:
        return out

    if mode == "medium":
        mapper = character_to_medium_slot
    elif mode == "simple":
        mapper = character_to_simple_slot
    else:
        # Mode full không cần map
        return {}

    for ch in bible.cast.characters:
        slot = mapper(ch)
        if slot is None:
            continue
        # Map cả zh chính + aliases
        out[ch.zh] = slot
        for a in (ch.alias or []):
            out[a] = slot

    return out


# ═════════════════════════════════════════════════════════════════
# FORMAT SLOT LIST CHO PROMPT (inject vào template)
# ═════════════════════════════════════════════════════════════════

def format_slot_list_for_prompt(mode: str, bible=None) -> str:
    """Format slot list để inject vào prompt template.

    Với mode medium, kèm theo gợi ý: với mỗi slot, character nào trong Bible sẽ thuộc slot đó.
    """
    if mode == "full":
        return "(Mode FULL — không dùng slot, AI gán tên TQ chính xác)"

    if mode == "simple":
        lines = ["DANH SÁCH SLOT (BẮT BUỘC dùng chính xác key):"]
        for s in SIMPLE_SLOTS:
            lines.append(f"  • {s['key']}  — {s['label']}")
        lines.append("")
        lines.append("Mọi dòng thoại phải có spk = 'M' hoặc 'F'.")
        lines.append("Nếu không xác định được giới tính, đoán theo context và xưng hô.")
        lines.append("Voice-over / narration → coi như M hoặc F tùy giọng (mặc định M).")
        return "\n".join(lines)

    # medium
    lines = ["DANH SÁCH 7 SLOT (BẮT BUỘC dùng chính xác key):"]
    for s in MEDIUM_SLOTS:
        lines.append(f"  • {s['key']}  — {s['label']}  ({s['hint']})")

    if bible and bible.cast and bible.cast.characters:
        # Build mapping minh họa cho AI
        lines.append("")
        lines.append("GỢI Ý MAP NHÂN VẬT → SLOT (auto detect từ Bible):")
        grouped: dict[str, list[str]] = {s["key"]: [] for s in MEDIUM_SLOTS}
        for ch in bible.cast.characters:
            slot = character_to_medium_slot(ch)
            if slot and slot in grouped:
                grouped[slot].append(f"{ch.vi} ({ch.zh})")
        for slot_key, items in grouped.items():
            if items:
                shown = items[:6]
                more = f" ... +{len(items)-6} khác" if len(items) > 6 else ""
                lines.append(f"  → {slot_key}: {', '.join(shown)}{more}")

    lines.append("")
    lines.append("LƯU Ý: AI vẫn gán tên TQ chính xác (ví dụ 顾沉舟), KHÔNG gán slot key.")
    lines.append("Tool sẽ tự map tên TQ → slot dựa trên gợi ý trên.")
    lines.append("Lý do: giữ data character gốc + có thể đổi mode mà không phải dịch lại.")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════
# RESOLVE SLOT TỪ SPEAKER STRING (dùng khi parse response)
# ═════════════════════════════════════════════════════════════════

def resolve_slot_from_speaker(
    spk: str, mode: str, char_to_slot: dict[str, str],
) -> Optional[str]:
    """Lookup slot từ giá trị 'spk' AI trả về.

    - Mode full:   trả None (không dùng slot, dùng character_id)
    - Mode medium: spk là tên TQ → tra char_to_slot
                   Nếu spk = 'narration' → trả 'NARRATION'
                   Nếu không tìm thấy → None
    - Mode simple: spk là 'M' / 'F' → trả luôn (validated)
                   Nếu spk là tên TQ thì cũng tra char_to_slot (fallback)
    """
    if not spk or spk in ("?", ""):
        return None

    if mode == "full":
        return None

    if mode == "simple":
        spk_upper = spk.upper().strip()
        if spk_upper in SIMPLE_SLOT_KEYS:
            return spk_upper
        # Fallback: nếu AI lỡ trả tên TQ thay vì M/F
        return char_to_slot.get(spk)

    if mode == "medium":
        spk_clean = spk.strip()

        # Đặc biệt: narration
        if spk_clean.lower() in ("narration", "narrator", "voice-over", "voiceover"):
            return "NARRATION"

        # Trường hợp AI lỡ trả slot key thay vì tên TQ
        spk_upper = spk_clean.upper()
        if spk_upper in MEDIUM_SLOT_KEYS:
            return spk_upper

        # Tra theo tên TQ / alias
        return char_to_slot.get(spk_clean)

    return None


# ═════════════════════════════════════════════════════════════════
# SCHEMA HELPER: hint cho output JSON
# ═════════════════════════════════════════════════════════════════

def get_speaker_field_hint(mode: str) -> str:
    """Trả về hint cho field 'spk' trong JSON output schema."""
    if mode == "simple":
        return ('spk: "M" hoặc "F" '
                '(M=nam, F=nữ). Bắt buộc dùng đúng 2 ký tự này.')
    if mode == "medium":
        return ('spk: tên TQ chính xác của nhân vật (vd "顾沉舟"). '
                'KHÔNG tự đặt slot key — tool sẽ tự map. '
                'Nếu là voice-over thì spk="narration".')
    # full
    return ('spk: tên TQ chính xác của nhân vật (vd "顾沉舟"), '
            'hoặc "?" nếu không xác định, '
            '"narration" cho voice-over, "crowd" cho đám đông.')


# ═════════════════════════════════════════════════════════════════
# FORMAT FULL SPEAKER BLOCK CHO PROMPT
# ═════════════════════════════════════════════════════════════════

def _speaker_block_full() -> str:
    return """\
Với mỗi dòng, xác định speaker_zh dựa vào:
- <characters>: danh sách nhân vật trong arc này
- Nội dung thoại (xưng hô, đại từ tự xưng)
- Mạch hội thoại trước-sau (luân phiên A→B→A→B)
- <context_before> và <context_after> (hiểu ai đang nói chuyện với ai)

Quy tắc:
- Dùng EXACT tên zh trong <characters> (vd "顾沉舟", không phải "Gu Chenzhou")
- Nếu nhân vật được nhắc trong alias, vẫn dùng tên ZH CHÍNH (zh field), không dùng alias
- Nếu thật sự không xác định được → "?"
- Voice-over / narration → "narration"
- Crowd / nhiều người nói cùng lúc → "crowd"
"""


def _speaker_block_medium(bible) -> str:
    slot_table = format_slot_list_for_prompt("medium", bible)
    return f"""\
🎙️ MODE LỒNG TIẾNG MEDIUM — Studio có 7 voice slot.

Bạn VẪN gán tên TQ chính xác (như "顾沉舟", "苏念"...) cho speaker_zh.
TOOL sẽ tự động map tên TQ → 1 trong 7 slot voice bên dưới dựa vào
role + giới tính trong Bible.

{slot_table}

Quy tắc gán speaker_zh:
- Dùng EXACT tên zh trong <characters> (vd "顾沉舟")
- Nếu nhân vật trong alias, vẫn dùng tên ZH CHÍNH
- Nếu KHÔNG xác định được → "?"
- Voice-over / narration → "narration" (sẽ map vào slot NARRATION)
- Crowd → "crowd"

Mục tiêu: giữ data character đầy đủ cho dễ debug, đồng thời gán đúng để
tool map sang 7 voice slot. Cùng 1 nhân vật phụ → cùng 1 tên TQ qua các dòng,
tool sẽ tự gộp về NAM_PHU hoặc NU_PHU.
"""


def _speaker_block_simple() -> str:
    return """\
🎙️ MODE LỒNG TIẾNG SIMPLE — Studio chỉ có 2 voice (1 nam, 1 nữ).

Bạn gán TRỰC TIẾP "M" hoặc "F" vào field spk, KHÔNG dùng tên TQ.

  • spk = "M" — dòng do nhân vật NAM nói
  • spk = "F" — dòng do nhân vật NỮ nói
  • spk = "?" — chỉ với noise lines (v1="", v2="")

Cách xác định giới tính:
- Đọc <characters>: tra g (gender) của nhân vật đang nói
- Xưng hô tự gọi mình ("anh", "chú", "ông" → nam; "chị", "cô", "em" → nữ tùy ngữ cảnh)
- Mạch hội thoại + cách người khác gọi nhân vật
- Voice-over / narration → đoán theo giọng đọc (mặc định M nếu không rõ)
- Crowd nhiều giọng → đoán theo giới tính chủ đạo, mặc định M

KHÔNG được dùng:
  ✗ "narration"  → phải là M hoặc F
  ✗ "crowd"      → phải là M hoặc F
  ✗ tên TQ       → phải là M hoặc F
  ✗ male/female  → phải là M hoặc F (1 ký tự duy nhất)

Mục tiêu: tối giản. Studio chỉ có 2 voice → mọi dòng phải gán được M/F.
"""


def format_speaker_block_for_prompt(mode: str, bible=None) -> str:
    """Trả về nội dung block SPEAKER ASSIGNMENT cho prompt theo mode."""
    if mode == "simple":
        return _speaker_block_simple()
    if mode == "medium":
        return _speaker_block_medium(bible)
    return _speaker_block_full()
